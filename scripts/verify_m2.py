#!/usr/bin/env python3
"""Exercise M2 safety and reset contracts against real ROS processes."""

from __future__ import annotations

import argparse
from collections import deque
from dataclasses import dataclass
import json
import math
import os
from pathlib import Path
import platform
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from typing import Callable, Optional

from geometry_msgs.msg import Twist, TwistStamped
from nav_msgs.msg import Odometry
import rclpy
from rclpy.node import Node
from rclpy.parameter import parameter_value_to_python
from rclpy.parameter_client import AsyncParameterClient
from rclpy.qos import DurabilityPolicy, QoSProfile
from smart_hub_interfaces.msg import (
    CrossingState,
    QueueState,
    SafetyState,
    VehicleState,
    VehicleStateArray,
)
from smart_hub_interfaces.srv import (
    ClearSafetyStop,
    RequestCrossing,
    ResetScenario,
)
from std_msgs.msg import Bool


STARTUP_TIMEOUT_SEC = 12.0
CASE_TIMEOUT_SEC = 4.0
ZERO = (0.0, 0.0)
PROCESSES = (
    ('scenario_runner', 'smart_hub_sim', 'scenario_runner'),
    ('safety_supervisor', 'smart_hub_safety', 'safety_supervisor'),
    ('crossing_arbiter', 'smart_hub_control', 'crossing_arbiter'),
    ('reset_coordinator', 'smart_hub_bringup', 'reset_coordinator'),
)


def _twist_value(message: Twist) -> tuple[float, float]:
    """Return the planar linear and angular command values."""
    return float(message.linear.x), float(message.angular.z)


def _vehicle_speed(message: VehicleStateArray, vehicle_id: str) -> Optional[float]:
    """Read a vehicle's speed from a message without treating absence as zero."""
    for vehicle in message.vehicles:
        if vehicle.vehicle_id == vehicle_id:
            return float(vehicle.speed_mps)
    return None


class Probe(Node):
    """Publish controlled sensor inputs and retain timestamped observations."""

    def __init__(self) -> None:
        """Create publishers, subscribers, service clients, and probe timers."""
        super().__init__('m2_acceptance_probe')
        transient = QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL)
        self.queue_pub = self.create_publisher(QueueState, '/hub/queue', 10)
        self.estop_pub = self.create_publisher(Bool, '/hub/estop', transient)
        self.robot_candidate_pub = self.create_publisher(
            TwistStamped, '/robot/cmd_vel_candidate', 1
        )
        self.bus_candidate_pub = self.create_publisher(
            TwistStamped, '/bus/cmd_vel_candidate', 1
        )
        self.robot_commands = deque(maxlen=512)
        self.bus_commands = deque(maxlen=512)
        self.safety_states = deque(maxlen=256)
        self.crossing_states = deque(maxlen=256)
        self.odom = deque(maxlen=256)
        self.observed_vehicles = deque(maxlen=256)
        self.ground_truth = deque(maxlen=256)
        self.queue_enabled = True
        self.queue_valid = True
        self.queue_stamp_override = None
        self.estop_value = False
        self.robot_candidate_enabled = False
        self.bus_candidate_enabled = False
        self.robot_candidate = (0.08, 0.0)
        self.bus_candidate = (0.0, 0.0)
        self.last_queue_sent = 0.0

        self.create_subscription(
            Twist, '/robot/cmd_vel', self._record(self.robot_commands), 1
        )
        self.create_subscription(Twist, '/bus/cmd_vel', self._record(self.bus_commands), 1)
        self.create_subscription(
            SafetyState, '/hub/safety', self._record(self.safety_states), transient
        )
        self.create_subscription(
            CrossingState, '/crossing/state', self._record(self.crossing_states), transient
        )
        self.create_subscription(Odometry, '/robot/odom', self._record(self.odom), 10)
        self.create_subscription(
            VehicleStateArray,
            '/hub/vehicles',
            self._record(self.observed_vehicles),
            10,
        )
        self.create_subscription(
            VehicleStateArray,
            '/sim/evaluator/ground_truth',
            self._record(self.ground_truth),
            10,
        )

        self.clear_client = self.create_client(ClearSafetyStop, '/safety/clear_stop')
        self.reset_client = self.create_client(ResetScenario, '/scenario/reset')
        self.crossing_client = self.create_client(RequestCrossing, '/crossing/request')
        self.create_timer(0.2, self._publish_queue)
        self.create_timer(0.1, self._publish_estop)
        self.create_timer(0.05, self._publish_candidates)

    @staticmethod
    def _record(buffer: deque) -> Callable:
        """Build a callback that records a monotonic receipt time and message."""
        def callback(message) -> None:
            """Append one ROS sample with its local receipt timestamp."""
            buffer.append((time.monotonic(), message))
        return callback

    def _publish_queue(self) -> None:
        if not self.queue_enabled:
            return
        message = QueueState()
        message.header.stamp = (self.get_clock().now().to_msg()
                                if self.queue_stamp_override is None
                                else self.queue_stamp_override)
        message.header.frame_id = 'map'
        message.zone_id = 'Q'
        message.count = 0
        message.confidence = 0.99
        message.valid = self.queue_valid
        message.crossing_occupied = False
        self.queue_pub.publish(message)
        self.last_queue_sent = time.monotonic()

    def _publish_estop(self) -> None:
        message = Bool()
        message.data = self.estop_value
        self.estop_pub.publish(message)

    @staticmethod
    def _candidate_message(node: Node, frame: str, command: tuple[float, float]):
        """Build a timestamped candidate command in its agent base frame."""
        message = TwistStamped()
        message.header.stamp = node.get_clock().now().to_msg()
        message.header.frame_id = frame
        message.twist.linear.x = command[0]
        message.twist.angular.z = command[1]
        return message

    def _publish_candidates(self) -> None:
        if self.robot_candidate_enabled:
            self.robot_candidate_pub.publish(
                self._candidate_message(self, 'robot/base_link', self.robot_candidate)
            )
        if self.bus_candidate_enabled:
            self.bus_candidate_pub.publish(
                self._candidate_message(self, 'bus/base_link', self.bus_candidate)
            )

    def set_estop(self, value: bool) -> float:
        """Publish the event immediately and return its monotonic send time."""
        self.estop_value = value
        message = Bool()
        message.data = value
        sent = time.monotonic()
        self.estop_pub.publish(message)
        return sent

    def spin_until(self, predicate: Callable[[], bool], timeout: float) -> bool:
        """Pump ROS callbacks until a predicate succeeds or its deadline expires."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return True
            rclpy.spin_once(self, timeout_sec=min(0.01, deadline - time.monotonic()))
        return predicate()

    def spin_for(self, duration: float) -> None:
        """Pump callbacks for a bounded observation interval."""
        deadline = time.monotonic() + duration
        while time.monotonic() < deadline:
            rclpy.spin_once(self, timeout_sec=min(0.01, deadline - time.monotonic()))

    def call(self, client, request, timeout: float = CASE_TIMEOUT_SEC):
        """Call a service asynchronously and return its result before a deadline."""
        if not client.service_is_ready():
            raise RuntimeError(f'service unavailable: {client.srv_name}')
        future = client.call_async(request)
        if not self.spin_until(future.done, timeout):
            raise TimeoutError(f'service deadline: {client.srv_name}')
        if future.exception() is not None:
            raise RuntimeError(f'service failed: {future.exception()}')
        return future.result()

    def latest(self, buffer: deque):
        """Return the latest message or None when no sample has arrived."""
        return buffer[-1][1] if buffer else None

    def wait_command(self, buffer: deque, predicate, timeout: float):
        """Wait for a final command sample matching a caller predicate."""
        return self.spin_until(
            lambda: bool(buffer and predicate(buffer[-1][1])), timeout
        )

    def wait_sample_after(self, buffer: deque, stamp: float, predicate,
                          timeout: float) -> bool:
        """Wait for a matching callback sample received after a test event."""
        return self.spin_until(
            lambda: any(received >= stamp and predicate(message)
                        for received, message in buffer),
            timeout,
        )


@dataclass
class Case:
    """One machine-readable acceptance result."""

    name: str
    status: str
    detail: str
    elapsed_sec: float
    observations: Optional[dict] = None


class Report:
    """Collect each case without converting missing evidence to PASS."""

    def __init__(self) -> None:
        """Start a report with no assumed passing results."""
        self.cases: list[Case] = []

    def run(self, name: str, operation: Callable[[], dict]) -> Optional[dict]:
        """Record PASS only when the bounded operation returns normally."""
        started = time.monotonic()
        try:
            observations = operation()
            if not isinstance(observations, dict):
                raise RuntimeError('acceptance operation returned no measurement record')
        except Exception as error:
            self.cases.append(Case(
                name, 'FAIL', f'{type(error).__name__}: {error}',
                time.monotonic() - started,
            ))
            return None
        self.cases.append(Case(
            name, 'PASS', 'acceptance satisfied', time.monotonic() - started,
            observations,
        ))
        return observations

    def blocked(self, name: str, why: str) -> None:
        """Record a case that could not run because a prerequisite failed."""
        self.cases.append(Case(name, 'BLOCKED', why, 0.0))

    def as_dict(self) -> dict:
        """Return a JSON-serializable report with explicit overall status."""
        statuses = {case.status for case in self.cases}
        if 'FAIL' in statuses:
            overall = 'FAIL'
        elif 'BLOCKED' in statuses:
            overall = 'BLOCKED'
        else:
            overall = 'PASS'
        return {
            'schema': 'smart-mobility-hub/m2-verification-v1',
            'status': overall,
            'environment': {
                'python': sys.version,
                'platform': platform.platform(),
                'ros_distro': os.environ.get('ROS_DISTRO', 'unknown'),
                'ros_domain_id': os.environ.get('ROS_DOMAIN_ID', '0'),
                'clock': 'monotonic latency; ROS stamps for freshness',
            },
            'cases': [case.__dict__ for case in self.cases],
        }


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _zero_commands(probe: Probe) -> bool:
    return bool(
        probe.robot_commands and probe.bus_commands and
        _twist_value(probe.robot_commands[-1][1]) == ZERO and
        _twist_value(probe.bus_commands[-1][1]) == ZERO
    )


def _service_request(scenario_id: str, seed: int = 73) -> ResetScenario.Request:
    request = ResetScenario.Request()
    request.scenario_id = scenario_id
    request.seed = seed
    request.preserve_logs = True
    return request


def _clear_request() -> ClearSafetyStop.Request:
    request = ClearSafetyStop.Request()
    request.operator_id = 'm2_acceptance_probe'
    request.acknowledgement = 'controlled integration test'
    return request


def _crossing_request(requester: str, operation: str, token: str = ''):
    request = RequestCrossing.Request()
    request.requester_id = requester
    request.operation = operation
    request.token = token
    return request


def _start_processes(log_dir: Path) -> dict[str, subprocess.Popen]:
    processes = {}
    for name, package, executable in PROCESSES:
        log_file = (log_dir / f'{name}.log').open('w', encoding='utf-8')
        process = subprocess.Popen(
            ['ros2', 'run', package, executable],
            stdout=log_file,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        process._m2_log_file = log_file
        processes[name] = process
    return processes


def _stop_process(process: Optional[subprocess.Popen], timeout: float = 1.0) -> None:
    if process is None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    if process.poll() is None:
        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait(timeout=timeout)
    log_file = getattr(process, '_m2_log_file', None)
    if log_file is not None:
        log_file.close()


def _process_logs(log_dir: Path) -> dict:
    logs = {}
    for path in sorted(log_dir.glob('*.log')):
        path.open('r', encoding='utf-8', errors='replace').close()
        logs[path.name] = path.read_text(encoding='utf-8', errors='replace')[-5000:]
    return logs


def _parameter_dumps(probe: Probe) -> dict:
    """Capture live parameters asynchronously while servicing probe heartbeats."""
    dumps = {}
    for node_name in (
        '/scenario_runner',
        '/safety_supervisor',
        '/hub_coordinator',
        '/reset_coordinator',
    ):
        started = time.monotonic()
        deadline = started + 10.0
        try:
            client = AsyncParameterClient(probe, node_name)

            def wait_for(predicate):
                if not probe.spin_until(predicate, min(3.0, max(
                        0.0, deadline - time.monotonic()))):
                    raise TimeoutError('parameter service deadline: ' + node_name)

            wait_for(client.services_are_ready)
            listing = client.list_parameters(prefixes=[], depth=0)
            wait_for(listing.done)
            names = listing.result().result.names
            values = client.get_parameters(names)
            wait_for(values.done)
            values = values.result().values
            if not names or len(names) != len(values):
                raise ValueError('empty or incomplete parameter response: ' + node_name)
            dumps[node_name] = {
                'returncode': 0,
                'stdout': json.dumps({node_name: {'ros__parameters': {
                    name: parameter_value_to_python(value)
                    for name, value in zip(names, values)
                }}}, indent=2) + '\n',
                'stderr': '',
                'transport': 'native asynchronous ROS parameter services',
                'elapsed_sec': time.monotonic() - started,
            }
        except Exception as error:
            dumps[node_name] = {'error': f'{type(error).__name__}: {error}',
                                'elapsed_sec': time.monotonic() - started}
    return dumps


def _run_isolated_crossing(domain_id: int) -> dict:
    """Test crossing exclusivity with an isolated authoritative observation source."""
    command = [sys.executable, str(Path(__file__).resolve()), '--crossing-worker']
    env = os.environ.copy()
    env['ROS_DOMAIN_ID'] = str(domain_id)
    completed = subprocess.run(
        command, env=env, text=True, capture_output=True, timeout=30, check=False
    )
    output = completed.stdout.strip().splitlines()
    if not output:
        raise RuntimeError(
            f'isolated crossing worker produced no result: {completed.stderr[-2000:]}'
        )
    result = json.loads(output[-1])
    if completed.returncode != 0:
        raise AssertionError(json.dumps(result, sort_keys=True))
    result['worker_domain_id'] = domain_id
    result['stderr_tail'] = completed.stderr[-2000:]
    return result


def _run_isolated_physical_crossing(domain_id: int) -> dict:
    """Run a physical-entry test in its own ROS graph and subprocess set."""
    command = [sys.executable, str(Path(__file__).resolve()), '--physical-crossing-worker']
    env = os.environ.copy()
    env['ROS_DOMAIN_ID'] = str(domain_id)
    completed = subprocess.run(
        command, env=env, text=True, capture_output=True, timeout=50, check=False
    )
    output = completed.stdout.strip().splitlines()
    if not output:
        raise RuntimeError(
            f'physical crossing worker produced no result: {completed.stderr[-2000:]}'
        )
    result = json.loads(output[-1])
    if completed.returncode != 0:
        raise AssertionError(json.dumps(result, sort_keys=True))
    result['worker_domain_id'] = domain_id
    result['stderr_tail'] = completed.stderr[-2000:]
    return result


class CrossingProbe(Node):
    """Supply controlled observations in an isolated crossing-arbiter graph."""

    def __init__(self) -> None:
        """Create isolated authoritative crossing observations and clients."""
        super().__init__('isolated_crossing_probe')
        self.queue_pub = self.create_publisher(QueueState, '/hub/queue', 10)
        self.vehicles_pub = self.create_publisher(VehicleStateArray, '/hub/vehicles', 10)
        qos = QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL)
        self.states = deque(maxlen=128)
        self.client = self.create_client(RequestCrossing, '/crossing/request')
        self.reset_client = self.create_client(ResetScenario, '/crossing/reset_state')
        self.robot_inside = False
        self.create_subscription(
            CrossingState, '/crossing/state', Probe._record(self.states), qos
        )
        self.create_timer(0.1, self.publish_inputs)

    def publish_inputs(self) -> None:
        """Publish fresh queue and synchronized vehicle observations."""
        stamp = self.get_clock().now().to_msg()
        queue = QueueState()
        queue.header.stamp = stamp
        queue.header.frame_id = 'map'
        queue.zone_id = 'Q'
        queue.confidence = 0.99
        queue.valid = True
        self.queue_pub.publish(queue)

        snapshot = VehicleStateArray()
        snapshot.header.stamp = stamp
        snapshot.header.frame_id = 'map'
        for vehicle_id, kind, x, y in (
            ('bus', 'bus', 1.0, 2.0),
            ('robot', 'robot', 5.0, 3.0) if self.robot_inside else
            ('robot', 'robot', 3.0, 6.0),
        ):
            vehicle = VehicleState()
            snapshot.vehicles.append(vehicle)
            vehicle.vehicle_id = vehicle_id
            vehicle.kind = kind
            vehicle.pose.x = x
            vehicle.pose.y = y
            vehicle.pose.theta = 0.0
            vehicle.speed_mps = 0.0
            vehicle.valid = True
        self.vehicles_pub.publish(snapshot)

    def spin_until(self, predicate: Callable[[], bool], timeout: float) -> bool:
        """Pump callbacks until a predicate succeeds or its deadline expires."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return True
            rclpy.spin_once(self, timeout_sec=min(0.01, deadline - time.monotonic()))
        return predicate()

    def spin_for(self, duration: float) -> None:
        """Pump callbacks for a bounded observation interval."""
        deadline = time.monotonic() + duration
        while time.monotonic() < deadline:
            rclpy.spin_once(self, timeout_sec=min(0.01, deadline - time.monotonic()))


def _worker_call(node: Node, client, request, timeout: float = 2.0):
    """Call a service in the worker graph under a bounded deadline."""
    if not node.spin_until(client.service_is_ready, timeout):
        raise TimeoutError(f'service unavailable: {client.srv_name}')
    future = client.call_async(request)
    if not node.spin_until(future.done, timeout):
        raise TimeoutError(f'service call timed out: {client.srv_name}')
    if future.exception() is not None:
        raise RuntimeError(str(future.exception()))
    return future.result()


def _crossing_worker() -> int:
    """Run the separate-process crossing policy test and print JSON evidence."""
    logs_dir = Path(tempfile.mkdtemp(prefix='smh-m2-arbiter-logs-'))
    process = None
    probe = None
    result = {'cases': [], 'status': 'FAIL'}
    try:
        log = (logs_dir / 'crossing_arbiter.log').open('w', encoding='utf-8')
        process = subprocess.Popen(
            ['ros2', 'run', 'smart_hub_control', 'crossing_arbiter'],
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        rclpy.init()
        probe = CrossingProbe()

        def expect(name: str, condition: bool, detail: str) -> None:
            """Record one isolated crossing acceptance and stop on failure."""
            result['cases'].append({
                'name': name,
                'status': 'PASS' if condition else 'FAIL',
                'detail': detail,
            })
            if not condition:
                raise AssertionError(f'{name}: {detail}')

        ready = probe.spin_until(
            lambda: process.poll() is None and probe.client.service_is_ready()
            and bool(probe.states),
            STARTUP_TIMEOUT_SEC,
        )
        expect('arbiter_ready', ready, 'crossing service and state topic discovered')
        clear = probe.spin_until(
            lambda: probe.states and probe.states[-1][1].valid
            and probe.states[-1][1].state == 'CLEAR',
            3.0,
        )
        expect('fresh_observation', clear, 'valid empty crossing observed')
        probe.spin_for(2.1)
        acquired = _worker_call(
            probe, probe.client, _crossing_request('bus', 'ACQUIRE')
        )
        expect('acquire_first_owner', acquired.granted and bool(acquired.token), acquired.reason)

        probe.robot_inside = True
        probe.spin_for(0.2)
        released_occupied = _worker_call(
            probe, probe.client,
            _crossing_request('bus', 'RELEASE', acquired.token),
        )
        expect(
            'release_rejected_while_occupied',
            not released_occupied.granted,
            released_occupied.reason,
        )
        reset_occupied = _worker_call(
            probe, probe.reset_client, _service_request('m2_baseline')
        )
        expect('reset_rejected_while_occupied', not reset_occupied.success,
               reset_occupied.reason)
        probe.spin_for(1.1)
        competitor = _worker_call(
            probe, probe.client, _crossing_request('robot', 'ACQUIRE')
        )
        expect(
            'expired_owner_not_reassigned_while_occupied',
            not competitor.granted,
            competitor.reason,
        )

        probe.robot_inside = False
        probe.spin_for(2.2)
        reassigned = _worker_call(
            probe, probe.client, _crossing_request('robot', 'ACQUIRE')
        )
        expect(
            'reassign_after_proven_clear',
            reassigned.granted and bool(reassigned.token),
            reassigned.reason,
        )
        released_clear = _worker_call(
            probe, probe.client,
            _crossing_request('robot', 'RELEASE', reassigned.token),
        )
        expect('release_after_clear', released_clear.granted, released_clear.reason)
        reset_clear = _worker_call(
            probe, probe.reset_client, _service_request('m2_baseline')
        )
        expect('reset_after_proven_clear', reset_clear.success, reset_clear.reason)
        result['status'] = 'PASS'
    except Exception as error:
        result['error'] = f'{type(error).__name__}: {error}'
        if process is not None and process.poll() is not None:
            result['process_exit'] = process.returncode
        try:
            result['arbiter_log_tail'] = (logs_dir / 'crossing_arbiter.log').read_text(
                encoding='utf-8', errors='replace'
            )[-5000:]
        except OSError:
            pass
    finally:
        if probe is not None:
            probe.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
        _stop_process(process)
    print(json.dumps(result, sort_keys=True))
    return 0 if result['status'] == 'PASS' else 1


def _physical_crossing_worker() -> int:
    """Prove motion waits for ownership and expiry cannot free occupied space."""
    processes = {}
    probe = None
    result = {'cases': [], 'status': 'FAIL'}
    logs_dir = Path(tempfile.mkdtemp(prefix='smh-m2-physical-logs-'))
    try:
        rclpy.init()
        probe = Probe()
        processes = _start_processes(logs_dir)

        def expect(name: str, condition: bool, detail: str) -> None:
            """Record one physical crossing acceptance and stop on failure."""
            result['cases'].append({
                'name': name,
                'status': 'PASS' if condition else 'FAIL',
                'detail': detail,
            })
            if not condition:
                raise AssertionError(f'{name}: {detail}')

        ready = probe.spin_until(
            lambda: all(process.poll() is None for process in processes.values())
            and probe.crossing_client.service_is_ready()
            and probe.reset_client.service_is_ready()
            and bool(probe.latest(probe.ground_truth))
            and bool(probe.robot_commands and probe.bus_commands and probe.safety_states),
            STARTUP_TIMEOUT_SEC,
        )
        expect('full_graph_ready', ready, 'simulator, safety, crossing, reset ready')
        probe.spin_for(0.4)
        expect('initial_zero', _zero_commands(probe), 'both final commands zero')

        probe.bus_candidate = (0.4, 0.0)
        probe.bus_candidate_enabled = True
        deadline = time.monotonic() + 12.0
        boundary_sample = None
        while time.monotonic() < deadline:
            rclpy.spin_once(probe, timeout_sec=0.01)
            truth = probe.latest(probe.ground_truth)
            if truth is None:
                continue
            x = next((item.pose.x for item in truth.vehicles
                      if item.vehicle_id == 'bus'), None)
            speed = _vehicle_speed(truth, 'bus')
            if x is not None and speed == 0.0 and x >= 3.6:
                boundary_sample = (x, time.monotonic())
                break
        probe.bus_candidate_enabled = False
        expect(
            'unowned_bus_stops_before_crossing',
            boundary_sample is not None and boundary_sample[0] + 0.3 < 4.5,
            'bus stopped with its full footprint before region C',
        )

        clear = probe.spin_until(
            lambda: (probe.latest(probe.crossing_states) is not None
                     and probe.latest(probe.crossing_states).valid
                     and probe.latest(probe.crossing_states).state == 'CLEAR'),
            2.0,
        )
        expect('upstream_wait_is_clear', clear, 'stopped bus leaves C available')
        acquire_deadline = time.monotonic() + 4.0
        acquired = None
        acquisition_attempts = 0
        while time.monotonic() < acquire_deadline and acquisition_attempts < 20:
            remaining = acquire_deadline - time.monotonic()
            acquired = probe.call(
                probe.crossing_client, _crossing_request('bus', 'ACQUIRE'),
                timeout=min(0.5, remaining),
            )
            acquisition_attempts += 1
            if acquired.granted:
                break
            crossing = probe.latest(probe.crossing_states)
            retryable = (crossing is not None and crossing.valid
                         and crossing.owner_id == ''
                         and crossing.state in ('CLEAR', 'CLEAR_DEBOUNCE'))
            if not retryable:
                break
            probe.spin_for(0.2)
        _assert(acquired is not None, 'crossing acquire was not attempted')
        expect('bus_acquires_before_entry', acquired.granted and bool(acquired.token),
               f'{acquired.reason}; attempts={acquisition_attempts}')

        probe.bus_candidate_enabled = True
        entered = False
        last_renew = time.monotonic()
        deadline = time.monotonic() + 8.0
        inside_sample = None
        while time.monotonic() < deadline:
            now = time.monotonic()
            if now - last_renew >= 0.25:
                renewed = probe.call(
                    probe.crossing_client,
                    _crossing_request('bus', 'RENEW', acquired.token),
                )
                if not renewed.granted:
                    raise AssertionError(f'crossing renewal denied: {renewed.reason}')
                last_renew = time.monotonic()
            rclpy.spin_once(probe, timeout_sec=0.01)
            truth = probe.latest(probe.ground_truth)
            if truth is None:
                continue
            vehicle = next((item for item in truth.vehicles
                            if item.vehicle_id == 'bus'), None)
            if vehicle is None:
                continue
            x, y = vehicle.pose.x, vehicle.pose.y
            entered = x + 0.3 >= 4.5 and x - 0.3 <= 5.5 and (
                y + 0.3 >= 1.25 and y - 0.3 <= 4.75
            )
            if entered:
                inside_sample = (x, y)
                break
        expect('owned_bus_enters_crossing', entered,
               'evaluator pose confirms full bus footprint in C under ownership')
        probe.bus_candidate_enabled = False
        competitor = probe.call(
            probe.crossing_client, _crossing_request('robot', 'ACQUIRE')
        )
        expect('competitor_denied_while_bus_inside', not competitor.granted,
               competitor.reason)

        probe.spin_for(1.15)
        crossing = probe.latest(probe.crossing_states)
        hold = (crossing is not None and crossing.owner_id == 'bus'
                and crossing.state == 'HOLD')
        still_inside = False
        truth = probe.latest(probe.ground_truth)
        if truth is not None:
            vehicle = next((item for item in truth.vehicles
                            if item.vehicle_id == 'bus'), None)
            if vehicle is not None:
                still_inside = vehicle.pose.x + 0.3 >= 4.5 and (
                    vehicle.pose.x - 0.3 <= 5.5
                    and vehicle.pose.y + 0.3 >= 1.25
                    and vehicle.pose.y - 0.3 <= 4.75
                )
        expect('expired_lease_holds_occupied_crossing', hold and still_inside,
               'owner retained in HOLD after lease expiry while footprint occupies C')
        competitor_after_expiry = probe.call(
            probe.crossing_client, _crossing_request('robot', 'ACQUIRE')
        )
        expect('no_transfer_after_lease_expiry', not competitor_after_expiry.granted,
               competitor_after_expiry.reason)
        renewed_owner = probe.call(
            probe.crossing_client,
            _crossing_request('bus', 'RENEW', acquired.token),
        )
        expect('expired_owner_can_restore_heartbeat', renewed_owner.granted,
               renewed_owner.reason)
        restored_owner = probe.spin_until(
            lambda: (probe.latest(probe.crossing_states) is not None
                     and probe.latest(probe.crossing_states).owner_id == 'bus'
                     and probe.latest(probe.crossing_states).state == 'OWNED'),
            0.3,
        )
        expect('renewal_restores_only_same_owner', restored_owner,
               'bus remains owner after matching-token renewal')
        reset_occupied = probe.call(
            probe.reset_client, _service_request('m2_baseline', 117)
        )
        expect('reset_rejected_while_occupied', not reset_occupied.success,
               reset_occupied.reason)
        result['entry_pose'] = list(inside_sample) if inside_sample else None
        result['unowned_stop_x_m'] = boundary_sample[0] if boundary_sample else None
        result['status'] = 'PASS'
    except Exception as error:
        result['error'] = f'{type(error).__name__}: {error}'
        result['process_log_tails'] = _process_logs(logs_dir)
    finally:
        if probe is not None:
            probe.robot_candidate_enabled = False
            probe.bus_candidate_enabled = False
            probe.destroy_node()
        for process in processes.values():
            _stop_process(process)
        if rclpy.ok():
            rclpy.shutdown()
    print(json.dumps(result, sort_keys=True))
    return 0 if result['status'] == 'PASS' else 1


def _repeat_candidates(probe: Probe, repetitions: int = 5) -> dict:
    latencies = []
    movement_evidence = None
    for _ in range(repetitions):
        candidate_started = time.monotonic()
        probe.robot_candidate_enabled = True
        probe.robot_candidate = (0.08, 0.0)
        active = probe.wait_command(
            probe.robot_commands,
            lambda msg: abs(msg.linear.x) > 1e-6,
            1.0,
        )
        _assert(active, 'fresh robot candidate did not reach final command')
        if movement_evidence is None:
            moving = probe.wait_sample_after(
                probe.ground_truth, candidate_started,
                lambda message: (_vehicle_speed(message, 'robot') or 0.0) > 0.0,
                0.5,
            )
            _assert(moving, 'safe candidate did not produce measured robot movement')
            truth = probe.latest(probe.ground_truth)
            robot = next(v for v in truth.vehicles if v.vehicle_id == 'robot')
            bus = next(v for v in truth.vehicles if v.vehicle_id == 'bus')
            separation = ((robot.pose.x - bus.pose.x) ** 2 +
                          (robot.pose.y - bus.pose.y) ** 2) ** 0.5
            _assert(robot.pose.x + 0.2 < 4.5 and robot.pose.y - 0.2 > 4.75,
                    'robot command entered or approached the crossing')
            _assert(separation > 0.7, 'robot movement violated agent clearance')
            movement_evidence = {
                'robot_pose': [robot.pose.x, robot.pose.y],
                'bus_pose': [bus.pose.x, bus.pose.y],
                'center_separation_m': separation,
                'crossing_clearance_proven': True,
            }
        probe.robot_candidate_enabled = False
        stopped_at = time.monotonic()
        saw_zero = probe.wait_sample_after(
            probe.robot_commands,
            stopped_at,
            lambda msg: _twist_value(msg) == ZERO,
            0.65,
        )
        elapsed = time.monotonic() - stopped_at
        _assert(saw_zero and elapsed <= 0.65, 'candidate silence did not stop <=0.65s')
        latencies.append(elapsed)
        probe.spin_for(0.08)
    return {'repetitions': repetitions, 'latencies_sec': latencies,
            'safe_movement': movement_evidence}


def _repeat_estop(probe: Probe, repetitions: int = 5) -> dict:
    latencies = []
    physical_latencies = []
    for _ in range(repetitions):
        candidate_started = time.monotonic()
        probe.robot_candidate_enabled = True
        probe.robot_candidate = (0.08, 0.0)
        active = probe.wait_command(
            probe.robot_commands,
            lambda msg: abs(msg.linear.x) > 1e-6,
            1.0,
        )
        _assert(active, 'robot did not have a live command before E-stop')
        moving = probe.wait_sample_after(
            probe.ground_truth, candidate_started,
            lambda msg: (_vehicle_speed(msg, 'robot') or 0.0) > 0.0, 0.5)
        _assert(moving, 'E-stop injection requires observed simulated motion')
        started = probe.set_estop(True)
        stopped = probe.wait_sample_after(
            probe.robot_commands,
            started,
            lambda msg: _twist_value(msg) == ZERO,
            0.20,
        )
        elapsed = time.monotonic() - started
        _assert(stopped and elapsed <= 0.20, 'E-stop output latency exceeded 0.20s')
        latencies.append(elapsed)
        physical_zero = probe.wait_sample_after(
            probe.ground_truth, started,
            lambda msg: _vehicle_speed(msg, 'robot') == 0.0, 0.5)
        _assert(physical_zero, 'no fresh measured zero velocity after E-stop')
        physical_latencies.append(time.monotonic() - started)
        asserted_clear = probe.call(probe.clear_client, _clear_request())
        _assert(not asserted_clear.success,
                'clear-stop accepted while the E-stop input remained asserted')
        probe.robot_candidate_enabled = False
        false_sent = probe.set_estop(False)
        latch_retained = probe.wait_sample_after(
            probe.safety_states, false_sent, lambda state: state.stop_latched, 0.25
        )
        _assert(latch_retained,
                'false E-stop cleared the protective latch')
        stopped_samples = (
            probe.wait_sample_after(
                probe.odom, false_sent,
                lambda message: abs(message.twist.twist.linear.x) <= 1e-6,
                2.0,
            ),
            probe.wait_sample_after(
                probe.observed_vehicles, false_sent,
                lambda message: _vehicle_speed(message, 'robot') == 0.0,
                2.0,
            ),
            probe.wait_sample_after(
                probe.ground_truth, false_sent,
                lambda message: _vehicle_speed(message, 'robot') == 0.0,
                2.0,
            ),
        )
        _assert(all(stopped_samples),
                'clear-stop precondition lacked fresh stationary odom, observation, '
                'and evaluator data')
        cleared = probe.call(probe.clear_client, _clear_request())
        _assert(cleared.success, f'safe explicit clear rejected: {cleared.reason}')
        clear_sent = time.monotonic()
        new_zero = probe.wait_sample_after(
            probe.robot_commands, clear_sent,
            lambda msg: _twist_value(msg) == ZERO, 0.15,
        )
        _assert(new_zero, 'no fresh zero command observed after clear-stop')
        probe.spin_for(0.1)
        _assert(_zero_commands(probe), 'clear-stop restarted motion without a new goal')
    return {'repetitions': repetitions, 'latencies_sec': latencies,
            'simulated_velocity_stop_sec': physical_latencies}


def _run_main() -> int:
    """Run the full M2 acceptance matrix against launched ROS processes."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--crossing-worker', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--physical-crossing-worker', action='store_true',
                        help=argparse.SUPPRESS)
    parser.add_argument('--output', default='-', help='JSON report path, or - for stdout')
    arguments = parser.parse_args()
    if arguments.crossing_worker:
        return _crossing_worker()
    if arguments.physical_crossing_worker:
        return _physical_crossing_worker()

    report = Report()
    ros2 = shutil.which('ros2')
    if ros2 is None:
        report.blocked('process_startup', 'ros2 executable is unavailable')
        return _emit(report, arguments.output)

    processes = {}
    probe = None
    parameter_dumps = {}
    with tempfile.TemporaryDirectory(prefix='smh-m2-logs-') as temp_dir:
        log_dir = Path(temp_dir)
        try:
            rclpy.init()
            probe = Probe()
            processes = _start_processes(log_dir)

            def ready() -> bool:
                """Check process, service, and final-command discovery."""
                exited = [name for name, proc in processes.items() if proc.poll() is not None]
                return not exited and all((
                    probe.clear_client.service_is_ready(),
                    probe.reset_client.service_is_ready(),
                    probe.crossing_client.service_is_ready(),
                )) and bool(probe.robot_commands and probe.bus_commands)

            startup_ok = probe.spin_until(ready, STARTUP_TIMEOUT_SEC)
            report.run('real_processes_and_services_ready', lambda: {
                'ready': startup_ok,
                'processes': {name: proc.poll() for name, proc in processes.items()},
            } if startup_ok else (_ for _ in ()).throw(
                RuntimeError('required processes or services failed startup')
            ))

            if startup_ok:
                probe.queue_pub.publish(QueueState())
                probe._publish_estop()
                observed = probe.spin_until(
                    lambda: probe.latest(probe.odom) is not None
                    and probe.latest(probe.observed_vehicles) is not None
                    and probe.latest(probe.ground_truth) is not None
                    and probe.latest(probe.crossing_states) is not None,
                    2.0,
                )
                report.run('simulator_observations_ready', lambda: {
                    'ready': observed,
                    'observed_vehicle_ids': [
                        item.vehicle_id for item in probe.latest(probe.observed_vehicles).vehicles
                    ] if observed else [],
                    'truth_vehicle_ids': [
                        item.vehicle_id for item in probe.latest(probe.ground_truth).vehicles
                    ] if observed else [],
                } if observed else (_ for _ in ()).throw(
                    RuntimeError('no odometry/observation/evaluator output')
                ))

                report.run('startup_zero_motion', lambda: _assert_zero_window(probe))
                report.run('crossing_exclusive_acquire_release', lambda: _main_crossing(probe))
                report.run('candidate_expiry_repetitions', lambda: _repeat_candidates(probe))
                report.run('queue_staleness_unknown_and_stop', lambda: _test_queue_freeze(probe))
                report.run('frozen_queue_source_stamp', lambda: _test_frozen_source(probe))
                report.run('invalid_queue_denies_motion', lambda: _test_invalid_queue(probe))
                report.run('nonfinite_candidate_rejected', lambda: _test_nan_candidate(probe))
                report.run('estop_latch_and_recovery_repetitions', lambda: _repeat_estop(probe))
                report.run('clear_stop_rejects_stale_inputs', lambda: _test_stale_clear(probe))
                report.run('scenario_reset_acceptance', lambda: _test_reset(probe))
                report.run('scenario_reset_stale_rejection', lambda: _test_stale_reset(probe))
                report.run('reset_missing_participant', lambda: _test_missing_participant(
                    probe, processes, log_dir
                ))

                parameter_dumps = _parameter_dumps(probe)
                report.run(
                    'scenario_parameter_dump',
                    lambda: _assert_parameter_dumps(parameter_dumps),
                )
                probe.spin_for(0.3)
                domain = int(os.environ.get('ROS_DOMAIN_ID', '0'))
                isolated_domain = (domain + 73) % 233
                report.run('isolated_crossing_occupied_release_and_expiry', lambda:
                           _run_isolated_crossing(isolated_domain))
                physical_domain = (domain + 74) % 233
                report.run('full_graph_physical_crossing_entry_and_expiry', lambda:
                           _run_isolated_physical_crossing(physical_domain))
                report.run('adapter_stops_after_supervisor_loss', lambda:
                           _test_supervisor_loss(probe, processes))
            else:
                for name in (
                    'simulator_observations_ready', 'startup_zero_motion',
                    'crossing_exclusive_acquire_release', 'candidate_expiry_repetitions',
                    'queue_staleness_unknown_and_stop', 'estop_latch_and_recovery_repetitions',
                    'invalid_queue_denies_motion', 'nonfinite_candidate_rejected',
                    'clear_stop_rejects_stale_inputs', 'scenario_reset_acceptance',
                    'scenario_reset_stale_rejection', 'reset_missing_participant',
                    'isolated_crossing_occupied_release_and_expiry',
                    'full_graph_physical_crossing_entry_and_expiry',
                    'scenario_parameter_dump',
                    'adapter_stops_after_supervisor_loss',
                ):
                    report.blocked(name, 'required real processes did not become ready')
        except Exception as error:
            report.blocked('harness_runtime', f'{type(error).__name__}: {error}')
        finally:
            if probe is not None:
                probe.robot_candidate_enabled = False
                probe.bus_candidate_enabled = False
                probe.destroy_node()
            for process in processes.values():
                _stop_process(process)
            if rclpy.ok():
                rclpy.shutdown()
        report_dict = report.as_dict()
        report_dict['process_log_tails'] = _process_logs(log_dir)
        report_dict['parameter_dumps'] = parameter_dumps
        return _emit_dict(report_dict, arguments.output)


def _assert_zero_window(probe: Probe) -> dict:
    probe.spin_for(0.4)
    robot = [_twist_value(message) for _, message in probe.robot_commands]
    bus = [_twist_value(message) for _, message in probe.bus_commands]
    _assert(robot and bus and all(command == ZERO for command in robot + bus),
            'a final command was nonzero before a new goal/candidate')
    return {'sample_count': min(len(robot), len(bus)), 'robot_zero': True, 'bus_zero': True}


def _assert_parameter_dumps(dumps: dict) -> dict:
    """Require the declared M2 participant parameter dumps to be captured."""
    failed = [
        name for name, result in dumps.items()
        if result.get('returncode') != 0 or not result.get('stdout', '').strip()
    ]
    _assert(not failed, f"parameter dump failed for: {', '.join(failed)}")
    return {'nodes': sorted(dumps), 'all_dumps_nonempty': True}


def _main_crossing(probe: Probe) -> dict:
    clear = probe.spin_until(
        lambda: (probe.latest(probe.crossing_states) is not None
                 and probe.latest(probe.crossing_states).valid
                 and probe.latest(probe.crossing_states).state == 'CLEAR'),
        2.0,
    )
    _assert(clear, 'crossing did not become valid and clear')
    probe.spin_for(2.05)
    acquire_deadline = time.monotonic() + 5.0
    first = None
    for _ in range(25):
        remaining = acquire_deadline - time.monotonic()
        if remaining <= 0.0:
            break
        first = probe.call(
            probe.crossing_client, _crossing_request('bus', 'ACQUIRE'),
            timeout=min(1.0, remaining))
        if first.granted or first.reason not in ('CLEAR_DEBOUNCE', 'UNKNOWN'):
            break
        probe.spin_for(min(0.2, max(0.0, acquire_deadline - time.monotonic())))
    _assert(first is not None, 'crossing acquisition deadline expired')
    _assert(first.granted and first.token, f'first acquire denied: {first.reason}')
    second = probe.call(
        probe.crossing_client, _crossing_request('robot', 'ACQUIRE')
    )
    _assert(not second.granted, 'competing requester acquired the owned crossing')
    released = probe.call(
        probe.crossing_client, _crossing_request('bus', 'RELEASE', first.token)
    )
    _assert(released.granted, f'clear crossing release denied: {released.reason}')
    return {'first_token_granted': True, 'competing_grant_denied': True,
            'clear_release_granted': True}


def _test_queue_freeze(probe: Probe, repetitions: int = 5) -> dict:
    latencies = []
    for _ in range(repetitions):
        probe.robot_candidate_enabled = True
        active = probe.wait_command(
            probe.robot_commands, lambda msg: abs(msg.linear.x) > 1e-6, 1.0
        )
        _assert(active, 'could not establish movement before queue freeze')
        probe.queue_enabled = False
        frozen_at = probe.last_queue_sent
        unknown = probe.wait_sample_after(
            probe.crossing_states, frozen_at, lambda message: not message.valid, 1.3
        )
        stopped = probe.wait_sample_after(
            probe.robot_commands, frozen_at,
            lambda msg: _twist_value(msg) == ZERO, 1.3
        )
        elapsed = time.monotonic() - frozen_at
        probe.robot_candidate_enabled = False
        probe.queue_enabled = True
        probe.spin_for(0.3)
        _assert(unknown, 'crossing did not become UNKNOWN after stale queue input')
        _assert(stopped, 'safety output did not stop on stale queue input')
        _assert(elapsed <= 1.2, f'stale input stop exceeded 1.2s ({elapsed:.3f}s)')
        latencies.append(elapsed)
    return {'repetitions': repetitions, 'crossing_unknown': True,
            'command_stopped': True, 'freeze_to_zero_sec': latencies}


def _test_invalid_queue(probe: Probe) -> dict:
    """Require explicit invalid queue state to deny motion and crossing grants."""
    probe.robot_candidate_enabled = True
    probe.robot_candidate = (0.08, 0.0)
    active = probe.wait_command(
        probe.robot_commands, lambda msg: abs(msg.linear.x) > 1e-6, 1.0
    )
    _assert(active, 'could not establish movement before invalid queue sample')
    probe.queue_valid = False
    probe._publish_queue()
    invalid_at = probe.last_queue_sent
    unknown = probe.wait_sample_after(
        probe.crossing_states, invalid_at, lambda message: not message.valid, 0.3
    )
    stopped = probe.wait_sample_after(
        probe.robot_commands, invalid_at,
        lambda message: _twist_value(message) == ZERO, 0.2,
    )
    probe.robot_candidate_enabled = False
    probe.queue_valid = True
    probe._publish_queue()
    probe.spin_for(0.3)
    _assert(unknown, 'crossing grant state remained valid on invalid queue input')
    _assert(stopped, 'invalid queue input did not stop final robot output')
    return {'valid_false_deny_motion': True, 'crossing_unknown': True,
            'zero_command_after_input_sec': time.monotonic() - invalid_at}


def _test_nan_candidate(probe: Probe) -> dict:
    """Require a non-finite candidate to produce a fresh zero final command."""
    probe.robot_candidate_enabled = True
    probe.robot_candidate = (0.08, 0.0)
    active = probe.wait_command(
        probe.robot_commands, lambda msg: abs(msg.linear.x) > 1e-6, 1.0
    )
    _assert(active, 'could not establish a candidate before NaN injection')
    probe.robot_candidate = (math.nan, 0.0)
    injected_at = time.monotonic()
    stopped = probe.wait_sample_after(
        probe.robot_commands, injected_at,
        lambda message: _twist_value(message) == ZERO, 0.2,
    )
    probe.robot_candidate_enabled = False
    probe.robot_candidate = (0.0, 0.0)
    _assert(stopped, 'non-finite candidate did not produce a fresh zero command')
    return {'nan_candidate_rejected': True,
            'zero_command_after_injection_sec': time.monotonic() - injected_at}


def _test_frozen_source(probe: Probe) -> dict:
    """Keep receipt heartbeats live while the acquisition timestamp freezes."""
    latencies = []
    try:
        for _ in range(5):
            probe.robot_candidate_enabled = True
            active_at = time.monotonic()
            _assert(probe.wait_sample_after(
                probe.robot_commands, active_at, lambda msg: msg.linear.x > 0.0, 1.0),
                'no moving output before frozen-source injection')
            probe.queue_stamp_override = probe.get_clock().now().to_msg()
            frozen_at = time.monotonic()
            unknown = probe.wait_sample_after(
                probe.crossing_states, frozen_at, lambda msg: not msg.valid, 1.2)
            stopped = probe.wait_sample_after(
                probe.robot_commands, frozen_at + 0.8,
                lambda msg: _twist_value(msg) == ZERO, 0.2)
            _assert(unknown and stopped, 'frozen source was refreshed by live receipts')
            _assert(probe.last_queue_sent >= frozen_at + 0.8,
                    'queue publication heartbeat stopped during source freeze')
            latencies.append(time.monotonic() - frozen_at)
            probe.queue_stamp_override = None
            probe.robot_candidate_enabled = False
            _assert(probe.spin_until(
                lambda: probe.crossing_states and probe.crossing_states[-1][1].valid, 0.5),
                'fresh acquisition stamps did not restore valid observations')
    finally:
        probe.queue_stamp_override = None
        probe.robot_candidate_enabled = False
    return {'repetitions': 5, 'live_receipts': True,
            'freeze_to_unknown_and_zero_sec': latencies}


def _test_stale_clear(probe: Probe, repetitions: int = 5) -> dict:
    reasons = []
    for _ in range(repetitions):
        probe.set_estop(True)
        probe.spin_for(0.1)
        probe.set_estop(False)
        probe.queue_enabled = False
        probe.spin_for(1.1)
        rejected = probe.call(probe.clear_client, _clear_request())
        probe.queue_enabled = True
        probe.spin_for(0.35)
        clear_sent = time.monotonic()
        accepted = probe.call(probe.clear_client, _clear_request())
        _assert(not rejected.success, 'clear-stop accepted while queue input was stale')
        _assert(accepted.success, f'clear-stop rejected after recovery: {accepted.reason}')
        stayed_zero = probe.wait_sample_after(
            probe.robot_commands, clear_sent,
            lambda message: _twist_value(message) == ZERO, 0.15,
        )
        _assert(stayed_zero, 'clear-stop initiated motion or lacked a fresh zero')
        reasons.append(rejected.reason)
    return {'repetitions': repetitions, 'stale_rejected': True,
            'fresh_stationary_accepted': True, 'stale_reasons': reasons}


def _test_reset(probe: Probe) -> dict:
    unknown = probe.call(probe.reset_client, _service_request('unknown_scenario'))
    _assert(not unknown.success, 'reset accepted an unknown scenario')
    before = probe.spin_until(lambda: probe.latest(probe.ground_truth) is not None, 1.0)
    _assert(before, 'no evaluator state before reset')
    old_robot = _vehicle_speed(probe.latest(probe.ground_truth), 'robot')
    probe.ground_truth.clear()
    response = probe.call(probe.reset_client, _service_request('m2_baseline', 99))
    _assert(response.success, f'safe reset not acknowledged: {response.reason}')
    _assert(bool(response.run_id), 'successful reset returned no run identifier')
    reset_completed = time.monotonic()

    def baseline_restored(message: VehicleStateArray) -> bool:
        """Check both seeded poses, headings, and measured stopped velocities."""
        vehicles = {vehicle.vehicle_id: vehicle for vehicle in message.vehicles}
        if 'robot' not in vehicles or 'bus' not in vehicles:
            return False
        robot = vehicles['robot']
        bus = vehicles['bus']
        return (
            abs(robot.pose.x - 3.0) <= 1e-6
            and abs(robot.pose.y - 6.0) <= 1e-6
            and abs(robot.pose.theta) <= 1e-6
            and abs(bus.pose.x - 1.0) <= 1e-6
            and abs(bus.pose.y - 2.0) <= 1e-6
            and abs(bus.pose.theta) <= 1e-6
            and _vehicle_speed(message, 'robot') == 0.0
            and _vehicle_speed(message, 'bus') == 0.0
        )

    reset_seen = probe.wait_sample_after(
        probe.ground_truth, reset_completed, baseline_restored, 1.0
    )
    _assert(reset_seen, 'post-ack evaluator sample did not confirm the seeded world restored')
    return {'unknown_scenario_rejected': True, 'run_id': response.run_id,
            'seed': 99, 'pre_reset_robot_speed_mps': old_robot,
            'post_reset_world_restored': True,
            'robot_pose': [3.0, 6.0, 0.0], 'bus_pose': [1.0, 2.0, 0.0]}


def _test_stale_reset(probe: Probe) -> dict:
    probe.set_estop(False)
    probe.queue_enabled = False
    probe.spin_for(1.1)
    response = probe.call(probe.reset_client, _service_request('m2_baseline', 100))
    probe.queue_enabled = True
    probe.spin_for(0.3)
    _assert(not response.success, 'scenario reset accepted stale critical input')
    return {'stale_reset_rejected': True, 'reason': response.reason}


def _test_missing_participant(probe: Probe, processes: dict, log_dir: Path) -> dict:
    sim = processes.get('scenario_runner')
    _assert(sim is not None and sim.poll() is None, 'scenario process already exited')
    _stop_process(sim)
    probe.ground_truth.clear()
    started = time.monotonic()
    response = probe.call(
        probe.reset_client, _service_request('m2_baseline', 101), timeout=1.25
    )
    elapsed = time.monotonic() - started
    _assert(not response.success, 'reset succeeded without a simulator participant')
    _assert(elapsed <= 1.25, f'missing participant response exceeded deadline: {elapsed}')
    new_log = (log_dir / 'scenario_runner_restart.log').open('w', encoding='utf-8')
    replacement = subprocess.Popen(
        ['ros2', 'run', 'smart_hub_sim', 'scenario_runner'],
        stdout=new_log,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    replacement._m2_log_file = new_log
    processes['scenario_runner'] = replacement
    restarted_at = time.monotonic()
    restored = probe.spin_until(
        lambda: replacement.poll() is None and probe.ground_truth
        and probe.ground_truth[-1][0] >= restarted_at,
        STARTUP_TIMEOUT_SEC,
    )
    _assert(restored, 'simulator did not restart after missing-participant test')
    ready_for_reset = probe.spin_until(
        lambda: probe.crossing_states and probe.safety_states
        and probe.crossing_states[-1][0] >= restarted_at
        and probe.safety_states[-1][0] >= restarted_at
        and probe.crossing_states[-1][1].valid
        and probe.crossing_states[-1][1].state == 'CLEAR'
        and probe.safety_states[-1][1].reason in ('clear', 'reset_in_progress'),
        3.0,
    )
    _assert(ready_for_reset, 'restored observations did not reach all safety participants')
    probe.ground_truth.clear()
    reset_started = time.monotonic()
    recovery_deadline = time.monotonic() + 4.0
    recovery = None
    for _ in range(10):
        remaining = recovery_deadline - time.monotonic()
        if remaining <= 0.0:
            break
        recovery = probe.call(
            probe.reset_client, _service_request('m2_baseline', 102),
            timeout=min(1.1, remaining))
        if recovery.success or recovery.reason != 'PARTICIPANT_UNAVAILABLE':
            break
        probe.spin_for(min(0.3, max(0.0, recovery_deadline - time.monotonic())))
    _assert(recovery is not None, 'service discovery recovery deadline expired')
    _assert(recovery.success,
            f'safe reset recovery after missing participant failed: {recovery.reason}')
    converged = probe.wait_sample_after(
        probe.ground_truth, reset_started,
        lambda message: (_vehicle_speed(message, 'robot') == 0.0
                         and _vehicle_speed(message, 'bus') == 0.0),
        3.0,
    )
    _assert(converged, 'post-recovery reset did not converge to stopped evaluator state')
    return {'rejected': True, 'response_sec': elapsed, 'simulator_restarted': True,
            'recovery_run_id': recovery.run_id, 'safe_reset_recovered': True}


def _test_supervisor_loss(probe: Probe, processes: dict) -> dict:
    latencies = []
    for repetition in range(5):
        probe.robot_candidate = (0.1, 0.0)
        probe.robot_candidate_enabled = True
        candidate_started = time.monotonic()
        moving = probe.wait_sample_after(
            probe.ground_truth, candidate_started,
            lambda message: (_vehicle_speed(message, 'robot') or 0.0) > 0.0,
            2.0,
        )
        state = probe.latest(probe.safety_states)
        command = probe.latest(probe.robot_commands)
        detail = {'trial': repetition + 1,
                  'reason': state.reason if state else 'NO_SAFETY',
                  'latched': state.stop_latched if state else None,
                  'command': _twist_value(command) if command else None}
        _assert(moving, f'no measured motion before termination: {detail}')
        supervisor = processes.get('safety_supervisor')
        _assert(supervisor is not None and supervisor.poll() is None,
                'safety supervisor process is unavailable')
        terminated_at = time.monotonic()
        _stop_process(supervisor)
        probe.robot_candidate_enabled = False
        stopped = probe.wait_sample_after(
            probe.ground_truth, terminated_at,
            lambda message: _vehicle_speed(message, 'robot') == 0.0,
            0.65,
        )
        elapsed = time.monotonic() - terminated_at
        _assert(stopped and elapsed <= 0.65,
                f'adapter stop exceeded 0.65s ({elapsed:.3f}s)')
        latencies.append(elapsed)
        if repetition == 4:
            continue
        log_file = (Path(processes['scenario_runner']._m2_log_file.name).parent /
                    f'safety_supervisor_restart_{repetition + 1}.log').open(
                        'w', encoding='utf-8'
                    )
        replacement = subprocess.Popen(
            ['ros2', 'run', 'smart_hub_safety', 'safety_supervisor'],
            stdout=log_file,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        replacement._m2_log_file = log_file
        processes['safety_supervisor'] = replacement
        probe.safety_states.clear()
        restarted_at = time.monotonic()
        restored = probe.spin_until(
            lambda: replacement.poll() is None
            and probe.safety_states
            and probe.safety_states[-1][0] >= restarted_at
            and probe.safety_states[-1][1].reason == 'clear'
            and not probe.safety_states[-1][1].stop_latched,
            STARTUP_TIMEOUT_SEC,
        )
        _assert(restored, 'safety supervisor failed to restart for another repetition')
    return {'repetitions': len(latencies), 'supervisor_terminated_while_moving': True,
            'measured_stop_sec': latencies, 'evaluator_ground_truth_used': True}


def _emit_dict(data: dict, output: str) -> int:
    serialized = json.dumps(data, indent=2, sort_keys=True)
    if output == '-':
        print(serialized)
    else:
        Path(output).write_text(serialized + '\n', encoding='utf-8')
    return 0 if data.get('status') == 'PASS' else 1


def _emit(report: Report, output: str) -> int:
    """Serialize a collected report to stdout or the requested path."""
    return _emit_dict(report.as_dict(), output)


if __name__ == '__main__':
    if '--crossing-worker' in sys.argv:
        raise SystemExit(_crossing_worker())
    if '--physical-crossing-worker' in sys.argv:
        raise SystemExit(_physical_crossing_worker())
    raise SystemExit(_run_main())
