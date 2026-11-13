#!/usr/bin/env python3
"""Record S8 integrated hub coordination (T15, A section 15 p21) against real ROS nodes.

Each episode starts the complete S8 graph in fresh processes, resets it with one seed,
and applies the A section 15.1 stimulus schedule: warm-up, a passenger rush, two
simultaneous parking requests, an escort, a pedestrian in C, a lower-road obstruction
and its removal. The same seeds run under reactive and predictive dispatch.

Safety acceptance (A section 15.3) is evaluated separately from service metrics:
zero collisions, zero overlapping crossing ownership, zero double allocations and zero
duplicate bus dispatches while a mission is active. Lower waiting time never
compensates for a violation.
"""

import argparse
from collections import deque
import hashlib
import json
import math
from pathlib import Path
import random
import statistics
import subprocess
import time
import traceback

from action_msgs.msg import GoalStatus
from ament_index_python.packages import get_package_prefix
import rclpy
from rclpy.action import ActionClient
from rclpy.node import Node
from rclpy.parameter import Parameter
from rclpy.parameter_client import AsyncParameterClient
from rclpy.qos import DurabilityPolicy, QoSProfile
from rclpy.task import Future
from rosidl_runtime_py.convert import message_to_ordereddict
from smart_hub_interfaces.action import EscortPassenger
from smart_hub_interfaces.msg import (
    CrossingState,
    DemandPrediction,
    HubEvent,
    ParkingState,
    QueueState,
    SafetyState,
    VehicleStateArray,
)
from smart_hub_interfaces.srv import (
    ClearSafetyStop,
    ReleaseParking,
    ReserveParking,
    ResetScenario,
)
from smart_hub_sim.geometry import intersects_crossing
from smart_hub_sim.observations import RADIUS
from std_srvs.srv import Trigger
from verification import cleanup_error, stop_processes
from verify_m3 import OperatorHeartbeat

EPISODE_SEC = 300.0
PEDESTRIAN = (80.0, 85.0)
OBSTRUCTION = (90.0, 120.0)
CAR_PATHS = {'P2': ['E', 'U', 'P3', 'P2'], 'P3': ['E', 'U', 'P3']}
# P2 is reachable only through P3, so the P2 car enters first and the P3 car follows
# CAR_GAP_SEC later (1.4 m at 0.35 m/s, above 0.8 m headway plus two 0.3 m footprints).
CAR_ORDER = ('P2', 'P3')
CAR_GAP_SEC = 4.0
DEPART_SEC = {'P3': 200.0, 'P2': 215.0}   # P3 leaves first so the P2 car never meets it


def arrivals(seed):
    """Return the seeded A section 15.1 rush-hour arrival schedule (simulation seconds).

    Two people wait at reset. One arrives during warm-up, a rush of four lifts the
    observed queue to seven shortly after 60 s, then a second rush and a tail follow.
    Only the timing is seeded; counts are fixed so episodes stay comparable.
    """
    rng = random.Random(seed)
    times = [rng.uniform(15, 45)]
    times += sorted(rng.uniform(52, 68) for _ in range(4))
    times += sorted(rng.uniform(90, 130) for _ in range(2))
    times += sorted(rng.uniform(140, 170) for _ in range(4))
    times += sorted(rng.uniform(190, 240) for _ in range(2))
    return [round(t, 3) for t in sorted(times)]


def percentile(values, fraction):
    """Nearest-rank percentile; None for no values."""
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, max(0, math.ceil(fraction * len(ordered)) - 1))]


class Probe(Node):
    """Act as operator, passengers' readiness and car drivers; record everything."""

    def __init__(self, directory):
        """Create clients and bounded histories with monotonic receipt times."""
        super().__init__('s8_acceptance_probe')
        self.output = (directory / 'trace.jsonl').open('w')
        self.history, self.samples = {}, {}
        transient = QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL)
        for name, kind, topic, qos in (
            ('truth', VehicleStateArray, '/sim/evaluator/ground_truth', 10),
            ('safety', SafetyState, '/hub/safety', transient),
            ('crossing', CrossingState, '/crossing/state', transient),
            ('parking', ParkingState, '/parking/state', transient),
            ('event', HubEvent, '/hub/events', 100),
            ('demand', DemandPrediction, '/hub/demand', 10),
            ('queue', QueueState, '/hub/queue', 10),
        ):
            self.history[name] = deque(maxlen=200000)
            self.create_subscription(kind, topic, lambda m, k=name: self.record(k, m), qos)
        self.escort = ActionClient(self, EscortPassenger, '/robot/escort')
        self.ready_client = self.create_client(Trigger, '/robot/confirm_ready')
        self.reset_client = self.create_client(ResetScenario, '/scenario/reset')
        self.clear_client = self.create_client(ClearSafetyStop, '/safety/clear_stop')
        self.reserve_client = self.create_client(ReserveParking, '/parking/reserve_slot')
        self.release_client = self.create_client(ReleaseParking, '/parking/release_slot')
        self.runner = AsyncParameterClient(self, 'scenario_runner')
        self.operator_heartbeat = OperatorHeartbeat(directory)
        self.t0 = None
        self.hooks = []
        self.last_truth_trace = 0.0

    def destroy_node(self):
        """Stop the operator process before destroying ROS entities."""
        self.operator_heartbeat.close()
        return super().destroy_node()

    def now(self):
        """Episode time in seconds since the seeded reset (monotonic)."""
        return time.monotonic() - self.t0 if self.t0 is not None else None

    def trace(self, topic, **fields):
        """Append one verifier event with monotonic and episode times."""
        self.output.write(json.dumps({'t': time.monotonic(), 'episode_t': self.now(),
                                      'topic': topic, **fields}) + '\n')

    def record(self, name, message):
        """Keep every sample; trace low-rate topics in full."""
        now = time.monotonic()
        self.samples[name] = message
        self.history[name].append((now, message))
        if name in ('event', 'safety', 'crossing', 'parking', 'demand'):
            self.trace(name, message=message_to_ordereddict(message))
        elif name == 'truth' and now - self.last_truth_trace >= 0.5:
            # 2 Hz evaluator positions so failures can be diagnosed from the trace alone.
            self.last_truth_trace = now
            self.trace('truth', vehicles=[
                [v.vehicle_id, round(v.pose.x, 3), round(v.pose.y, 3), round(v.speed_mps, 3)]
                for v in message.vehicles])

    def wait(self, predicate, seconds):
        """Spin real callbacks until a predicate holds or the deadline passes."""
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if predicate():
                return True
            rclpy.spin_once(self, timeout_sec=0.02)
            for hook in list(self.hooks):
                hook()
        return bool(predicate())

    def until(self, episode_t):
        """Spin until the given episode time."""
        self.wait(lambda: self.now() >= episode_t, max(0.0, episode_t - self.now()) + 1.0)

    def future(self, future, seconds=5.0):
        """Require a bounded response; a timeout is never success."""
        assert self.wait(future.done, seconds), 'client deadline exceeded'
        return future.result()

    def params(self, **values):
        """Set fixture parameters through the real parameter service."""
        response = self.future(self.runner.set_parameters(
            [Parameter(name, value=value) for name, value in values.items()]))
        assert all(r.successful for r in response.results), str(response)
        self.trace('parameter_update', values=values)

    def events(self, since=None, entity=None):
        """HubEvents after a monotonic time, optionally for one entity."""
        return [(t, m) for t, m in self.history['event']
                if (since is None or t >= since) and (entity is None or m.entity_id == entity)]

    def truth_agent(self, ident):
        """Latest evaluator truth record for one identifier."""
        message = self.samples.get('truth')
        return next((v for v in message.vehicles if v.vehicle_id == ident), None) \
            if message else None


def start_graph(directory, seed, policy, schedule):
    """Start every S8 node (S8.yaml) in its own process group; return processes and logs."""
    arrivals_text = '[' + ','.join(f'{t:.3f}' for t in schedule) + ']'
    commands = {
        'scenario_runner': ['smart_hub_sim', 'scenario_runner', '--ros-args',
                            '-p', 'm3_mode:=true', '-p', 'm4_mode:=true',
                            '-p', 'm6_mode:=true', '-p', 'publish_queue:=false',
                            '-p', f'seed:={seed}', '-p', 'initial_passengers:=2',
                            '-p', f'passenger_arrivals_sec:={arrivals_text}'],
        'passenger_detector': ['smart_hub_perception', 'passenger_detector'],
        'demand_predictor': ['smart_hub_prediction', 'demand_predictor'],
        'safety_supervisor': ['smart_hub_safety', 'safety_supervisor'],
        'crossing_arbiter': ['smart_hub_control', 'crossing_arbiter', '--ros-args',
                             '-p', f'dispatch_policy:={policy}'],
        'route_planner': ['smart_hub_control', 'route_planner'],
        'robot_manager': ['smart_hub_control', 'robot_manager'],
        'bus_manager': ['smart_hub_control', 'bus_manager'],
        'parking_manager': ['smart_hub_control', 'parking_manager'],
        'traffic_monitor': ['smart_hub_control', 'traffic_monitor'],
        'dashboard_marker_publisher': ['smart_hub_bringup', 'dashboard_marker_publisher'],
        'metrics_logger': ['smart_hub_bringup', 'metrics_logger', '--ros-args',
                           '-p', 'scenario_id:=S8', '-p', f'seed:={seed}',
                           '-p', f'output_dir:={directory / "metrics"}'],
    }
    processes, logs = {}, []
    for name, command in commands.items():
        log = (directory / (name + '.log')).open('w')
        logs.append(log)
        package, executable, *arguments = command
        installed = Path(get_package_prefix(package)) / 'lib' / package / executable
        processes[name] = subprocess.Popen([str(installed), *arguments], stdout=log,
                                           stderr=subprocess.STDOUT, start_new_session=True)
    return commands, processes, logs


def reset(probe, seed):
    """Release the operator stop, then obtain an acknowledged seeded reset."""
    probe.operator_heartbeat.set_state(False)
    assert probe.wait(lambda: probe.reset_client.service_is_ready() and
                      probe.samples.get('safety') is not None, 30), 'graph did not start'
    # Wait for every input to be fresh: the supervisor reports clear only then.
    assert probe.wait(lambda: probe.samples['safety'].reason == 'clear', 40), \
        f"safety never clear: {probe.samples['safety'].reason}"
    # Fresh processes subscribe at different times; let every reset participant see the
    # supervisor first. A startup reset that is refused is retried (at most three
    # attempts) and every attempt is recorded; the episode clock starts at the success.
    probe.wait(lambda: False, 3.0)
    attempts = []
    for _ in range(3):
        response = probe.future(probe.reset_client.call_async(ResetScenario.Request(
            scenario_id='m2_baseline', seed=seed, preserve_logs=True)), 5)
        attempts.append({'success': response.success, 'reason': response.reason})
        if response.success:
            break
        probe.wait(lambda: False, 2.0)
    probe.trace('reset_attempts', attempts=attempts)
    assert response.success, attempts
    probe.t0 = time.monotonic()
    probe.trace('episode_start', seed=seed, run_id=response.run_id)
    probe.reset_attempts = attempts
    return response.run_id


def run_episode(probe, seed, schedule):
    """Apply the A section 15.1 schedule and return the raw observations."""
    obs = {'actions': [], 'escorts': [], 'reservations': {}, 'cars': {}, 'clears': []}

    def act(name, **fields):
        obs['actions'].append({'t': probe.now(), 'action': name, **fields})
        probe.trace('action', action=name, **fields)

    run_id = reset(probe, seed)
    obs['run_id'] = run_id

    # 65 s: C1 and C2 request parking simultaneously (distinct or explicit rejection).
    probe.until(65.0)
    futures = {vehicle: probe.reserve_client.call_async(ReserveParking.Request(
        request_id=f's8-{seed}-{vehicle}', vehicle_id=vehicle, preferred_slot='',
        ttl_sec=60.0)) for vehicle in ('C1', 'C2')}
    for vehicle, future in futures.items():
        response = probe.future(future, 3)
        obs['reservations'][vehicle] = {
            'success': response.success, 'slot': response.slot_id,
            'reservation_id': response.reservation_id, 'reason': response.reason}
    act('parking_requests', results=obs['reservations'])
    cars = []
    granted = {r['slot']: v for v, r in obs['reservations'].items()
               if r['success'] and r['slot'] in CAR_PATHS}
    for index, slot in enumerate(s for s in CAR_ORDER if s in granted):
        if index:
            probe.wait(lambda: False, CAR_GAP_SEC)
        vehicle = granted[slot]
        cars.append({'id': vehicle, 'nodes': CAR_PATHS[slot], 'speed': 0.35})
        obs['cars'][vehicle] = {'slot': slot, 'spawn_t': probe.now()}
        probe.params(synthetic_cars=json.dumps(cars))
    occupied = ['P1']

    def park_hook():
        # A parked car is seen by the slot sensor; its reservation has done its job and
        # is released, while the sensor keeps the slot OCCUPIED (A section 11).
        for vehicle, car in obs['cars'].items():
            if 'parked_t' in car or 'pending_release' in car:
                continue
            record = probe.truth_agent(vehicle)
            slot = car['slot']
            target = {'P2': (9.5, 6.5), 'P3': (11.0, 6.5)}[slot]
            if record and math.hypot(record.pose.x - target[0], record.pose.y - target[1]) \
                    < 1e-6 and record.speed_mps == 0.0:
                car['parked_t'] = probe.now()
                occupied.append(slot)
                car['pending_release'] = probe.release_client.call_async(
                    ReleaseParking.Request(
                        request_id=f's8-{seed}-arrive-{vehicle}',
                        reservation_id=obs['reservations'][vehicle]['reservation_id'],
                        vehicle_id=vehicle))
                probe.runner.set_parameters([Parameter('occupied_slots',
                                                       value=list(occupied))])
                probe.trace('car_parked', vehicle=vehicle, slot=slot)
    probe.hooks.append(park_hook)

    # 70 s: escort R -> D; 75 s: readiness.
    probe.until(70.0)
    escort = send_escort(probe, obs, f's8-{seed}-escort-1')
    probe.until(75.0)
    confirm_ready(probe, obs)

    # 80-85 s: pedestrian occupies C.
    probe.until(PEDESTRIAN[0])
    probe.params(pedestrian_present=True)
    act('pedestrian_on')
    probe.until(PEDESTRIAN[1])
    probe.params(pedestrian_present=False)
    act('pedestrian_off')

    # Deliberate operator recovery once C has been observed clear (A section 16.3).
    if probe.wait(lambda: probe.samples['crossing'].state != 'UNKNOWN' and
                  not probe.samples['crossing'].pedestrian_present, 4.0):
        probe.wait(lambda: False, 2.2)
        if probe.samples['safety'].stop_latched:
            response = probe.future(probe.clear_client.call_async(ClearSafetyStop.Request(
                operator_id='s8-probe', acknowledgement='pedestrian left C; deliberate')))
            obs['clears'].append({'t': probe.now(), 'success': response.success,
                                  'reason': response.reason, 'mono': time.monotonic()})
            act('clear_stop', success=response.success, reason=response.reason)

    # 90 s: lower-road obstruction.
    probe.until(OBSTRUCTION[0])
    # A new obstruction appears on free road, not on top of a vehicle: insert O only
    # when no ground-truth footprint is within its radius plus clearance, waiting at
    # most until 115 s. (run2 at adc7955 inserted O 0.56 m from a stopped bus, which the
    # collision check then counted, although nothing had moved.)
    def o_clear():
        truth = probe.samples.get('truth')
        return truth is not None and all(
            math.hypot(v.pose.x - 7.0, v.pose.y - 2.0) > 0.35 + RADIUS.get(v.kind, 0.3) + 0.2
            for v in truth.vehicles if v.kind != 'obstacle')
    inserted = probe.wait(o_clear, OBSTRUCTION[1] - 5.0 - probe.now())
    if inserted:
        probe.params(obstruction_active=True)
    obs['obstruction'] = {'inserted': inserted, 't': probe.now(),
                          'deferred_sec': probe.now() - OBSTRUCTION[0]}
    act('obstruction_on' if inserted else 'obstruction_skipped_occupied',
        deferred_sec=obs['obstruction']['deferred_sec'])
    # A new escort only if the first one ended; the latch never restarts it by itself.
    if escort['future'].done():
        probe.wait(lambda: False, 1.0)
        escort = send_escort(probe, obs, f's8-{seed}-escort-2')
    retry_ready_until(probe, obs, escort, OBSTRUCTION[1])

    # 120 s: remove obstruction; no spontaneous restart is checked in evaluation.
    probe.params(obstruction_active=False)
    act('obstruction_off')
    # A rejected escort (for example while a hazard latch was active) is an explicit
    # outcome; the operator asks once more after the road is clear.
    if not escort['accepted']:
        probe.wait(lambda: False, 1.0)
        escort = send_escort(probe, obs, f's8-{seed}-escort-3')
    retry_ready_until(probe, obs, escort, 180.0)

    # 180-300 s: missions finish, cars leave, reservations are released.
    for slot, depart in sorted(DEPART_SEC.items(), key=lambda item: item[1]):
        probe.until(depart)
        vehicle = next((v for v, c in obs['cars'].items() if c['slot'] == slot), None)
        if vehicle is None:
            continue
        car = obs['cars'][vehicle]
        pending = car.pop('pending_release', None)
        if pending is not None and probe.wait(pending.done, 3):
            response = pending.result()
            car['release'] = {'success': response.success, 'reason': response.reason}
        act('depart', vehicle=vehicle, release=car.get('release'))
        cars = [c for c in cars if c['id'] != vehicle]
        if slot in occupied:
            occupied.remove(slot)
        probe.params(synthetic_cars=json.dumps(cars), occupied_slots=list(occupied))
    retry_ready_until(probe, obs, escort, EPISODE_SEC)
    probe.hooks.clear()
    for car in obs['cars'].values():
        car.pop('pending_release', None)
    for item in obs['escorts']:
        if not item['future'].done():
            handle = item['handle']
            probe.future(handle.cancel_goal_async(), 3)
            act('cancel_unfinished_escort', request_id=item['request_id'])
            probe.wait(item['future'].done, 10)
    for item in obs['escorts']:
        result = item['future'].result() if item['future'].done() else None
        item['status'] = result.status if result else None
        item['reason'] = (result.result.reason if result else
                          'REJECTED' if not item['accepted'] else 'NO_TERMINAL_RESULT')
        item['success'] = bool(result and result.status == GoalStatus.STATUS_SUCCEEDED)
        item['end_mono'] = item.get('end_mono') or time.monotonic()
    obs['end_mono'] = time.monotonic()
    return obs


def send_escort(probe, obs, request_id):
    """Send one escort goal and remember its handle and result future."""
    goal = EscortPassenger.Goal(request_id=request_id, passenger_id='P-s8',
                                pickup_node='R', destination_node='D',
                                max_duration_sec=200.0)
    handle = probe.future(probe.escort.send_goal_async(goal), 5)
    item = {'request_id': request_id, 'sent_t': probe.now(), 'sent_mono': time.monotonic(),
            'accepted': handle.accepted, 'handle': handle,
            'future': handle.get_result_async() if handle.accepted else _done()}
    item['future'].add_done_callback(lambda _f, i=item: i.update(end_mono=time.monotonic()))
    obs['escorts'].append(item)
    probe.trace('escort_goal', request_id=request_id, accepted=handle.accepted)
    return item


def _done():
    """Return a completed future for a rejected goal."""
    future = Future()
    future.set_result(None)
    return future


def confirm_ready(probe, obs):
    """Call /robot/confirm_ready once and record the answer."""
    response = probe.future(probe.ready_client.call_async(Trigger.Request()), 3)
    obs.setdefault('ready', []).append({'t': probe.now(), 'success': response.success,
                                        'message': response.message})
    return response.success


def retry_ready_until(probe, obs, escort, episode_t):
    """Confirm readiness whenever the robot newly waits at pickup."""
    seen = len([1 for _, m in probe.events(escort['sent_mono'], 'robot')
                if m.event == 'WAIT_READY'])
    while probe.now() < episode_t and not escort['future'].done():
        count = len([1 for _, m in probe.events(escort['sent_mono'], 'robot')
                     if m.event == 'WAIT_READY'])
        if count > seen:
            seen = count
            probe.wait(lambda: False, 1.0)
            confirm_ready(probe, obs)
        rclpy.spin_once(probe, timeout_sec=0.05)
    probe.until(min(episode_t, EPISODE_SEC))


def evaluate(probe, obs):
    """Compute A section 15.3 safety checks and service metrics from recorded topics."""
    t0, end = probe.t0, obs['end_mono']
    truth = [(t, m) for t, m in probe.history['truth'] if t0 <= t <= end]
    events = [(t, m) for t, m in probe.history['event'] if t0 <= t <= end]

    # Collisions: any two ground-truth footprints overlapping (obstacle included).
    collisions, inside_pairs = [], []
    for t, message in truth:
        vehicles = [v for v in message.vehicles if v.kind in RADIUS]
        for i, a in enumerate(vehicles):
            for b in vehicles[i + 1:]:
                if math.hypot(a.pose.x - b.pose.x, a.pose.y - b.pose.y) < (
                        RADIUS[a.kind] + RADIUS[b.kind]):
                    collisions.append({'t': t - t0, 'pair': [a.vehicle_id, b.vehicle_id]})
        inside = [v.vehicle_id for v in vehicles if v.kind != 'obstacle' and
                  intersects_crossing(v.pose.x, v.pose.y, RADIUS[v.kind])]
        if len(inside) > 1:
            inside_pairs.append({'t': t - t0, 'inside': inside})

    # Crossing ownership: never two owners; never a non-owner inside C while owned.
    crossing = [(t, m) for t, m in probe.history['crossing'] if t0 <= t <= end]
    owner_conflicts, new_grants_during_pedestrian = [], []
    tokens = set()
    for t, m in crossing:
        if m.state == 'OWNED' and m.token and m.token not in tokens:
            tokens.add(m.token)
            if PEDESTRIAN[0] <= t - t0 <= PEDESTRIAN[1] + 2.0 or m.pedestrian_present:
                new_grants_during_pedestrian.append({'t': t - t0, 'owner': m.owner_id})
    index, owner = 0, ''
    for t, message in truth:
        while index < len(crossing) and crossing[index][0] <= t:
            owner = crossing[index][1].owner_id
            index += 1
        if not owner:
            continue
        intruders = [v.vehicle_id for v in message.vehicles
                     if v.kind in ('bus', 'robot', 'car') and v.vehicle_id != owner and
                     intersects_crossing(v.pose.x, v.pose.y, RADIUS[v.kind])]
        if intruders:
            owner_conflicts.append({'t': t - t0, 'owner': owner, 'intruders': intruders})

    # Entry into C while the pedestrian is present (outside a pre-existing occupancy).
    entries_during_pedestrian = []
    before = set()
    for t, message in truth:
        rel = t - t0
        inside = {v.vehicle_id for v in message.vehicles if v.kind in ('bus', 'robot', 'car')
                  and intersects_crossing(v.pose.x, v.pose.y, RADIUS[v.kind])}
        if PEDESTRIAN[0] <= rel <= PEDESTRIAN[1]:
            for ident in inside - before:
                entries_during_pedestrian.append({'t': rel, 'vehicle': ident})
        before = inside

    # Parking: no slot held by two vehicles, no vehicle holding two slots.
    double_allocations = []
    for t, m in probe.history['parking']:
        if not t0 <= t <= end:
            continue
        holders = [(s.slot_id, s.vehicle_id) for s in m.slots
                   if s.state == 'RESERVED' and s.vehicle_id]
        vehicles = [v for _, v in holders]
        if len(vehicles) != len(set(vehicles)):
            double_allocations.append({'t': t - t0, 'holders': holders})
    slots = [r['slot'] for r in obs['reservations'].values() if r['success']]
    if len(slots) != len(set(slots)):
        double_allocations.append({'t': 65.0, 'responses': obs['reservations']})

    # Dispatch: no new request while a previous mission is outstanding.
    duplicate_dispatches, outstanding, dispatches = [], False, []
    for t, m in events:
        if m.entity_id != 'hub_coordinator':
            continue
        if m.event == 'BUS_DISPATCH_REQUESTED':
            dispatches.append({'t': t - t0, 'reason': m.reason})
            if outstanding:
                duplicate_dispatches.append({'t': t - t0, 'reason': m.reason})
            outstanding = True
        elif m.event in ('BUS_DISPATCH_RESULT', 'BUS_DISPATCH_REJECTED', 'BUS_DISPATCH_FAILED'):
            outstanding = False

    # No spontaneous robot restart: after each robot terminal result, zero measured
    # speed until the verifier sends the next goal.
    restarts = []
    goal_times = sorted(e['sent_mono'] for e in obs['escorts'])
    for item in obs['escorts']:
        stop = item['end_mono']
        nxt = next((g for g in goal_times if g > stop), end)
        moving = [t - t0 for t, m in truth if stop + 0.5 <= t < nxt for v in m.vehicles
                  if v.vehicle_id == 'robot' and abs(v.speed_mps) > 1e-6]
        if moving:
            restarts.append({'after_request': item['request_id'], 'first_t': moving[0]})

    # Forecast only valid after warm-up history (A section 9.3 step 1).
    demand = [(t - t0, m) for t, m in probe.history['demand'] if t0 <= t <= end]
    first_valid = next((t for t, m in demand if m.valid), None)

    # Service metrics. Waits come from simulator boarding records; anyone still waiting
    # at the end is right-censored at the episode end.
    boarded = [json.loads(m.reason) for _, m in events if m.event == 'PASSENGER_BOARDED']
    waits = [b['boarding_sec'] - b['entry_sec'] for b in boarded]
    total = 2 + len(obs['schedule'])
    censored = [EPISODE_SEC - t for t in ([0.0, 0.0] + obs['schedule'])[len(boarded):]]
    queue_peak = max((m.count for t, m in probe.history['queue'] if t0 <= t <= end
                      and m.valid), default=None)
    bus_results = [m.reason for _, m in events if m.entity_id == 'hub_coordinator'
                   and m.event == 'BUS_DISPATCH_RESULT']
    travel = {}
    for vehicle, car in obs['cars'].items():
        arrived = next((t - t0 for t, m in truth if t - t0 >= car['spawn_t']
                        for v in m.vehicles if v.vehicle_id == vehicle and v.speed_mps == 0
                        and t - t0 > car['spawn_t'] + 1.0), None)
        travel[vehicle] = None if arrived is None else arrived - car['spawn_t']
    crossing_wait = {'robot': 0.0, 'bus': 0.0}
    for entity, phase in (('robot', 'WAIT_CROSSING'), ('bus', 'WAIT')):
        timeline = [(t, m) for t, m in events if m.entity_id == entity and (
            m.event.isupper() and not m.event.startswith(('CROSSING_', 'ROUTE')))]
        for (t, m), nxt in zip(timeline, timeline[1:] + [(end, None)]):
            if m.event == phase and (entity == 'robot' or 'CROSSING' in m.reason):
                crossing_wait[entity] += nxt[0] - t
    final_parking = {s.slot_id: s.state for s in probe.samples['parking'].slots} \
        if probe.samples.get('parking') else None
    safety = {
        'collisions': len(collisions), 'physical_crossing_overlap': len(inside_pairs),
        'crossing_owner_conflicts': len(owner_conflicts),
        'new_crossing_grants_during_pedestrian': len(new_grants_during_pedestrian),
        'entries_into_c_during_pedestrian': len(entries_during_pedestrian),
        'double_allocations': len(double_allocations),
        'duplicate_dispatches': len(duplicate_dispatches),
        'spontaneous_robot_restarts': len(restarts),
    }
    metrics = {
        'passengers_total': total, 'passengers_boarded': len(boarded),
        'completion_rate': len(boarded) / total,
        'wait_served_p50_sec': percentile(waits, .5),
        'wait_served_p95_sec': percentile(waits, .95),
        'wait_served_mean_sec': statistics.fmean(waits) if waits else None,
        'wait_including_censored_mean_sec': statistics.fmean(waits + censored),
        'right_censored_passengers': len(censored),
        'queue_peak_observed': queue_peak,
        'bus_dispatches': len(dispatches), 'bus_results': bus_results,
        'bus_missions_succeeded': sum('success=True' in r for r in bus_results),
        'robot_missions': len(obs['escorts']),
        'robot_missions_succeeded': sum(e['success'] for e in obs['escorts']),
        'robot_results': [e['reason'] for e in obs['escorts']],
        'car_travel_time_sec': travel,
        'car_travel_mean_sec': statistics.fmean(v for v in travel.values() if v is not None)
        if any(v is not None for v in travel.values()) else None,
        'crossing_wait_sec': crossing_wait,
        'first_valid_forecast_sec': first_valid,
        'final_parking': final_parking,
    }
    details = {'collisions': collisions[:20], 'physical_crossing_overlap': inside_pairs[:20],
               'crossing_owner_conflicts': owner_conflicts[:20],
               'new_crossing_grants_during_pedestrian': new_grants_during_pedestrian,
               'entries_into_c_during_pedestrian': entries_during_pedestrian,
               'double_allocations': double_allocations[:20],
               'duplicate_dispatches': duplicate_dispatches, 'dispatches': dispatches,
               'spontaneous_robot_restarts': restarts}
    checks = []
    if first_valid is None or first_valid < 30.0:
        checks.append(f'forecast validity at {first_valid} s, expected only after warm-up')
    if not any(r['success'] for r in obs['reservations'].values()) and not all(
            r['reason'] for r in obs['reservations'].values()):
        checks.append('parking requests neither reserved nor explicitly rejected')
    if any(e['reason'] == 'NO_TERMINAL_RESULT' for e in obs['escorts']):
        checks.append('escort without terminal result')
    status = 'PASS' if not any(safety.values()) and not checks else 'FAIL'
    return status, safety, metrics, details, checks


def paired_summary(episodes):
    """Paired predictive-minus-reactive effects per seed; bootstrap over seeds."""
    by_seed = {}
    for episode in episodes:
        if episode.get('metrics'):
            by_seed.setdefault(episode['seed'], {})[episode['policy']] = episode['metrics']
    rows = []
    for seed, pair in sorted(by_seed.items()):
        if {'reactive', 'predictive'} <= set(pair):
            rows.append({'seed': seed, **{
                f'delta_{key}': (pair['predictive'][key] - pair['reactive'][key])
                if pair['predictive'][key] is not None and pair['reactive'][key] is not None
                else None
                for key in ('wait_including_censored_mean_sec', 'wait_served_mean_sec',
                            'wait_served_p95_sec', 'completion_rate',
                            'queue_peak_observed')}})
    deltas = [r['delta_wait_including_censored_mean_sec'] for r in rows
              if r['delta_wait_including_censored_mean_sec'] is not None]
    interval = None
    if len(deltas) >= 2:
        rng = random.Random(0)
        means = sorted(statistics.fmean(rng.choice(deltas) for _ in deltas)
                       for _ in range(5000))
        interval = [means[int(.025 * len(means))], means[int(.975 * len(means)) - 1]]
    return {'pairs': rows, 'n_pairs': len(rows),
            'mean_delta_wait_including_censored_sec':
                statistics.fmean(deltas) if deltas else None,
            'bootstrap_95ci_over_seeds': interval,
            'note': 'delta = predictive - reactive on identical seeds; negative favours '
                    'predictive. Resampled over episodes (seeds), not windows.'}


def main():
    """Run every (seed, policy) episode in fresh processes and report honest status."""
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True)
    parser.add_argument('--seeds', type=int, nargs='+', default=list(range(801, 811)))
    parser.add_argument('--policies', nargs='+', default=['reactive', 'predictive'],
                        choices=['reactive', 'predictive'])
    args = parser.parse_args()
    root = Path(args.output).resolve().parent / (Path(args.output).stem + '-raw')
    if root.exists():
        raise SystemExit('Evidence directory already exists; choose a unique run ID')
    root.mkdir(parents=True)
    commit = subprocess.run(['git', 'rev-parse', 'HEAD'], capture_output=True,
                            text=True).stdout.strip()
    dirty = bool(subprocess.run(['git', 'status', '--porcelain'], capture_output=True,
                                text=True).stdout.strip())
    report = {'schema': 'smart-mobility-hub/s8-verification-v1', 'test': 'T15',
              'source': 'A section 15 p21', 'commit': commit, 'worktree_dirty': dirty,
              'seeds': args.seeds, 'policies': args.policies, 'episodes': [],
              'clocks': 'monotonic episode time; wall-backed ROS stamps; no /clock',
              'fixtures': 'scripted kinematic cars (D17), obstacle O on Cs-J, '
                          'pedestrian flag, verifier operator heartbeat and readiness'}
    started = time.monotonic()
    rclpy.init()
    try:
        for seed in args.seeds:
            for policy in args.policies:
                report['episodes'].append(episode(root, seed, policy))
                Path(args.output).write_text(json.dumps(report, indent=2) + '\n')
    except KeyboardInterrupt:
        report['interrupted'] = True
    finally:
        if rclpy.ok():
            rclpy.shutdown()
    statuses = [e['status'] for e in report['episodes']]
    expected = len(args.seeds) * len(args.policies)
    report['status'] = ('PASS' if len(statuses) == expected and
                        all(s == 'PASS' for s in statuses) else
                        'FAIL' if 'FAIL' in statuses else 'BLOCKED')
    report['paired'] = paired_summary(report['episodes'])
    report['elapsed_sec'] = time.monotonic() - started
    Path(args.output).write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'status': report['status'], 'output': args.output}), flush=True)
    raise SystemExit({'PASS': 0, 'FAIL': 1, 'BLOCKED': 2}[report['status']])


def episode(root, seed, policy):
    """Run one seeded episode end to end; never let one failure hide another."""
    directory = root / f'seed{seed}-{policy}'
    directory.mkdir()
    schedule = arrivals(seed)
    record = {'seed': seed, 'policy': policy, 'status': 'BLOCKED', 'schedule': schedule}
    processes, logs, probe = {}, [], None
    began = time.monotonic()
    try:
        probe = Probe(directory)
        commands, processes, logs = start_graph(directory, seed, policy, schedule)
        record['commands'] = commands
        obs = run_episode(probe, seed, schedule)
        obs['schedule'] = schedule
        status, safety, metrics, details, checks = evaluate(probe, obs)
        record.update(status=status, safety=safety, metrics=metrics, details=details,
                      checks=checks, run_id=obs['run_id'], actions=obs['actions'],
                      reservations=obs['reservations'], clears=obs['clears'],
                      ready=obs.get('ready', []),
                      obstruction=obs.get('obstruction'),
                      reset_attempts=getattr(probe, 'reset_attempts', None),
                      escorts=[{k: v for k, v in e.items() if k not in ('handle', 'future')}
                               for e in obs['escorts']])
    except (Exception, KeyboardInterrupt) as error:
        record['status'] = 'BLOCKED' if isinstance(error, KeyboardInterrupt) else 'FAIL'
        record['error'] = repr(error)
        record['traceback'] = traceback.format_exc()
        if isinstance(error, KeyboardInterrupt):
            raise
    finally:
        try:
            if probe is not None:
                probe.destroy_node()
        except Exception as error:
            cleanup_error(record, 'operator', error)
        try:
            stop_processes(processes.values())
        except Exception as error:
            cleanup_error(record, 'nodes', error)
        if probe is not None:
            probe.output.close()
        for log in logs:
            log.close()
        trace = directory / 'trace.jsonl'
        if trace.exists():
            record['trace_sha256'] = hashlib.sha256(trace.read_bytes()).hexdigest()
        record['elapsed_sec'] = time.monotonic() - began
        print(json.dumps({k: record.get(k) for k in ('seed', 'policy', 'status', 'safety',
                                                     'checks', 'error')}), flush=True)
    return record


if __name__ == '__main__':
    main()
