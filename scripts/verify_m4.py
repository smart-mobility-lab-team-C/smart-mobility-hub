#!/usr/bin/env python3
"""Run real-node M4 ownership, sensing, barrier and traffic acceptance probes."""

import argparse
from collections import deque
import hashlib
import json
import math
import os
from pathlib import Path
import signal
import subprocess
import time
import traceback

import rclpy
from rclpy.node import Node
from rclpy.parameter import Parameter, parameter_value_to_python
from rclpy.parameter_client import AsyncParameterClient
from rclpy.qos import DurabilityPolicy, QoSProfile
from rosidl_runtime_py.convert import message_to_ordereddict
from smart_hub_interfaces.msg import (
    EdgeStateArray, HubEvent, ParkingState, SafetyState, VehicleState, VehicleStateArray,
)
from smart_hub_interfaces.srv import (
    ClearSafetyStop, ReleaseParking, ReserveParking, ResetScenario,
)
from std_msgs.msg import Bool


class Probe(Node):
    """Record transport observations and drive only explicitly labelled test inputs."""

    def __init__(self, directory):
        """Create bounded histories, service clients and a deliberate operator heartbeat."""
        super().__init__('m4_acceptance_probe')
        self.output = (directory / 'trace.jsonl').open('w')
        self.history = {}
        self.estop = True
        transient = QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL)
        self.heartbeat = self.create_publisher(Bool, '/hub/estop', transient)
        self.create_timer(.1, lambda: self.heartbeat.publish(Bool(data=self.estop)))
        for name, cls, topic, qos in (
            ('parking', ParkingState, '/parking/state', transient),
            ('edges', EdgeStateArray, '/traffic/edges', 10),
            ('safety', SafetyState, '/hub/safety', transient),
            ('barrier', Bool, '/parking/barrier_open', 1),
            ('request', Bool, '/parking/barrier_request', 1),
            ('events', HubEvent, '/hub/events', 100),
        ):
            self.history[name] = deque(maxlen=30000)
            self.create_subscription(cls, topic, lambda msg, k=name: self.record(k, msg), qos)
        self.reserve = self.create_client(ReserveParking, '/parking/reserve_slot')
        self.release = self.create_client(ReleaseParking, '/parking/release_slot')
        self.clear = self.create_client(ClearSafetyStop, '/safety/clear_stop')
        self.reset = self.create_client(ResetScenario, '/scenario/reset')
        self.parameters = AsyncParameterClient(self, 'scenario_runner')
        self.vehicles = self.create_publisher(VehicleStateArray, '/hub/vehicles', 10)
        self.records = None
        self.freeze = False
        self.frozen = None
        self.last_feed = None
        self.create_timer(.1, self.feed)

    def record(self, name, msg):
        """Keep raw message fields alongside observer monotonic receipt times."""
        now = time.monotonic()
        self.history[name].append((now, msg))
        self.output.write(json.dumps({'t': now, 'topic': name,
                                      'message': message_to_ordereddict(msg)}) + '\n')

    def latest(self, name):
        """Return the last observed message, if any."""
        return self.history[name][-1][1] if self.history[name] else None

    def wait(self, predicate, timeout=5):
        """Spin callbacks until a monotonic deadline, including all heartbeat timers."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return True
            rclpy.spin_once(self, timeout_sec=.01)
        return bool(predicate())

    def pause(self, duration):
        """Continue recording during intentional observation windows."""
        self.wait(lambda: False, duration)

    def future(self, future, timeout=2):
        """Require explicit bounded service completion."""
        assert self.wait(future.done, timeout), 'service response deadline'
        result = future.result()
        self.output.write(json.dumps({'t': time.monotonic(), 'topic': 'service_response',
                                      'message': message_to_ordereddict(result)}) + '\n')
        return result

    def params(self, **values):
        """Wait for confirmed parameter updates and record their exact values."""
        result = self.future(self.parameters.set_parameters(
            [Parameter(key, value=value) for key, value in values.items()]))
        assert all(item.successful for item in result.results), str(result)
        self.output.write(json.dumps({'t': time.monotonic(), 'parameters': values}) + '\n')

    def slots(self):
        """Return observed slot states indexed by public slot ID."""
        msg = self.latest('parking')
        return {slot.slot_id: slot for slot in msg.slots} if msg else {}

    def edge(self):
        """Select the lower road's measured edge record."""
        msg = self.latest('edges')
        return next((edge for edge in msg.edges if edge.edge_id == 'Cs-J'), None) if msg else None

    def label(self):
        """Read the actual monitor label from transition events."""
        for _, msg in reversed(self.history['events']):
            if msg.event == 'TRAFFIC_STATE' and msg.entity_id == 'Cs-J':
                return json.loads(msg.reason)['label']
        return None

    def feed(self):
        """Publish acquisition-stamped raw test observations, never derived edge state."""
        if self.records is None:
            return
        msg = VehicleStateArray()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.header.frame_id = 'map'
        for record in self.records:
            ident, edge, x, y, speed, kind, *validity = record
            vehicle = VehicleState(vehicle_id=ident, edge_id=edge, speed_mps=float(speed),
                                   kind=kind, valid=validity[0] if validity else True)
            vehicle.pose.x, vehicle.pose.y = float(x), float(y)
            msg.vehicles.append(vehicle)
        if self.freeze:
            if self.frozen is None:
                self.frozen = msg
            msg = self.frozen
        else:
            self.frozen = None
        self.last_feed = msg
        self.vehicles.publish(msg)


def parking_cases(probe, results):
    """Exercise twenty real service pairs, expiry and independent actuator behavior."""
    assert probe.wait(lambda: probe.reserve.service_is_ready() and
                      probe.release.service_is_ready() and probe.clear.service_is_ready()
                      and probe.reset.service_is_ready(), 15)
    assert probe.wait(lambda: len(probe.slots()) == 3 and
                      probe.slots()['P2'].state == 'FREE', 8)
    probe.estop = False
    probe.pause(2.2)
    clear = probe.future(probe.clear.call_async(ClearSafetyStop.Request(
        operator_id='m4-probe', acknowledgement='deliberate recovery for barrier test')))
    assert clear.success, clear.reason
    probe.pause(.3)
    response = probe.future(probe.reset.call_async(ResetScenario.Request(
        scenario_id='m2_baseline', seed=17, preserve_logs=True)), 3)
    assert (response.success and
            response.reason == 'ALL_M4_PARTICIPANTS_ACKNOWLEDGED'), str(response)
    assert probe.wait(lambda: probe.slots().get('P2') and
                      probe.slots()['P2'].state == 'FREE', 4)
    results.append({'name': 'reset_acknowledgments', 'status': 'PASS', 'run_id': response.run_id})
    latencies = []
    for trial in range(20):
        requests = [
            ReserveParking.Request(request_id=f'pair-{trial}-{vehicle}',
                                   vehicle_id=vehicle, preferred_slot='P2', ttl_sec=30.)
            for vehicle in ('C1', 'C2')
        ]
        started = time.monotonic()
        futures = [probe.reserve.call_async(request) for request in requests]
        completed = []
        for future in futures:
            future.add_done_callback(lambda done: completed.append(time.monotonic()))
        responses = [probe.future(future) for future in futures]
        assert all(item.success for item in responses), str(responses)
        assert {item.slot_id for item in responses} == {'P2', 'P3'}
        assert len({item.reservation_id for item in responses}) == 2
        assert probe.wait(lambda: len(completed) == 2, 1)
        latencies.extend(t - started for t in completed)
        retry = probe.future(probe.reserve.call_async(requests[0]))
        assert message_to_ordereddict(retry) == message_to_ordereddict(responses[0])
        conflict = ReserveParking.Request(
            request_id=requests[0].request_id, vehicle_id='other',
            preferred_slot='P2', ttl_sec=30.)
        assert not probe.future(probe.reserve.call_async(conflict)).success
        full = ReserveParking.Request(
            request_id=f'full-{trial}', vehicle_id='C3', ttl_sec=30.)
        assert not probe.future(probe.reserve.call_async(full)).success
        for vehicle, response in zip(('C1', 'C2'), responses):
            wrong = probe.future(probe.release.call_async(ReleaseParking.Request(
                request_id=f'wrong-{trial}-{vehicle}',
                reservation_id='wrong', vehicle_id=vehicle)))
            assert not wrong.success
            released = probe.future(probe.release.call_async(ReleaseParking.Request(
                request_id=f'release-{trial}-{vehicle}', reservation_id=response.reservation_id,
                vehicle_id=vehicle)))
            assert released.success
    p95 = sorted(latencies)[math.ceil(.95 * len(latencies)) - 1]
    assert p95 < .250, f'p95 service latency {p95}'
    results.append({'name': 'T07_service_pairs', 'status': 'PASS', 'pairs': 20,
                    'latencies_sec': latencies, 'p95_sec': p95, 'double_allocations': 0})
    canonical_parking(probe, results)
    reservation = probe.future(probe.reserve.call_async(ReserveParking.Request(
        request_id='expiry', vehicle_id='C1', preferred_slot='P2', ttl_sec=5.)))
    assert reservation.success
    probe.params(entry_vehicle_id='stranger')
    probe.pause(.7)
    assert not probe.latest('barrier').data
    probe.params(entry_vehicle_id='C1')
    assert probe.wait(lambda: probe.latest('barrier') and probe.latest('barrier').data, 2)
    probe.params(passage_occupied=True)
    probe.estop = True
    probe.pause(.7)
    assert probe.latest('barrier').data, 'barrier closed onto occupied passage'
    probe.params(passage_occupied=False)
    assert probe.wait(lambda: not probe.latest('barrier').data, 1)
    probe.params(occupied_slots=['P1', 'P2'], invalid_slots=['P3'])
    probe.pause(5.5)
    slots = probe.slots()
    assert slots['P2'].state == 'OCCUPIED' and not slots['P2'].reservation_id
    assert slots['P3'].state == 'UNKNOWN'
    old = probe.future(probe.release.call_async(ReleaseParking.Request(
        request_id='expired-release', reservation_id=reservation.reservation_id, vehicle_id='C1')))
    assert not old.success
    results.append({'name': 'T08_expiry_and_barrier', 'status': 'PASS',
                    'occupied_after_expiry': True, 'stale_unavailable': True,
                    'wrong_entrance_denied': True, 'occupied_passage_held': True})
    probe.params(occupied_slots=['P1'], invalid_slots=[''], freeze_parking=True)
    start = time.monotonic()
    assert probe.wait(lambda: all(slot.state == 'UNKNOWN' for slot in probe.slots().values()), 1.2)
    results.append({'name': 'parking_frozen_source', 'status': 'PASS',
                    'unknown_sec': time.monotonic() - start})
    probe.params(freeze_parking=False)
    assert probe.wait(lambda: probe.slots()['P2'].state == 'FREE', 2)


def canonical_parking(probe, results):
    """Retain the assignment's t=5/6/8/10/40 parking sequence on wall time."""
    started = time.monotonic()

    def at(second):
        probe.pause(max(0, started + second - time.monotonic()))

    at(5)
    requests = [
        ReserveParking.Request(request_id='canonical-' + vehicle,
                               vehicle_id=vehicle, preferred_slot='P2', ttl_sec=30.)
        for vehicle in ('C1', 'C2')
    ]
    futures = [probe.reserve.call_async(request) for request in requests]
    responses = [probe.future(future) for future in futures]
    assert all(response.success for response in responses)
    assert len({response.slot_id for response in responses}) == 2
    at(6)
    retry = probe.future(probe.reserve.call_async(requests[0]))
    assert message_to_ordereddict(retry) == message_to_ordereddict(responses[0])
    occupied = responses[0].slot_id
    at(8)
    probe.params(occupied_slots=['P1', occupied])
    assert probe.wait(lambda: probe.slots()[occupied].state == 'OCCUPIED', 1)
    at(10)
    probe.params(invalid_slots=['P3'])
    at(40)
    slots = probe.slots()
    assert all(not slots[key].reservation_id for key in ('P2', 'P3'))
    assert slots['P3'].state == 'UNKNOWN'
    if occupied != 'P3':
        assert slots[occupied].state == 'OCCUPIED'
    results.append({'name': 'canonical_S4_timeline', 'status': 'PASS',
                    'sample_count': 2, 'scheduled_request_times_sec': [5, 6],
                    'occupancy_sec': 8, 'sensor_loss_sec': 10, 'expiry_check_sec': 40,
                    'occupied_slot': occupied, 'elapsed_sec': time.monotonic() - started})
    probe.params(occupied_slots=['P1'], invalid_slots=[''])
    assert probe.wait(lambda: all(
        probe.slots()[key].state == 'FREE' for key in ('P2', 'P3')), 2)


def traffic_cases(probe, results):
    """Validate labels, false alarms, frozen source, missing data and recovery."""
    probe.params(publish_vehicles=False)
    probe.pause(.3)
    free = [('flow', 'Cs-J', 6, 2, .35, 'car')]
    trials = []
    classification = []
    observation_start = time.monotonic()

    def classify(expected):
        edge = probe.edge()
        classification.append({'expected': expected, 'observed': probe.label(),
                               'valid': edge.valid, 'speed_mps': edge.mean_speed_mps,
                               'density': edge.density_ratio, 't': time.monotonic()})
        assert classification[-1]['observed'] == expected

    for seed in range(10):
        probe.records = [(f'flow-{seed}', 'Cs-J', 6, 2, .35, 'car')]
        start = time.monotonic()
        assert probe.wait(lambda: probe.edge() and probe.edge().valid and
                          probe.label() == 'NORMAL', 2)
        probe.pause(6.)
        classify('NORMAL')
        labels = [json.loads(msg.reason)['label'] for t, msg in probe.history['events']
                  if t >= start and msg.event == 'TRAFFIC_STATE' and msg.entity_id == 'Cs-J']
        assert all(label == 'NORMAL' for label in labels), labels
        trials.append({'trial_id': seed, 'duration_sec': 6., 'false_congestion': 0})
    canonical_traffic(probe, results)
    probe.records = [(f'slow-{i}', 'Cs-J', 5.5 + .8 * i, 2, .1, 'car') for i in range(4)]
    start = time.monotonic()
    assert probe.wait(lambda: probe.label() == 'CONGESTED', 2)
    congestion_delay = time.monotonic() - start
    classify('CONGESTED')
    probe.records = [('O', 'Cs-J', 7, 2, 0, 'obstacle')]
    start = time.monotonic()
    assert probe.wait(lambda: probe.edge().blocked, .6)
    obstruction_delay = time.monotonic() - start
    assert probe.wait(lambda: probe.label() == 'BLOCKED', .2)
    classify('BLOCKED')
    probe.records = free
    assert probe.wait(lambda: probe.edge().valid and not probe.edge().blocked and
                      probe.label() == 'NORMAL', 2)
    for name, records in (
        ('outside_corridor', [('bad', 'Cs-J', 7, 7, .35, 'car')]),
        ('incorrect_edge', [('bad', 'not-an-edge', 7, 2, .35, 'car')]),
    ):
        probe.records = records
        assert probe.wait(lambda: not probe.edge().valid and probe.label() == 'UNKNOWN', 1.2), name
        classify('UNKNOWN')
        probe.records = free
        assert probe.wait(lambda: probe.edge().valid, 1.2), name + ' recovery'
    probe.records = []
    assert probe.wait(lambda: probe.edge().valid and probe.edge().density_ratio == 0
                      and probe.label() == 'NORMAL', 1.2)
    classify('NORMAL')
    probe.records = [('frozen-source', 'Cs-J', 6, 2, .35, 'car', False),
                     ('healthy-source', 'Cn-N', 3, 4, .35, 'car', True)]
    assert probe.wait(lambda: not probe.edge().valid and any(
        edge.edge_id == 'Cn-N' and edge.valid for edge in probe.latest('edges').edges), 1.2)
    frames = [msg for t, msg in probe.history['edges'] if t >= observation_start]
    per_class = {}
    for label in ('NORMAL', 'CONGESTED', 'BLOCKED', 'UNKNOWN'):
        tp = sum(item['expected'] == label and item['observed'] == label
                 for item in classification)
        predicted = sum(item['observed'] == label for item in classification)
        actual = sum(item['expected'] == label for item in classification)
        per_class[label] = {'precision': tp / predicted if predicted else None,
                            'recall': tp / actual if actual else None}
    results.append({'name': 'T09_traffic_labels', 'status': 'PASS',
                    'classification_scope': (
                        'stable probe checkpoints; transitions reported separately'),
                    'classification_samples': classification, 'per_class': per_class,
                    'edge_sample_count': len(frames),
                    'valid_data_fraction': sum(
                        any(e.edge_id == 'Cs-J' and e.valid for e in msg.edges)
                        for msg in frames) / len(frames),
                    'free_flow_trials': trials, 'congestion_delay_sec': congestion_delay,
                    'obstruction_delay_sec': obstruction_delay,
                    'invalid_samples_rejected': True, 'valid_empty_normal': True,
                    'invalid_individual_source_does_not_poison_healthy_edge': True})
    for mode in ('frozen_source', 'missing_feed'):
        probe.records, probe.freeze = free, False
        probe.frozen = None
        assert probe.wait(lambda: probe.edge().valid, 1.2)
        probe.pause(.3)
        started = time.monotonic()
        if mode == 'frozen_source':
            probe.frozen = probe.last_feed
            probe.freeze = True
        else:
            probe.records = None
        assert probe.wait(lambda: not probe.edge().valid, 1.2), mode
        delay = time.monotonic() - started
        probe.records, probe.freeze = free, False
        probe.frozen = None
        assert probe.wait(lambda: probe.edge().valid and probe.label() == 'NORMAL', 1.2)
        results.append({'name': 'T10_' + mode, 'status': 'PASS', 'unknown_sec': delay})


def canonical_traffic(probe, results):
    """Observe the assignment's t=20/45/60 lower-corridor faults and recovery."""
    started = time.monotonic()

    def at(second):
        probe.pause(max(0, started + second - time.monotonic()))

    probe.records = [('canonical-flow', 'Cs-J', 6, 2, .35, 'car')]
    assert probe.wait(lambda: probe.edge().valid and probe.label() == 'NORMAL', 2)
    at(20)
    slow = [(f'canonical-{i}', 'Cs-J', 5.5 + .8 * i, 2, .1, 'car') for i in range(4)]
    probe.records = slow
    congestion_start = time.monotonic()
    assert probe.wait(lambda: probe.label() == 'CONGESTED', 2)
    congestion_delay = time.monotonic() - congestion_start
    at(45)
    probe.records = [*slow[:3], (*slow[3], False)]
    stale_start = time.monotonic()
    assert probe.wait(lambda: not probe.edge().valid, 1.2)
    stale_delay = time.monotonic() - stale_start
    at(60)
    probe.records = [*probe.records, ('O', 'Cs-J', 7, 2, 0, 'obstacle')]
    blocked_start = time.monotonic()
    assert probe.wait(lambda: probe.edge().blocked, .6)
    blocked_delay = time.monotonic() - blocked_start
    at(62)
    probe.records = [*slow, ('O', 'Cs-J', 7, 2, 0, 'obstacle')]
    assert probe.wait(lambda: probe.edge().valid and probe.edge().blocked, 1.2)
    at(64)
    probe.records = [('recovered-flow', 'Cs-J', 6, 2, .35, 'car')]
    assert probe.wait(lambda: probe.edge().valid and probe.label() == 'NORMAL', 1.2)
    results.append({'name': 'canonical_S5_timeline', 'status': 'PASS', 'sample_count': 4,
                    'scheduled_phase_times_sec': [0, 20, 45, 60, 62, 64],
                    'individual_source_loss': 'aggregator explicitly marks frozen source invalid',
                    'congestion_delay_sec': congestion_delay, 'unknown_delay_sec': stale_delay,
                    'obstruction_delay_sec': blocked_delay,
                    'elapsed_sec': time.monotonic() - started})


def stop_process(process):
    """Terminate a launched process group without leaving ROS participants running."""
    if process.poll() is not None:
        return
    os.killpg(process.pid, signal.SIGINT)
    try:
        process.wait(timeout=8)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=3)


def capture_parameters(probe, directory):
    """Read live values through bounded services while keeping probe callbacks active."""
    for node in ('scenario_runner', 'parking_manager', 'traffic_monitor'):
        deadline = time.monotonic() + 10
        client = AsyncParameterClient(probe, node)
        assert probe.wait(client.services_are_ready, 3), 'parameter services missing: ' + node
        listing = probe.future(client.list_parameters(prefixes=[], depth=0),
                               min(3, max(0, deadline - time.monotonic())))
        names = listing.result.names
        values = probe.future(client.get_parameters(names),
                              min(3, max(0, deadline - time.monotonic()))).values
        assert names and len(names) == len(values), 'incomplete parameter dump: ' + node
        dump = {'/' + node: {'ros__parameters': {
            name: parameter_value_to_python(value) for name, value in zip(names, values)}}}
        (directory / (node + '-parameters.yaml')).write_text(json.dumps(dump, indent=2) + '\n')


def main():
    """Retain logs, bags, parameters, raw trace and failure outcomes for every run."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    directory = Path(args.output).resolve().parent
    if directory.exists():
        raise SystemExit('Choose a fresh evidence directory')
    directory.mkdir(parents=True)
    report = {'schema': 'smart-mobility-hub/m4-verification-v1', 'status': 'FAIL',
              'cases': [], 'seed': 17, 'model': None,
              'configuration': 'map_m1.yaml; m4.launch.py defaults',
              'clocks': 'monotonic latency; wall-backed ROS source timestamps'}
    processes, logs = [], []
    rclpy.init()
    probe = Probe(directory)
    try:
        for name, command in (
            ('launch', ['ros2', 'launch', 'smart_hub_bringup', 'm4.launch.py', 'seed:=17']),
            ('bag', ['ros2', 'bag', 'record', '-o', str(directory / 'bag'),
                     '/hub/vehicles', '/traffic/edges', '/parking/observed', '/parking/state',
                     '/parking/barrier_request', '/parking/barrier_open', '/hub/events']),
        ):
            log = (directory / (name + '.log')).open('w')
            logs.append(log)
            processes.append(subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT,
                                              start_new_session=True))
        probe.pause(.5)
        assert all(process.poll() is None for process in processes), 'launch or recorder exited'
        parking_cases(probe, report['cases'])
        traffic_cases(probe, report['cases'])
        capture_parameters(probe, directory)
        report['status'] = 'PASS'
        report['scenario_acceptance'] = 'T07–T10 eligible; independent review remains open'
    except Exception as error:
        report['error'] = repr(error)
        report['traceback'] = traceback.format_exc()
    finally:
        for process in reversed(processes):
            stop_process(process)
        if report['status'] == 'PASS' and not (directory / 'bag/metadata.yaml').exists():
            report['status'] = 'FAIL'
            report['error'] = 'bag metadata missing after recorder shutdown'
        probe.output.close()
        for log in logs:
            log.close()
        report['trace_sha256'] = hashlib.sha256(
            (directory / 'trace.jsonl').read_bytes()).hexdigest()
        report['revision_evidence'] = (
            '../commit.txt and ../source-sha256.txt from container runner')
        Path(args.output).write_text(json.dumps(report, indent=2) + '\n')
        probe.destroy_node()
        rclpy.shutdown()
    print(json.dumps({'status': report['status'], 'output': args.output}), flush=True)
    return 0 if report['status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
