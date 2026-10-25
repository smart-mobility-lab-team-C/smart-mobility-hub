#!/usr/bin/env python3
"""Record M3 acceptance against real ROS nodes with explicit synthetic fixtures."""

import argparse
from collections import deque
import hashlib
import json
import math
import os
from pathlib import Path
import select
import signal
import subprocess
import sys
import time
import traceback

from action_msgs.msg import GoalStatus
from ament_index_python.packages import get_package_prefix
from door_duration import assess_receipts, assess_source
from geometry_msgs.msg import Twist
from nav_msgs.msg import Odometry
import rclpy
from rclpy.action import ActionClient
from rclpy.node import Node
from rclpy.parameter import Parameter
from rclpy.parameter_client import AsyncParameterClient
from rclpy.qos import DurabilityPolicy, QoSProfile
from rosidl_runtime_py.convert import message_to_ordereddict
from smart_hub_interfaces.action import DockBus
from smart_hub_interfaces.msg import (
    BusArrival,
    CrossingState,
    HubEvent,
    QueueState,
    SafetyState,
    VehicleStateArray,
)
from smart_hub_interfaces.srv import ClearSafetyStop, ComputeRoute, RequestCrossing, ResetScenario
from std_msgs.msg import Bool
from std_srvs.srv import Trigger
from verification import (
    Blocked, CaseRunner, cleanup_error, overall_status, stop_processes, StopCases,
)


class OperatorHeartbeat:
    """Control the dedicated process that owns `/hub/estop`."""

    def __init__(self, directory):
        """Start asserted and wait until the child has published that state."""
        self.sequence = 0
        self.log = (directory / 'operator-process.log').open('w')
        command = [
            sys.executable,
            str(Path(__file__).with_name('m3_operator_heartbeat.py')),
            '--parent-pid', str(os.getpid()),
            '--output', str(directory / 'operator-heartbeat.jsonl'),
        ]
        self.process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=self.log,
            text=True,
            bufsize=1,
            start_new_session=True,
        )
        try:
            ready = self._read_response(5.0)
            if ready.get('event') != 'ready' or ready.get('published') is not True:
                raise RuntimeError(f'operator publisher failed startup: {ready}')
        except Exception:
            self._stop_child()
            raise

    def _read_response(self, timeout):
        """Wait briefly for a response without blocking on a dead publisher."""
        ready, _, _ = select.select([self.process.stdout], [], [], timeout)
        if not ready:
            raise TimeoutError('operator publisher acknowledgement timed out')
        line = self.process.stdout.readline()
        if not line:
            raise RuntimeError(f'operator publisher exited: {self.process.poll()}')
        return json.loads(line)

    def _request(self, operation, value=None):
        """Send a command and require its publication acknowledgement."""
        if self.process.poll() is not None:
            raise RuntimeError(f'operator publisher exited: {self.process.returncode}')
        self.sequence += 1
        request = {'id': self.sequence, 'operation': operation}
        if operation == 'set':
            request['value'] = bool(value)
        self.process.stdin.write(json.dumps(request) + '\n')
        self.process.stdin.flush()
        response = self._read_response(2.0)
        if response.get('id') != self.sequence or not response.get('ok'):
            raise RuntimeError(f'operator publisher rejected command: {response}')
        if operation == 'set' and response.get('published') is not bool(value):
            raise RuntimeError(f'operator publisher state mismatch: {response}')
        return response.get('published')

    def set_state(self, value):
        """Set the operator state through the child process."""
        return self._request('set', value)

    def close(self):
        """Assert stop, stop the child, and reap it within a fixed bound."""
        try:
            if self.process.poll() is None:
                self._request('shutdown')
            self.process.wait(timeout=2.0)
        except (OSError, RuntimeError, TimeoutError, subprocess.TimeoutExpired):
            self._stop_child()
        finally:
            if self.process.stdin and not self.process.stdin.closed:
                self.process.stdin.close()
            if self.process.stdout and not self.process.stdout.closed:
                self.process.stdout.close()
            self.log.close()

    def _stop_child(self):
        """Terminate and reap a child that did not complete its shutdown."""
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=1.0)


class Probe(Node):
    """Own only the operator heartbeat and test clients; retain all observed traces."""

    def __init__(self, directory):
        """Create asynchronous clients and bounded in-memory observation histories."""
        super().__init__('m3_acceptance_probe')
        self.output = (directory / 'trace.jsonl').open('w')
        self.samples = {}
        self.history = {}
        transient = QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL)
        for name, kind, topic, qos in (
            ('truth', VehicleStateArray, '/sim/evaluator/ground_truth', 10),
            ('command', Twist, '/bus/cmd_vel', 1),
            ('door', Bool, '/bus/door_open', 1),
            ('odom', Odometry, '/bus/odom', 10),
            ('arrival', BusArrival, '/hub/bus_arrival', 10),
            ('queue', QueueState, '/hub/queue', 10),
            ('safety', SafetyState, '/hub/safety', transient),
            ('crossing', CrossingState, '/crossing/state', transient),
            ('event', HubEvent, '/hub/events', 100),
        ):
            self.history[name] = deque(maxlen=30000)
            self.create_subscription(kind, topic, lambda msg, k=name: self.record(k, msg), qos)
        self.add_passenger = self.create_client(Trigger, '/sim/add_passenger')
        self.action = ActionClient(self, DockBus, '/bus/dock')
        self.robot_token = ''
        self.robot_future = None
        self.cross_client = self.create_client(RequestCrossing, '/crossing/request')
        self.create_timer(0.2, self.renew_robot)
        self.reset_client = self.create_client(ResetScenario, '/scenario/reset')
        self.clear_client = self.create_client(ClearSafetyStop, '/safety/clear_stop')
        self.route_client = self.create_client(ComputeRoute, '/route/compute')
        self.parameters = {
            name: AsyncParameterClient(self, name)
            for name in ('scenario_runner', 'm3_synthetic_roads', 'bus_manager')
        }
        self.feedback = deque(maxlen=30000)
        self.operator_heartbeat = OperatorHeartbeat(directory)

    def set_estop(self, value):
        """Set operator state and require acknowledgement from its publisher process."""
        self.operator_heartbeat.set_state(value)

    def destroy_node(self):
        """Stop the external operator before destroying evaluator ROS entities."""
        self.operator_heartbeat.close()
        return super().destroy_node()

    def renew_robot(self):
        """Maintain the test competitor's lease without competing motion publishers."""
        if self.robot_token and (self.robot_future is None or self.robot_future.done()):
            self.robot_future = self.cross_client.call_async(
                RequestCrossing.Request(
                    requester_id='robot', operation='RENEW', token=self.robot_token
                )
            )

    def record(self, name, message):
        """Write acquisition-bearing messages with monotonic observer timestamps."""
        now = time.monotonic()
        self.samples[name] = message
        self.history[name].append((now, message))
        self.output.write(
            json.dumps({'t': now, 'topic': name, 'message': message_to_ordereddict(message)})
            + '\n'
        )

    def wait(self, predicate, seconds=5.0):
        """Spin real callbacks up to an explicit monotonic deadline."""
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if predicate():
                return True
            rclpy.spin_once(self, timeout_sec=0.02)
        return bool(predicate())

    def future(self, future, seconds=5.0):
        """Require a bounded response; never infer success from timeout."""
        assert self.wait(future.done, seconds), 'client deadline exceeded'
        return future.result()

    def pause(self, seconds):
        """Keep the heartbeat and subscriptions alive during deliberate observation."""
        self.wait(lambda: False, seconds)

    def boarding_goal_readiness(self):
        """Wait briefly for fresh physical and supervisor clearance before a new goal."""
        def snapshot():
            now = time.monotonic()
            observed = {}
            for name in ('door', 'truth', 'safety'):
                history = self.history[name]
                if history:
                    received, message = history[-1]
                    observed[name] = {
                        'age_sec': round(now - received, 3),
                        'message': message_to_ordereddict(message),
                    }
                else:
                    observed[name] = None
            bus = self.bus()
            door = self.samples.get('door')
            safety = self.samples.get('safety')
            ages = {
                name: now - history[-1][0] if history else math.inf
                for name, history in self.history.items()
                if name in ('door', 'truth', 'safety')
            }
            ready = (
                all(age <= 0.5 for age in ages.values())
                and door is not None
                and not door.data
                and bus is not None
                and bus.valid
                and abs(bus.speed_mps) < 0.02
                and safety is not None
                and safety.motion_permitted
                and not safety.stop_latched
            )
            return ready, {
                'door_closed': door is not None and not door.data,
                'bus_stopped': bus is not None and bus.valid and abs(bus.speed_mps) < 0.02,
                'supervisor_clear': safety is not None
                and safety.motion_permitted
                and not safety.stop_latched,
                'observations': observed,
            }

        deadline = time.monotonic() + 2.0
        ready, observed = snapshot()
        while not ready and time.monotonic() < deadline:
            rclpy.spin_once(self, timeout_sec=0.02)
            ready, observed = snapshot()
        self.output.write(
            json.dumps(
                {
                    't': time.monotonic(),
                    'topic': 'boarding_goal_readiness',
                    'ready': ready,
                    'deadline_sec': 2.0,
                    'observed': observed,
                }
            )
            + '\n'
        )
        assert ready, f'boarding goal readiness timed out after 2.0 s: {observed}'
        return observed

    def params(self, node, **values):
        """Set only fixture fault parameters via their real ROS parameter service."""
        response = self.future(
            self.parameters[node].set_parameters(
                [Parameter(name, value=value) for name, value in values.items()]
            )
        )
        assert all(r.successful for r in response.results), str(response)
        self.output.write(
            json.dumps(
                {
                    't': time.monotonic(),
                    'topic': 'parameter_update',
                    'node': node,
                    'values': values,
                }
            )
            + '\n'
        )

    def bus(self):
        """Return evaluator bus truth only for metrics, never to a controller."""
        message = self.samples.get('truth')
        return (
            next((v for v in message.vehicles if v.vehicle_id == 'bus'), None) if message else None
        )

    def moving(self):
        """Observe physical translation rather than goal acceptance alone."""
        bus = self.bus()
        return bus is not None and abs(bus.speed_mps) > 0.01

    def reset(self, seed):
        """Restore fixture inputs, explicitly clear latch and obtain all reset acknowledgements."""
        self.set_estop(False)
        self.params(
            'scenario_runner', publish_bus_odom=True, publish_queue=True, pedestrian_present=False
        )
        self.params(
            'm3_synthetic_roads',
            blocked_edges=[''],
            publish_edges=True,
            freeze_edges=False,
            bay_clear=True,
        )
        self.pause(2.2)
        if self.samples.get('safety') and self.samples['safety'].stop_latched:
            response = self.future(
                self.clear_client.call_async(
                    ClearSafetyStop.Request(
                        operator_id='m3-probe', acknowledgement='deliberate recovery'
                    )
                )
            )
            assert response.success, response.reason
            self.pause(0.2)
        request = ResetScenario.Request(scenario_id='m2_baseline', seed=seed, preserve_logs=True)
        response = self.future(self.reset_client.call_async(request), 3)
        assert response.success, response.reason
        self.pause(2.2)
        return response.run_id

    def send(self, duration=180.0):
        """Send a real action goal and retain feedback and goal identifiers."""

        def feedback(message):
            now = time.monotonic()
            self.feedback.append((now, message.feedback))
            self.output.write(
                json.dumps(
                    {'t': now, 'topic': 'feedback', 'message': message_to_ordereddict(message)}
                )
                + '\n'
            )

        goal = DockBus.Goal(bus_id='bus', bay_id='B', max_duration_sec=float(duration))
        handle = self.future(self.action.send_goal_async(goal, feedback_callback=feedback))
        assert handle.accepted, 'goal unexpectedly rejected'
        self.output.write(
            json.dumps(
                {
                    't': time.monotonic(),
                    'topic': 'goal',
                    'goal_id': bytes(handle.goal_id.uuid).hex(),
                    'message': message_to_ordereddict(goal),
                }
            )
            + '\n'
        )
        result = handle.get_result_async()
        result.add_done_callback(
            lambda future: self.output.write(
                json.dumps(
                    {
                        't': time.monotonic(),
                        'topic': 'result',
                        'goal_id': bytes(handle.goal_id.uuid).hex(),
                        'message': message_to_ordereddict(future.result()),
                    }
                )
                + '\n'
            )
        )
        return handle, result

    def cancel_goal(self, handle, result):
        """Measure accepted-cancel to observed zero and confirmed action cancellation."""
        requested = time.monotonic()
        response = self.future(handle.cancel_goal_async())
        accepted = time.monotonic()
        assert response.goals_canceling, 'cancel denied: ' + str(response)
        assert self.wait(
            lambda: any(
                t >= accepted and m.linear.x == 0 and m.angular.z == 0
                for t, m in self.history['command']
            ),
            0.5,
        )
        latency = (
            min(
                t
                for t, m in self.history['command']
                if t >= accepted and m.linear.x == 0 and m.angular.z == 0
            )
            - requested
        )
        assert latency <= 0.5
        terminal = self.future(result, 3)
        assert terminal.status == GoalStatus.STATUS_CANCELED, str(terminal)
        assert self.wait(lambda: self.bus().speed_mps == 0, 0.3), 'truth stop not observed'
        return latency


FAULT_CASES = [
    'arrival_during_boarding_and_interruption',
    'cancel_during_approach',
    'action_timeout',
    'blocked_bay_wait',
    'planner_timeout_retries_and_late_reply',
    'no_route',
    'frozen_edge_source_stamp',
    'stale_bus_pose',
    'estop_aborts_and_latches',
    'pedestrian_before_crossing_entry',
    'active_route_missing_feed',
    'busy_goal_rejection',
    'crossing_denial_renewal_loss_and_explicit_recovery',
    'active_mission_reset',
]


def verify(probe, processes, nominal_runs, only_case=None, door_comparison=False):
    """Stop at the first FAIL or BLOCKED case and retain every downstream NOT RUN."""
    names = [f'nominal_docking_{i + 1:02}' for i in range(nominal_runs)] + FAULT_CASES
    if not nominal_runs:
        names.remove('arrival_during_boarding_and_interruption')
    if only_case:
        names = [only_case]
    if door_comparison:
        names = ['door_comparison_seed_304']
    measurement = {}
    runner = CaseRunner(names, measurement)
    try:
        _verify_cases(probe, processes, nominal_runs, only_case, door_comparison,
                      runner.run, measurement)
    except StopCases:
        pass
    except (Exception, KeyboardInterrupt) as error:
        runner.results.append({
            'name': 'verifier_setup', 'status': 'BLOCKED', 'reason': repr(error),
            'traceback': traceback.format_exc(),
        })
    return runner.finish()


def _verify_cases(probe, processes, nominal_runs, only_case, door_comparison, case, measurement):
    """Exercise the declared M3 cases through the fail-fast recording harness."""
    assert probe.wait(lambda: probe.action.server_is_ready() and len(probe.samples) >= 8, 15)
    probe.pause(2.5)
    for node in (
        'scenario_runner',
        'safety_supervisor',
        'hub_coordinator',
        'route_planner',
        'bus_manager',
        'm3_synthetic_roads',
    ):
        if node not in probe.parameters:
            probe.parameters[node] = AsyncParameterClient(probe, node)
        client = probe.parameters[node]
        assert probe.wait(client.services_are_ready, 8), 'parameter service unavailable: ' + node
        listing = probe.future(client.list_parameters(prefixes=[], depth=0), 5)
        names = listing.result.names
        values = probe.future(client.get_parameters(names), 5).values
        assert names and len(names) == len(values)
        record = {name: message_to_ordereddict(value) for name, value in zip(names, values)}
        (Path(probe.output.name).parent / (node + '-parameters.json')).write_text(
            json.dumps(record, indent=2) + '\n'
        )

    def nominal(index):
        count = [0, 2, 4, 6][index % 4]
        probe.parameters_count = count
        probe.params('scenario_runner', initial_passengers=count)
        run_id = probe.reset(300 + index)
        start = time.monotonic()
        handle, result = probe.send()
        assert probe.wait(result.done, 180), 'mission did not terminate'
        terminal = result.result()
        goal_id = bytes(handle.goal_id.uuid).hex()
        # Event delivery can trail the action result; this wait is evaluator-only.
        probe.wait(lambda: any(
            m.event == 'DOOR_MEASURED' and m.run_id == run_id
            and m.correlation_id == goal_id and json.loads(m.reason)['operation'] == 'goal_end'
            for _, m in probe.history['event']), 1.0)
        source = assess_source(
            [message_to_ordereddict(m) for _, m in probe.history['event']],
            run_id, goal_id,
            terminal.status == GoalStatus.STATUS_SUCCEEDED and terminal.result.success)
        measurement.update(run_id=run_id, goal_id=goal_id, seed=300 + index,
                           source_door_assessment=source, other_nominal_requirements='NOT PASS')
        assert terminal.status == GoalStatus.STATUS_SUCCEEDED, str(terminal)
        bus = probe.bus()
        position = math.hypot(bus.pose.x - 8, bus.pose.y - 4)
        yaw = abs(math.atan2(math.sin(bus.pose.theta), math.cos(bus.pose.theta)))
        assert position <= 0.2 and yaw <= 0.17
        assert not probe.samples['door'].data and bus.speed_mps == 0
        boards = [
            (t, m)
            for t, m in probe.history['event']
            if t >= start and m.event == 'PASSENGER_BOARDED'
        ]
        expected = min(4, int(probe.parameters_count))
        assert len(boards) == expected, f'boarding count {len(boards)} != {expected}'
        boarding = [json.loads(m.reason) for _, m in boards]
        assert len({r['passenger_id'] for r in boarding}) == len(boarding)
        # Pair measured door samples with nearest preceding physical truth.
        truth = [(t, m) for t, m in probe.history['truth'] if t >= start]
        separation = []
        for _, message in truth:
            by_id = {v.vehicle_id: v for v in message.vehicles}
            a, b = by_id['bus'].pose, by_id['robot'].pose
            separation.append(math.hypot(a.x - b.x, a.y - b.y))
        assert separation and min(separation) > 0.7
        for t, door in probe.history['door']:
            if t < start or not door.data:
                continue
            previous = [m for at, m in truth if at <= t]
            if previous:
                state = next(v for v in previous[-1].vehicles if v.vehicle_id == 'bus')
                assert state.speed_mps == 0, 'open-door physical motion'
        dock_events = [t for t, m in probe.history['event'] if t >= start and m.event == 'BOARD']
        assert dock_events, 'no docking transition'
        docked = min(dock_events)
        held = [
            (t, next(v for v in m.vehicles if v.vehicle_id == 'bus'))
            for t, m in truth
            if docked - 0.9 <= t <= docked
        ]
        assert len(held) >= 7
        assert all(
            v.speed_mps == 0
            and math.hypot(v.pose.x - 8, v.pose.y - 4) <= 0.2
            and abs(v.pose.theta) <= 0.17
            for _, v in held
        )
        doors = [(t, m.data) for t, m in probe.history['door'] if t >= start]
        opened = min(t for t, value in doors if value)
        closed = min(t for t, value in doors if t > opened and not value)
        receipt = assess_receipts(opened, closed, source)
        measurement.update(receipt_assertion=receipt, measured_door_open_sec=closed - opened)
        sample = [
            (abs(m.distance_remaining_m - 5), t, m.eta_sec)
            for t, m in probe.feedback
            if t >= start and m.eta_sec >= 0 and m.phase == 'APPROACH'
        ]
        assert sample, 'no valid moving ETA'
        _, at, eta = min(sample)
        error = abs(eta - (docked - at))
        assert error <= 3.0, f'ETA error {error}'
        invalid = sum(0.5 for t, m in probe.feedback if t >= start and m.eta_sec < 0)
        measurement['other_nominal_requirements'] = 'PASS'
        if source['status'] == 'BLOCKED':
            raise Blocked(str(source))
        assert source['status'] == 'PASS', str(source)
        return {
            **measurement,
            'run_id': run_id,
            'seed': 300 + index,
            'position_error_m': position,
            'yaw_error_rad': yaw,
            'eta_error_at_5m_sec': error,
            'eta_invalid_duration_sampled_sec': invalid,
            'boarding': boarding,
            'goal_id': goal_id,
            'minimum_agent_separation_m': min(separation),
            'measured_door_open_sec': closed - opened,
            'initial_passengers': count,
        }

    probe.parameters_count = 6
    if door_comparison:
        case('door_comparison_seed_304', lambda: nominal(4))
        return
    for index in range(0 if only_case else nominal_runs):
        if not case(f'nominal_docking_{index + 1:02}', lambda i=index: nominal(i)):
            return

    def arrival_during_boarding():
        # The preceding nominal goal leaves the bus stopped at B; no teleport is used.
        readiness = probe.boarding_goal_readiness()
        started = time.monotonic()
        handle, result = probe.send(20)
        assert probe.wait(lambda: probe.samples['door'].data, 5)
        probe.pause(2.3)
        added = probe.future(probe.add_passenger.call_async(Trigger.Request()))
        assert added.success
        assert probe.wait(
            lambda: any(
                t >= started and m.event == 'PASSENGER_BOARDED' and m.entity_id == added.message
                for t, m in probe.history['event']
            ),
            4,
        )
        latency = probe.cancel_goal(handle, result)
        records = [
            json.loads(m.reason)
            for t, m in probe.history['event']
            if t >= started and m.event == 'PASSENGER_BOARDED' and m.entity_id == added.message
        ]
        assert len(records) == 1 and records[0]['slot'] >= 2
        probe.pause(0.3)
        assert not probe.samples['door'].data
        return {
            'arrival_id': added.message,
            'boarding': records[0],
            'cancel_zero_sec': latency,
            'door_closed_after_interruption': True,
            'pre_goal_readiness': readiness,
        }

    if nominal_runs:
        case('arrival_during_boarding_and_interruption', arrival_during_boarding)

    def cancel():
        probe.params('scenario_runner', initial_passengers=6)
        probe.reset(400)
        handle, result = probe.send()
        assert probe.wait(probe.moving, 30)
        return {'command_zero_latency_sec': probe.cancel_goal(handle, result)}

    if not case('cancel_during_approach', cancel):
        return

    def timeout():
        probe.reset(401)
        _, result = probe.send(0.5)
        terminal = probe.future(result, 4)
        assert terminal.status == GoalStatus.STATUS_ABORTED and terminal.result.reason == 'TIMEOUT'
        return {'reason': terminal.result.reason}

    case('action_timeout', timeout)

    def blocked_bay():
        probe.reset(402)
        probe.params('m3_synthetic_roads', bay_clear=False)
        probe.pause(0.6)
        handle, result = probe.send(4)
        probe.pause(1)
        assert probe.samples['arrival'].state == 'WAIT'
        assert not probe.samples['arrival'].eta_valid
        assert not probe.moving()
        latency = probe.cancel_goal(handle, result)
        return {'wait_observed': True, 'invalid_eta': True, 'cancel_zero_sec': latency}

    case('blocked_bay_wait', blocked_bay)

    def unavailable():
        probe.reset(403)
        os.killpg(processes['route_planner'].pid, signal.SIGSTOP)
        try:
            start = time.monotonic()
            _, result = probe.send(10)
            terminal = probe.future(result, 8)
            assert terminal.result.reason == 'PLANNER_UNAVAILABLE', str(terminal)
            requests = [
                m for t, m in probe.history['event'] if t >= start and m.event == 'ROUTE_REQUEST'
            ]
            assert len(requests) == 3
            request_times = [
                json.loads(m.reason)['sent_monotonic']
                for t, m in probe.history['event']
                if t >= start and m.event == 'ROUTE_REQUEST'
            ]
            gaps = [b - a for a, b in zip(request_times, request_times[1:])]
            assert gaps[0] >= 1.25 - 1e-6 and gaps[1] >= 1.5 - 1e-6
        finally:
            os.killpg(processes['route_planner'].pid, signal.SIGCONT)
        probe.pause(0.5)
        assert not probe.moving(), 'late planner reply caused movement'
        return {'attempts': 3, 'reason': terminal.result.reason, 'late_reply_motion': False}

    case('planner_timeout_retries_and_late_reply', unavailable)

    def no_route():
        probe.reset(404)
        probe.params('m3_synthetic_roads', blocked_edges=['A-Cs', 'A-N'])
        probe.pause(0.6)
        rejected = probe.future(
            probe.action.send_goal_async(
                DockBus.Goal(bus_id='bus', bay_id='B', max_duration_sec=10.0)
            )
        )
        assert not rejected.accepted
        assert not probe.moving()
        return {'reason': 'NO_ROUTE', 'unreachable_goal_rejected': True}

    case('no_route', no_route)

    def frozen_edges():
        probe.reset(405)
        probe.params('m3_synthetic_roads', freeze_edges=True)
        probe.pause(1.7)
        response = probe.future(
            probe.route_client.call_async(
                ComputeRoute.Request(start_node='A', goal_node='B', agent_type='bus')
            )
        )
        assert not response.success and response.reason == 'NO_ROUTE'
        return {'reason': response.reason}

    case('frozen_edge_source_stamp', frozen_edges)

    def stale_pose():
        probe.reset(406)
        _, result = probe.send(30)
        assert probe.wait(probe.moving, 25)
        probe.params('scenario_runner', publish_bus_odom=False)
        terminal = probe.future(result, 5)
        assert terminal.status == GoalStatus.STATUS_ABORTED
        assert terminal.result.reason.startswith('STALE_POSE'), str(terminal)
        probe.params('scenario_runner', publish_bus_odom=True)
        return {'reason': terminal.result.reason}

    case('stale_bus_pose', stale_pose)

    def estop():
        probe.reset(407)
        _, result = probe.send(30)
        assert probe.wait(probe.moving, 25)
        probe.set_estop(True)
        terminal = probe.future(result, 4)
        assert terminal.result.reason == 'SAFETY_STOP', str(terminal)
        probe.set_estop(False)
        probe.pause(0.3)
        assert probe.samples['safety'].stop_latched
        return {'reason': terminal.result.reason, 'false_does_not_clear': True}

    case('estop_aborts_and_latches', estop)

    def pedestrian():
        probe.reset(410)
        _, result = probe.send(30)
        assert probe.wait(probe.moving, 25)
        probe.params('scenario_runner', pedestrian_present=True)
        terminal = probe.future(result, 4)
        assert terminal.result.reason == 'SAFETY_STOP'
        assert probe.bus().pose.x < 4.0
        assert probe.wait(lambda: not probe.moving(), 0.4), 'truth stop not observed'
        return {'reason': terminal.result.reason, 'entry_inhibited': True}

    case('pedestrian_before_crossing_entry', pedestrian)

    def stale_active_route():
        probe.reset(411)
        _, result = probe.send(30)
        assert probe.wait(probe.moving, 25)
        probe.params('m3_synthetic_roads', publish_edges=False)
        terminal = probe.future(result, 4)
        assert terminal.result.reason == 'ROUTE_INVALID_OR_STALE'
        return {'reason': terminal.result.reason}

    case('active_route_missing_feed', stale_active_route)

    def busy_rejection():
        probe.reset(412)
        handle, result = probe.send(30)
        rejected = probe.future(
            probe.action.send_goal_async(
                DockBus.Goal(bus_id='bus', bay_id='B', max_duration_sec=30.0)
            )
        )
        assert not rejected.accepted
        probe.cancel_goal(handle, result)
        return {'second_goal_rejected': True}

    case('busy_goal_rejection', busy_rejection)

    def crossing_denial_and_renewal_loss():
        probe.reset(413)
        response = probe.future(
            probe.cross_client.call_async(
                RequestCrossing.Request(requester_id='robot', operation='ACQUIRE', token='')
            )
        )
        assert response.granted, response.reason
        probe.robot_token = response.token
        try:
            started = time.monotonic()
            _, result = probe.send(120)
            assert probe.wait(lambda: probe.bus().pose.x >= 2.6, 65)
            probe.pause(0.6)
            assert not probe.samples['arrival'].eta_valid, 'unknown crossing wait became zero'
            assert probe.wait(lambda: probe.samples['arrival'].state == 'WAIT', 20)
            probe.pause(2.0)
            assert probe.bus().pose.x < 4.0 and not probe.moving()
            assert not probe.samples['arrival'].eta_valid
            denied = [
                m.reason
                for t, m in probe.history['event']
                if t >= started and m.event == 'CROSSING_DENIED'
            ]
            assert 2 <= len(denied) <= 12
            token, probe.robot_token = probe.robot_token, ''
            released = probe.future(
                probe.cross_client.call_async(
                    RequestCrossing.Request(requester_id='robot', operation='RELEASE', token=token)
                )
            )
            assert released.granted, released.reason
            assert probe.wait(lambda: probe.bus().pose.x >= 4.6, 15)
            stopped_at = time.monotonic()
            os.killpg(processes['crossing_arbiter'].pid, signal.SIGSTOP)
            try:
                assert probe.wait(
                    lambda: any(
                        t >= stopped_at and m.linear.x == 0 and m.angular.z == 0
                        for t, m in probe.history['command']
                    ),
                    0.8,
                )
                terminal = probe.future(result, 4)
                assert terminal.status == GoalStatus.STATUS_ABORTED
            finally:
                os.killpg(processes['crossing_arbiter'].pid, signal.SIGCONT)
            probe.pause(0.7)
            assert probe.samples['crossing'].owner_id == 'bus'
            assert not probe.moving(), 'old mission restarted after renewal recovery'
            # Explicit new mission must compute a fresh route from the current edge.
            _, recovered = probe.send(90)
            terminal = probe.future(recovered, 90)
            assert terminal.status == GoalStatus.STATUS_SUCCEEDED, str(terminal)
            return {
                'denials': denied,
                'renewal_loss_stopped': True,
                'occupied_owner_retained': True,
                'explicit_new_goal_recovered': True,
            }
        finally:
            probe.robot_token = ''

    case('crossing_denial_renewal_loss_and_explicit_recovery', crossing_denial_and_renewal_loss)

    def active_reset():
        probe.reset(408)
        _, result = probe.send(30)
        probe.pause(0.4)
        response = probe.future(
            probe.reset_client.call_async(
                ResetScenario.Request(scenario_id='m2_baseline', seed=409, preserve_logs=True)
            ),
            2,
        )
        assert response.success, response.reason
        terminal = probe.future(result, 3)
        assert terminal.result.reason == 'SCENARIO_RESET', str(terminal)
        assert probe.wait(
            lambda: probe.bus() and probe.bus().pose.x == 1 and probe.bus().pose.y == 2, 2
        )
        assert not probe.samples['door'].data
        return {
            'reason': response.reason,
            'action_reason': terminal.result.reason,
            'run_id': response.run_id,
        }

    case('active_mission_reset', active_reset)


def main():
    """Start isolated real nodes, retain logs on failure and report honest acceptance."""
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True)
    parser.add_argument('--nominal-runs', type=int, default=10)
    parser.add_argument('--door-comparison', action='store_true',
                        help='one seed-304 comparison; retain receipt assertion separately')
    parser.add_argument(
        '--only-case',
        choices=(
            'busy_goal_rejection',
            'crossing_denial_renewal_loss_and_explicit_recovery',
        ),
    )
    args = parser.parse_args()
    if args.door_comparison and args.only_case:
        parser.error('--door-comparison cannot be combined with --only-case')
    directory = Path(args.output).resolve().parent
    if directory.exists():
        raise SystemExit('Evidence directory already exists; choose a unique run ID')
    directory.mkdir(parents=True)
    processes, logs = {}, []
    commands = {
        'scenario_runner': [
            'smart_hub_sim',
            'scenario_runner',
            '--ros-args',
            '-p',
            'm3_mode:=true',
        ],
        'safety_supervisor': ['smart_hub_safety', 'safety_supervisor'],
        'crossing_arbiter': ['smart_hub_control', 'crossing_arbiter'],
        'route_planner': ['smart_hub_control', 'route_planner'],
        'bus_manager': ['smart_hub_control', 'bus_manager'],
        'm3_synthetic_roads': ['smart_hub_control', 'm3_synthetic_roads'],
    }
    started = time.monotonic()
    probe = None
    report = {
        'schema': 'smart-mobility-hub/m3-verification-v1',
        'status': 'FAIL',
        'nominal_runs': 1 if args.door_comparison else args.nominal_runs,
        'only_case': args.only_case,
        'scope': 'door measurement comparison only' if args.door_comparison else 'M3 verifier',
        'full_milestone_acceptance': False if args.door_comparison else None,
        'cases': [],
        'commands': commands,
        'clocks': 'monotonic latency; wall-backed ROS source stamps',
    }
    try:
        rclpy.init()
        probe = Probe(directory)
        for name, command in commands.items():
            log = (directory / (name + '.log')).open('w')
            logs.append(log)
            package, executable, *arguments = command
            installed = Path(get_package_prefix(package)) / 'lib' / package / executable
            invocation = [str(installed), *arguments]
            report.setdefault('actual_commands', {})[name] = invocation
            processes[name] = subprocess.Popen(
                invocation,
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        report['cases'] = verify(
            probe, processes, args.nominal_runs, args.only_case, args.door_comparison)
        report['status'] = overall_status(report['cases'])
        report['scenario_acceptance'] = (
            'NOT RUN: comparison is not milestone acceptance' if args.door_comparison else
            'T05/T06 eligible only with ten nominal runs and '
            'complete source-required fault evidence; other T rows NOT RUN')
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
            try:
                probe.output.close()
            except Exception as error:
                cleanup_error(report, 'trace_file', error)
        for log in logs:
            try:
                log.close()
            except Exception as error:
                cleanup_error(report, 'node_log', error)
        if rclpy.ok():
            try:
                rclpy.shutdown()
            except Exception as error:
                cleanup_error(report, 'rclpy', error)
        trace = directory / 'trace.jsonl'
        if trace.exists():
            try:
                report['trace_sha256'] = hashlib.sha256(trace.read_bytes()).hexdigest()
            except Exception as error:
                cleanup_error(report, 'trace_hash', error)
        report['elapsed_sec'] = time.monotonic() - started
        Path(args.output).write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'status': report['status'], 'output': args.output}), flush=True)
    raise SystemExit({'PASS': 0, 'FAIL': 1, 'BLOCKED': 2}[report['status']])


if __name__ == '__main__':
    main()
