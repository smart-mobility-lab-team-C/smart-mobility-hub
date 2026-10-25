#!/usr/bin/env python3
"""Record M6 robot navigation/escort (T13-T14) and routing (T11-T12) against real nodes."""

import argparse
from collections import deque
import hashlib
import itertools
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
from geometry_msgs.msg import Twist, TwistStamped
import rclpy
from rclpy.action import ActionClient
from rclpy.node import Node
from rclpy.parameter import Parameter
from rclpy.parameter_client import AsyncParameterClient
from rclpy.qos import DurabilityPolicy, QoSProfile
from rosidl_runtime_py.convert import message_to_ordereddict
from smart_hub_control.routing import load_map
from smart_hub_interfaces.action import EscortPassenger, NavigateTo
from smart_hub_interfaces.msg import (
    CrossingState,
    EdgeStateArray,
    HubEvent,
    SafetyState,
    VehicleStateArray,
)
from smart_hub_interfaces.srv import ClearSafetyStop, ComputeRoute, ResetScenario
from smart_hub_sim.geometry import intersects_crossing
from std_srvs.srv import Trigger
from verification import CaseRunner, cleanup_error, overall_status, stop_processes, StopCases
from verify_m3 import OperatorHeartbeat

SPEED_CAP = {'bus': 0.4, 'robot': 0.25, 'car': 0.35}


def percentile(values, fraction):
    """Nearest-rank percentile; callers report the sample count alongside."""
    ordered = sorted(values)
    return ordered[max(0, math.ceil(fraction * len(ordered)) - 1)]


def oracle(config, edges, start, goal, agent, excluded):
    """Independent exhaustive simple-path search using the A section 13.2 cost."""
    # Callers assert an idle CLEAR crossing first, so the A section 13.2 wait term is zero.
    graph = {name: [] for name in config['nodes']}
    for edge in config['edges']:
        state = edges.get(edge['id'])
        if (state is None or not state.valid or state.blocked or edge['id'] in excluded
                or agent not in edge['agents']):
            continue
        (ax, ay), (bx, by) = (config['nodes'][n] for n in edge['nodes'])
        speed = max(min(state.mean_speed_mps, SPEED_CAP[agent]), 0.05)
        cost = math.hypot(bx - ax, by - ay) / speed * (1 + 2 * state.density_ratio)
        a, b = edge['nodes']
        graph[a].append((b, cost))
        graph[b].append((a, cost))
    best = [math.inf, None]

    def walk(node, seen, cost, path):
        if cost >= best[0]:
            return
        if node == goal:
            best[:] = [cost, list(path)]
            return
        for neighbor, edge_cost in graph[node]:
            if neighbor not in seen:
                seen.add(neighbor)
                path.append(neighbor)
                walk(neighbor, seen, cost + edge_cost, path)
                path.pop()
                seen.discard(neighbor)

    walk(start, {start}, 0.0, [start])
    return best


class Probe(Node):
    """Own the operator heartbeat and test clients; retain observation histories."""

    def __init__(self, directory):
        """Create clients, parameter clients and bounded histories."""
        super().__init__('m6_acceptance_probe')
        self.output = (directory / 'trace.jsonl').open('w')
        self.samples, self.history = {}, {}
        transient = QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL)
        for name, kind, topic, qos in (
            ('truth', VehicleStateArray, '/sim/evaluator/ground_truth', 10),
            ('command', Twist, '/robot/cmd_vel', 1),
            ('candidate', TwistStamped, '/robot/cmd_vel_candidate', 1),
            ('safety', SafetyState, '/hub/safety', transient),
            ('crossing', CrossingState, '/crossing/state', transient),
            ('edges', EdgeStateArray, '/traffic/edges', 10),
            ('event', HubEvent, '/hub/events', 100),
        ):
            self.history[name] = deque(maxlen=30000)
            self.create_subscription(kind, topic, lambda msg, k=name: self.record(k, msg), qos)
        self.escort = ActionClient(self, EscortPassenger, '/robot/escort')
        self.navigate = ActionClient(self, NavigateTo, '/robot/navigate_to')
        self.ready_client = self.create_client(Trigger, '/robot/confirm_ready')
        self.reset_client = self.create_client(ResetScenario, '/scenario/reset')
        self.clear_client = self.create_client(ClearSafetyStop, '/safety/clear_stop')
        self.route_client = self.create_client(ComputeRoute, '/route/compute')
        self.parameters = {name: AsyncParameterClient(self, name)
                           for name in ('scenario_runner', 'm3_synthetic_roads')}
        self.feedback = deque(maxlen=30000)
        self.request_counter = itertools.count(1)
        self.operator_heartbeat = OperatorHeartbeat(directory)

    def destroy_node(self):
        """Stop the operator process before destroying ROS entities."""
        self.operator_heartbeat.close()
        return super().destroy_node()

    def trace(self, topic, **fields):
        """Append one verifier event with a monotonic observer time."""
        self.output.write(json.dumps({'t': time.monotonic(), 'topic': topic, **fields}) + '\n')

    def record(self, name, message):
        """Retain acquisition-bearing messages with monotonic receipt times."""
        now = time.monotonic()
        self.samples[name] = message
        self.history[name].append((now, message))
        if name not in ('candidate', 'command'):
            self.trace(name, message=message_to_ordereddict(message))

    def wait(self, predicate, seconds=5.0):
        """Spin real callbacks until a predicate holds or the deadline passes."""
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if predicate():
                return True
            rclpy.spin_once(self, timeout_sec=0.02)
        return bool(predicate())

    def future(self, future, seconds=5.0):
        """Require a bounded response; a timeout is never success."""
        assert self.wait(future.done, seconds), 'client deadline exceeded'
        return future.result()

    def pause(self, seconds):
        """Keep callbacks alive while observing."""
        self.wait(lambda: False, seconds)

    def params(self, node, **values):
        """Set fixture/fault parameters through the real parameter service."""
        response = self.future(self.parameters[node].set_parameters(
            [Parameter(name, value=value) for name, value in values.items()]))
        assert all(r.successful for r in response.results), str(response)
        self.trace('parameter_update', node=node, values=values)

    def vehicle(self, vehicle_id):
        """Evaluator truth for metrics only."""
        message = self.samples.get('truth')
        return next((v for v in message.vehicles if v.vehicle_id == vehicle_id), None) \
            if message else None

    def robot_events(self, since):
        """Robot HubEvents observed after a monotonic time."""
        return [(t, m) for t, m in self.history['event']
                if t >= since and m.entity_id == 'robot']

    def reset(self, seed):
        """Restore inputs, clear a latch deliberately and obtain every reset acknowledgement."""
        self.operator_heartbeat.set_state(False)
        self.params('scenario_runner', publish_robot_odom=True, publish_bus_odom=True,
                    publish_queue=True, pedestrian_present=False)
        self.params('m3_synthetic_roads', blocked_edges=[''], publish_edges=True,
                    freeze_edges=False, bay_clear=True, density_ratio=0.0)
        self.pause(2.2)
        if self.samples.get('safety') and self.samples['safety'].stop_latched:
            response = self.future(self.clear_client.call_async(ClearSafetyStop.Request(
                operator_id='m6-probe', acknowledgement='deliberate recovery')))
            assert response.success, response.reason
            self.pause(0.2)
        response = self.future(self.reset_client.call_async(ResetScenario.Request(
            scenario_id='m2_baseline', seed=seed, preserve_logs=True)), 3)
        assert response.success, response.reason
        self.pause(2.2)
        return response.run_id

    def send(self, kind, duration=240.0, **fields):
        """Send a real action goal; return (handle-or-None, result future, request id)."""
        request_id = fields.pop('request_id', f'm6-{next(self.request_counter):04}')
        if kind == 'escort':
            goal = EscortPassenger.Goal(
                request_id=request_id, passenger_id=fields.get('passenger', 'P-anon'),
                pickup_node=fields.get('pickup', 'R'),
                destination_node=fields.get('destination', 'D'),
                max_duration_sec=float(duration))
            client = self.escort
        else:
            goal = NavigateTo.Goal(request_id=request_id, goal_node=fields.get('goal', 'D'),
                                   max_duration_sec=float(duration))
            client = self.navigate

        def feedback(message):
            self.feedback.append((time.monotonic(), message.feedback))

        handle = self.future(client.send_goal_async(goal, feedback_callback=feedback))
        self.trace('goal', kind=kind, request_id=request_id, accepted=handle.accepted,
                   message=message_to_ordereddict(goal))
        if not handle.accepted:
            return None, None, request_id
        return handle, handle.get_result_async(), request_id

    def wait_phase(self, phase, since, seconds):
        """Wait for a robot phase event after a monotonic time."""
        return self.wait(lambda: any(m.event == phase for _, m in self.robot_events(since)),
                         seconds)

    def confirm(self):
        """Call the readiness Trigger and return its response."""
        return self.future(self.ready_client.call_async(Trigger.Request()))


def crossing_conflicts(probe, since):
    """Count truth samples with robot footprint in C lacking robot ownership, or bus also in C."""
    crossing = list(probe.history['crossing'])
    conflicts = inside = 0
    for t, truth in probe.history['truth']:
        if t < since:
            continue
        agents = {v.vehicle_id: v for v in truth.vehicles}
        robot, bus = agents.get('robot'), agents.get('bus')
        if robot is None or not intersects_crossing(robot.pose.x, robot.pose.y, 0.2):
            continue
        inside += 1
        state = next((m for ct, m in reversed(crossing) if ct <= t), None)
        owned = state is not None and state.owner_id == 'robot' and state.state in (
            'OWNED', 'HOLD')
        bus_inside = bus is not None and intersects_crossing(bus.pose.x, bus.pose.y, 0.3)
        if not owned or bus_inside:
            conflicts += 1
    return conflicts, inside


def minimum_separation(probe, since):
    """Smallest robot-bus centre distance from evaluator truth."""
    distances = []
    for t, truth in probe.history['truth']:
        agents = {v.vehicle_id: v for v in truth.vehicles}
        if t >= since and {'robot', 'bus'} <= set(agents):
            distances.append(math.hypot(agents['robot'].pose.x - agents['bus'].pose.x,
                                        agents['robot'].pose.y - agents['bus'].pose.y))
    return min(distances) if distances else None


def feedback_intervals(probe, since, until):
    """Intervals between received feedback messages within a goal window."""
    times = [t for t, _ in probe.feedback if since <= t <= until]
    return [b - a for a, b in zip(times, times[1:])]


def run_escort(probe, config, measurement, seed):
    """Nominal R to D escort with readiness; returns the per-run measurements."""
    probe.reset(seed)
    started = time.monotonic()
    handle, result, request_id = probe.send('escort')
    assert handle is not None, 'nominal escort rejected'
    assert probe.wait_phase('WAIT_READY', started, 30), 'WAIT_READY not reached'
    ready = probe.confirm()
    assert ready.success, ready.message
    terminal = probe.future(result, 240)
    finished = time.monotonic()
    measurement['result'] = message_to_ordereddict(terminal.result)
    assert terminal.status == GoalStatus.STATUS_SUCCEEDED, str(terminal.result.reason)
    destination = config['nodes']['D']
    errors = []
    hold_end = time.monotonic() + 1.0
    while time.monotonic() < hold_end:
        rclpy.spin_once(probe, timeout_sec=0.02)
        robot = probe.vehicle('robot')
        errors.append(math.hypot(robot.pose.x - destination[0], robot.pose.y - destination[1]))
    robot = probe.vehicle('robot')
    intervals = feedback_intervals(probe, started, finished)
    conflicts, inside = crossing_conflicts(probe, started)
    separation = minimum_separation(probe, started)
    observed = {
        'seed': seed, 'request_id': request_id,
        'duration_sec': finished - started,
        'final_error_max_over_1s_m': max(errors),
        'final_speed_mps': robot.speed_mps,
        'travelled_m': terminal.result.travelled_distance_m,
        'feedback_count': len(intervals) + 1,
        'feedback_interval_p50_sec': statistics.median(intervals),
        'feedback_interval_p95_sec': percentile(intervals, 0.95),
        'feedback_interval_max_sec': max(intervals),
        'crossing_inside_samples': inside, 'crossing_conflicts': conflicts,
        'min_robot_bus_separation_m': separation,
    }
    measurement.update(observed)
    assert max(errors) <= 0.20, f'final error {max(errors):.3f} m'
    assert robot.speed_mps == 0.0, 'robot not stopped after success'
    assert inside > 0, 'escort did not traverse C; crossing check not exercised'
    assert conflicts == 0, f'{conflicts} crossing conflict samples'
    assert separation is not None and separation > 0.5, 'robot/bus footprint contact'
    assert observed['feedback_interval_p50_sec'] <= 0.55, 'feedback below 2 Hz'
    return observed


def verify(probe, config, nominal_runs, only_case):
    """Run every declared case through the fail-fast recorder."""
    names = ([f'nominal_escort_{i + 1:02}' for i in range(nominal_runs)]
             + ['busy_and_duplicate_rejection', 'readiness_timeout', 'cancel_while_moving',
                'unreachable_destination', 'frozen_robot_odometry', 'blocked_edge_detour',
                'no_route_then_restore', 'route_oracle_20_seeds'])
    if only_case:
        names = [only_case]
    measurement = {}
    runner = CaseRunner(names, measurement)
    try:
        _cases(probe, config, nominal_runs, runner.run, measurement)
    except StopCases:
        pass
    except (Exception, KeyboardInterrupt) as error:
        runner.results.append({'name': 'verifier_setup', 'status': 'BLOCKED',
                               'reason': repr(error), 'traceback': traceback.format_exc()})
    return runner.finish()


def _cases(probe, config, nominal_runs, case, measurement):
    """Exercise T13, T14, T12 and T11 cases."""
    assert probe.wait(lambda: probe.escort.server_is_ready() and probe.navigate.server_is_ready()
                      and len(probe.samples) >= 6, 20), 'M6 graph not ready'
    probe.operator_heartbeat.set_state(False)
    settled = {'since': None}

    def steady():
        safety = probe.samples.get('safety')
        good = safety is not None and not safety.stop_latched and safety.reason in (
            'clear', 'candidate_stale', 'crossing_not_owned')
        settled['since'] = (settled['since'] or time.monotonic()) if good else None
        return good and time.monotonic() - settled['since'] >= 3.0
    probe.pause(2.2)
    if probe.samples.get('safety') and probe.samples['safety'].stop_latched:
        cleared = probe.future(probe.clear_client.call_async(ClearSafetyStop.Request(
            operator_id='m6-probe', acknowledgement='deliberate startup recovery')))
        assert cleared.success, cleared.reason
    assert probe.wait(steady, 30), f'graph never settled: {probe.samples.get("safety")}'

    for index in range(nominal_runs):
        case(f'nominal_escort_{index + 1:02}',
             lambda index=index: run_escort(probe, config, measurement, 601 + index))

    def busy():
        probe.reset(631)
        idle = probe.confirm()
        assert not idle.success, 'readiness accepted with no mission'
        handle, result, request_id = probe.send('escort')
        assert handle is not None
        second, _, _ = probe.send('navigate', goal='J')
        duplicate, _, _ = probe.send('escort', request_id=request_id)
        assert second is None, 'second mission accepted while busy'
        assert duplicate is None, 'duplicate request_id accepted'
        probe.future(handle.cancel_goal_async())
        terminal = probe.future(result, 5)
        assert terminal.status == GoalStatus.STATUS_CANCELED, str(terminal.result.reason)
        return {'idle_ready_message': idle.message, 'busy_rejected': True,
                'duplicate_rejected': True, 'cleanup_status': 'CANCELED'}
    case('busy_and_duplicate_rejection', busy)

    def readiness_timeout():
        probe.reset(632)
        start_pose = probe.vehicle('robot').pose
        started = time.monotonic()
        handle, result, _ = probe.send('escort')
        assert handle is not None
        assert probe.wait_phase('WAIT_READY', started, 30)
        waiting = time.monotonic()
        terminal = probe.future(result, 30)
        aborted = time.monotonic()
        moved = max(math.hypot(v.pose.x - start_pose.x, v.pose.y - start_pose.y)
                    for t, m in probe.history['truth'] if t >= started
                    for v in m.vehicles if v.vehicle_id == 'robot')
        measurement.update({'wait_to_abort_sec': aborted - waiting, 'max_displacement_m': moved,
                            'reason': terminal.result.reason})
        assert terminal.status == GoalStatus.STATUS_ABORTED
        assert terminal.result.reason == 'READINESS_TIMEOUT'
        assert 19.5 <= aborted - waiting <= 22.0, 'readiness deadline not ~20 s'
        assert moved <= 0.05, 'robot moved without readiness'
        late = probe.confirm()
        assert not late.success, 'readiness accepted after timeout'
        return dict(measurement)
    case('readiness_timeout', readiness_timeout)

    def cancel_while_moving():
        probe.reset(633)
        started = time.monotonic()
        handle, result, _ = probe.send('escort')
        assert probe.wait_phase('WAIT_READY', started, 30)
        assert probe.confirm().success
        assert probe.wait(lambda: (probe.vehicle('robot').speed_mps or 0) > 0.05, 40), \
            'robot never translated'
        requested = time.monotonic()
        response = probe.future(handle.cancel_goal_async())
        accepted = time.monotonic()
        assert response.goals_canceling, 'cancel denied'
        assert probe.wait(lambda: any(t >= accepted and m.linear.x == 0 and m.angular.z == 0
                                      for t, m in probe.history['command']), 0.5)
        zero = min(t for t, m in probe.history['command']
                   if t >= accepted and m.linear.x == 0 and m.angular.z == 0)
        terminal = probe.future(result, 4)
        assert probe.wait(lambda: probe.vehicle('robot').speed_mps == 0.0, 0.5)
        stopped = time.monotonic()
        observed = {'request_to_accept_sec': accepted - requested,
                    'accept_to_zero_command_sec': zero - accepted,
                    'accept_to_observed_truth_zero_sec': stopped - accepted,
                    'status': terminal.status, 'reason': terminal.result.reason}
        measurement.update(observed)
        assert terminal.status == GoalStatus.STATUS_CANCELED
        assert zero - accepted <= 0.5
        return observed
    case('cancel_while_moving', cancel_while_moving)

    def unreachable():
        probe.reset(634)
        to_parking, _, _ = probe.send('escort', destination='P1')
        unknown, _, _ = probe.send('navigate', goal='X')
        zero_duration, _, _ = probe.send('navigate', goal='D', duration=0.0)
        assert to_parking is None and unknown is None and zero_duration is None
        return {'car_only_destination_rejected': True, 'unknown_node_rejected': True,
                'nonpositive_duration_rejected': True}
    case('unreachable_destination', unreachable)

    def frozen_odometry():
        probe.reset(635)
        started = time.monotonic()
        handle, result, _ = probe.send('escort')
        assert probe.wait_phase('WAIT_READY', started, 30)
        assert probe.confirm().success
        assert probe.wait(lambda: (probe.vehicle('robot').speed_mps or 0) > 0.05, 40)
        probe.params('scenario_runner', publish_robot_odom=False)
        frozen = time.monotonic()
        terminal = probe.future(result, 6)
        ended = time.monotonic()
        assert probe.wait(lambda: probe.vehicle('robot').speed_mps == 0.0, 1.0)
        truth_zero = min(t for t, m in probe.history['truth'] if t >= frozen and any(
            v.vehicle_id == 'robot' and v.speed_mps == 0.0 for v in m.vehicles))
        observed = {'freeze_to_result_sec': ended - frozen,
                    'freeze_to_truth_zero_sec': truth_zero - frozen,
                    'reason': terminal.result.reason, 'status': terminal.status}
        measurement.update(observed)
        assert terminal.status == GoalStatus.STATUS_ABORTED
        assert terminal.result.reason.startswith('STALE_ODOMETRY')
        return observed
    case('frozen_robot_odometry', frozen_odometry)

    def detour():
        probe.reset(636)
        started = time.monotonic()
        handle, result, _ = probe.send('escort')
        assert probe.wait_phase('WAIT_READY', started, 30)
        assert probe.confirm().success
        assert probe.wait(lambda: probe.vehicle('robot').pose.x > 3.5, 40)
        probe.params('m3_synthetic_roads', blocked_edges=['Cs-J'])
        blocked = time.monotonic()
        terminal = probe.future(result, 300)
        routes = [json.loads(m.reason)['nodes'] for t, m in probe.robot_events(started)
                  if m.event == 'ROUTE']
        on_blocked = sum(1 for t, m in probe.history['truth'] if t >= blocked
                         for v in m.vehicles if v.vehicle_id == 'robot'
                         and 5.7 < v.pose.x < 8.8 and abs(v.pose.y - 2.0) < 0.05)
        conflicts, inside = crossing_conflicts(probe, started)
        observed = {'routes': routes, 'samples_on_blocked_edge_after_block': on_blocked,
                    'crossing_conflicts': conflicts, 'status': terminal.status,
                    'reason': terminal.result.reason,
                    'replans': sum(1 for _, m in probe.robot_events(started)
                                   if m.event == 'REPLAN')}
        measurement.update(observed)
        assert terminal.status == GoalStatus.STATUS_SUCCEEDED, terminal.result.reason
        assert any('B' in route for route in routes[1:]), 'no detour via Cn-B'
        assert on_blocked == 0, 'robot used the blocked edge'
        assert conflicts == 0
        return observed
    case('blocked_edge_detour', detour)

    def no_route():
        probe.reset(637)
        probe.params('m3_synthetic_roads', blocked_edges=['Cs-J', 'B-Cn'])
        probe.pause(1.2)
        rejected, _, _ = probe.send('escort')
        car = probe.future(probe.route_client.call_async(ComputeRoute.Request(
            start_node='A', goal_node='E', agent_type='car')))
        assert rejected is None, 'escort accepted with no robot route'
        assert not car.success and car.reason == 'NO_ROUTE' and not car.node_ids
        probe.params('m3_synthetic_roads', blocked_edges=[''])
        probe.pause(1.2)
        started = time.monotonic()
        handle, result, _ = probe.send('escort')
        assert probe.wait_phase('WAIT_READY', started, 30)
        assert probe.confirm().success
        assert probe.wait(lambda: probe.vehicle('robot').pose.x > 3.5, 40)
        probe.params('m3_synthetic_roads', blocked_edges=['Cs-J', 'B-Cn'])
        terminal = probe.future(result, 10)
        assert terminal.status == GoalStatus.STATUS_ABORTED
        assert terminal.result.reason.startswith('NO_ROUTE'), terminal.result.reason
        aborted = time.monotonic()
        probe.params('m3_synthetic_roads', blocked_edges=[''])
        probe.pause(3.0)
        moving_candidates = sum(1 for t, m in probe.history['candidate']
                                if t >= aborted and (m.twist.linear.x or m.twist.angular.z))
        moved = any(v.speed_mps != 0.0 for t, m in probe.history['truth'] if t >= aborted + 0.5
                    for v in m.vehicles if v.vehicle_id == 'robot')
        observed = {'car_reason': car.reason, 'mission_reason': terminal.result.reason,
                    'nonzero_candidates_after_abort': moving_candidates,
                    'moved_after_restore': moved}
        measurement.update(observed)
        assert moving_candidates == 0 and not moved, 'motion resumed without a new goal'
        return observed
    case('no_route_then_restore', no_route)

    def route_oracle():
        probe.operator_heartbeat.set_state(False)
        probe.params('m3_synthetic_roads', blocked_edges=[''], density_ratio=0.0)
        probe.pause(2.2)
        rng = random.Random(6110)
        ids = [e['id'] for e in config['edges']]
        records, latencies = [], []
        for seed in range(20):
            blocked = rng.sample(ids, rng.randint(0, 4))
            density = round(rng.uniform(0.0, 0.9), 3)
            probe.params('m3_synthetic_roads', blocked_edges=blocked or [''],
                         density_ratio=density)
            published = time.monotonic()
            assert probe.wait(lambda: probe.history['edges'] and probe.history['edges'][-1][0]
                              > published + 0.05, 2.0)
            probe.pause(0.1)
            for _ in range(3):
                agent = rng.choice(('bus', 'robot', 'car'))
                usable = sorted({n for e in config['edges'] if agent in e['agents']
                                 for n in e['nodes']})
                start, goal = rng.sample(usable, 2)
                excluded = rng.sample(ids, rng.randint(0, 1))
                crossing = probe.samples.get('crossing')
                assert crossing and crossing.valid and crossing.state == 'CLEAR' \
                    and not crossing.owner_id, 'crossing not idle; wait term not zero'
                edges = {e.edge_id: e for e in probe.history['edges'][-1][1].edges}
                sent = time.monotonic()
                response = probe.future(probe.route_client.call_async(ComputeRoute.Request(
                    start_node=start, goal_node=goal, agent_type=agent,
                    excluded_edges=excluded)))
                latencies.append(time.monotonic() - sent)
                expected_cost, expected_path = oracle(config, edges, start, goal, agent,
                                                      excluded)
                path = list(response.node_ids)
                record = {'seed': seed, 'agent': agent, 'start': start, 'goal': goal,
                          'blocked': blocked, 'excluded': excluded, 'density': density,
                          'success': response.success, 'cost': response.estimated_cost_sec,
                          'oracle_cost': None if expected_path is None else expected_cost,
                          'path': path}
                records.append(record)
                if expected_path is None:
                    assert not response.success and response.reason == 'NO_ROUTE', record
                    continue
                assert response.success, record
                assert abs(response.estimated_cost_sec - expected_cost) <= 1e-6 * max(
                    1.0, expected_cost), record
                permitted = {e['id']: e for e in config['edges']}
                for a, b in zip(path, path[1:]):
                    edge = permitted.get('-'.join(sorted((a, b))))
                    assert edge and agent in edge['agents'] and edge['id'] not in blocked \
                        and edge['id'] not in excluded, record
        measurement['latency_p95_sec'] = percentile(latencies, 0.95)
        assert measurement['latency_p95_sec'] < 0.25
        return {'requests': len(records), 'configurations': 20,
                'routes_found': sum(r['success'] for r in records),
                'latency_p50_sec': statistics.median(latencies),
                'latency_p95_sec': percentile(latencies, 0.95),
                'latency_max_sec': max(latencies), 'records': records}
    case('route_oracle_20_seeds', route_oracle)


def main():
    """Start isolated real nodes, record every case and report honest status."""
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True)
    parser.add_argument('--nominal-runs', type=int, default=10)
    parser.add_argument('--case', help='run exactly one named case (debugging)')
    args = parser.parse_args()
    directory = Path(args.output).resolve().parent / (Path(args.output).stem + '-raw')
    if directory.exists():
        raise SystemExit('Evidence directory already exists; choose a unique run ID')
    directory.mkdir(parents=True)
    commands = {
        'scenario_runner': ['smart_hub_sim', 'scenario_runner', '--ros-args',
                            '-p', 'm3_mode:=true', '-p', 'm6_mode:=true'],
        'safety_supervisor': ['smart_hub_safety', 'safety_supervisor'],
        'crossing_arbiter': ['smart_hub_control', 'crossing_arbiter'],
        'route_planner': ['smart_hub_control', 'route_planner'],
        'bus_manager': ['smart_hub_control', 'bus_manager'],
        'robot_manager': ['smart_hub_control', 'robot_manager'],
        'm3_synthetic_roads': ['smart_hub_control', 'm3_synthetic_roads'],
    }
    report = {'schema': 'smart-mobility-hub/m6-verification-v1', 'status': 'FAIL',
              'nominal_runs': args.nominal_runs, 'only_case': args.case, 'cases': [],
              'commands': commands, 'clocks': 'monotonic latency; wall-backed ROS stamps',
              'obstacle_model': 'logical: blocked edge via synthetic road fixture'}
    processes, logs, probe = {}, [], None
    started = time.monotonic()
    try:
        rclpy.init()
        probe = Probe(directory)
        for name, command in commands.items():
            log = (directory / (name + '.log')).open('w')
            logs.append(log)
            package, executable, *arguments = command
            installed = Path(get_package_prefix(package)) / 'lib' / package / executable
            processes[name] = subprocess.Popen([str(installed), *arguments], stdout=log,
                                               stderr=subprocess.STDOUT,
                                               start_new_session=True)
        report['cases'] = verify(probe, load_map(), args.nominal_runs, args.case)
        report['status'] = overall_status(report['cases'])
    except (Exception, KeyboardInterrupt) as error:
        report['status'] = 'BLOCKED'
        report['error'] = repr(error)
        report['traceback'] = traceback.format_exc()
    finally:
        try:
            if probe is not None:
                probe.destroy_node()
        except Exception as error:
            cleanup_error(report, 'operator', error)
        try:
            stop_processes(processes.values())
        except Exception as error:
            cleanup_error(report, 'nodes', error)
        if probe is not None:
            probe.output.close()
        for log in logs:
            log.close()
        if rclpy.ok():
            rclpy.shutdown()
        trace = directory / 'trace.jsonl'
        if trace.exists():
            report['trace_sha256'] = hashlib.sha256(trace.read_bytes()).hexdigest()
        report['elapsed_sec'] = time.monotonic() - started
        Path(args.output).write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'status': report['status'], 'output': args.output}), flush=True)
    raise SystemExit({'PASS': 0, 'FAIL': 1, 'BLOCKED': 2}[report['status']])


if __name__ == '__main__':
    main()
