#!/usr/bin/env python3
"""Record S9 faults T16-T18 (A section 16 pp22-23) in five mission phases with real nodes.

Every fault is injected once in each of five mission phases (A section 16.3: "Repeat
each fault five times at different mission phases"):

* T16 stop latch: E-stop asserted while moving, false after 2 s, reset rejected while a
  sensor is stale, accepted once inputs are fresh, and no motion until a new goal.
* T17 watchdogs: kill the active controller, kill the supervisor, and stop odometry,
  each separately. The supervisor and the simulator adapter must stop motion
  independently.
* T18 service loss: planner absent, and planner replying after the 1 s client
  timeout. At most two retries, an explicit failure, zero motion and no late path.

Zero-command latency is measured from the probe's own injection time to the first zero
final command it receives, so it is an upper bound on latency after supervisor
receipt. Measured simulator speed is reported separately (A section 16.3).
"""

import argparse
from collections import deque
import hashlib
import json
import math
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import traceback

from action_msgs.msg import GoalStatus
from ament_index_python.packages import get_package_prefix
from geometry_msgs.msg import Twist, TwistStamped
import rclpy
from rclpy.action import ActionClient
from smart_hub_interfaces.action import DockBus
from smart_hub_interfaces.srv import ClearSafetyStop
from smart_hub_sim.geometry import intersects_crossing
from verification import cleanup_error, signal_group, stop_processes
from verify_m6 import Probe as M6Probe

E_STOP_BOUND = 0.20          # A section 16.3 / T16
CANDIDATE_BOUND = 0.65       # 0.5 s command timeout + 0.05 s step + sampling (M2 bound)
ODOM_BOUND = 1.25            # 1 s odometry gap + one 20 Hz tick + sampling
ADAPTER_BOUND = 0.65         # adapter command expiry 0.5 s + step + sampling
PHASES = ('navigate_moving', 'escort_after_crossing', 'escort_in_crossing',
          'escort_replanning', 'bus_approach')
FAULTS = ('t16_estop_latch', 't17_kill_controller', 't17_kill_supervisor',
          't17_odometry_gap', 't18_planner_absent', 't18_planner_late')
NODES = {
    'scenario_runner': ['smart_hub_sim', 'scenario_runner', '--ros-args',
                        '-p', 'm3_mode:=true', '-p', 'm6_mode:=true'],
    'safety_supervisor': ['smart_hub_safety', 'safety_supervisor'],
    'crossing_arbiter': ['smart_hub_control', 'crossing_arbiter'],
    'route_planner': ['smart_hub_control', 'route_planner'],
    'bus_manager': ['smart_hub_control', 'bus_manager'],
    'robot_manager': ['smart_hub_control', 'robot_manager'],
    'm3_synthetic_roads': ['smart_hub_control', 'm3_synthetic_roads'],
}


class Graph:
    """Own every node process so single nodes can be killed and restarted."""

    def __init__(self, directory):
        """Start nothing yet; logs append across restarts."""
        self.directory, self.processes, self.logs = directory, {}, []

    def start(self, name, command=None):
        """Start one node in its own process group."""
        log = (self.directory / (name + '.log')).open('a')
        self.logs.append(log)
        if command is None:
            package, executable, *arguments = NODES[name]
            installed = Path(get_package_prefix(package)) / 'lib' / package / executable
            command = [str(installed), *arguments]
        self.processes[name] = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT,
                                                start_new_session=True)

    def kill(self, name):
        """SIGKILL one node group (no graceful shutdown, as for a crash)."""
        process = self.processes.pop(name)
        signal_group(process, signal.SIGKILL)
        process.wait(timeout=5)

    def stop(self):
        """Stop every node and close logs."""
        try:
            stop_processes(self.processes.values())
        finally:
            for log in self.logs:
                log.close()


class Probe(M6Probe):
    """M6 probe plus the bus action and bus command histories."""

    def __init__(self, directory):
        """Add bus subscriptions to the M6 recorder."""
        super().__init__(directory)
        for name, kind, topic in (('bus_command', Twist, '/bus/cmd_vel'),
                                  ('bus_candidate', TwistStamped, '/bus/cmd_vel_candidate')):
            self.history[name] = deque(maxlen=30000)
            self.create_subscription(kind, topic, lambda m, k=name: self.record(k, m), 1)
        self.dock = ActionClient(self, DockBus, '/bus/dock')
        self.recoveries = []

    def ready(self, seconds=40.0):
        """Wait until every service and parameter client the trials use is available."""
        clients = [self.reset_client, self.clear_client, self.ready_client]
        return self.wait(lambda: all(c.service_is_ready() for c in clients) and all(
            p.services_are_ready() for p in self.parameters.values()) and
            self.samples.get('truth') is not None and self.samples.get('safety') is not None,
            seconds)

    def speed(self, agent):
        """Measured simulator speed of one agent (evaluator truth); 0 before any truth."""
        vehicle = self.vehicle(agent)
        return abs(vehicle.speed_mps) if vehicle else 0.0

    def first_after(self, key, since, predicate):
        """Monotonic time of the first recorded sample after since that satisfies predicate."""
        return next((t for t, m in self.history[key] if t >= since and predicate(m)), None)


def zero(message):
    """A final Twist with every component zero."""
    return all(v == 0.0 for v in (message.linear.x, message.linear.y, message.linear.z,
                                  message.angular.x, message.angular.y, message.angular.z))


def truth_zero_time(probe, agent, since):
    """Time of the first truth sample after since with the agent stopped."""
    return probe.first_after('truth', since, lambda m: any(
        v.vehicle_id == agent and v.speed_mps == 0.0 for v in m.vehicles))


def recover(probe):
    """Operator recovery when a trial left an agent inside C (reset needs C clear).

    Restore inputs, clear the latch deliberately, then give each stranded agent a new
    goal that leaves C. Returns what was done; the next reset proves the result.
    """
    record = {'actions': []}
    probe.operator_heartbeat.set_state(False)
    probe.params('scenario_runner', publish_robot_odom=True, publish_bus_odom=True,
                 publish_queue=True, pedestrian_present=False)
    probe.params('m3_synthetic_roads', blocked_edges=[''], congested_edges=[''])
    probe.pause(2.2)
    if probe.samples.get('safety') and probe.samples['safety'].stop_latched:
        response = probe.future(probe.clear_client.call_async(ClearSafetyStop.Request(
            operator_id='s9-probe', acknowledgement='recovery before reset')))
        record['actions'].append({'clear_stop': response.success, 'reason': response.reason})
        probe.pause(0.5)
    for agent, radius in (('robot', 0.2), ('bus', 0.3)):
        vehicle = probe.vehicle(agent)
        if vehicle is None or not intersects_crossing(vehicle.pose.x, vehicle.pose.y,
                                                      radius + 0.2):
            continue
        if agent == 'robot':
            handle, result, _ = probe.send('navigate', goal='D')
        else:
            handle = probe.future(probe.dock.send_goal_async(DockBus.Goal(
                bus_id='bus', bay_id='B', max_duration_sec=120.0)), 5)
            result = handle.get_result_async() if handle.accepted else None
        left = result is not None and probe.wait(lambda: not intersects_crossing(
            probe.vehicle(agent).pose.x, probe.vehicle(agent).pose.y, radius + 0.2), 60)
        record['actions'].append({'moved_out_of_c': agent, 'accepted': result is not None,
                                  'left_c': bool(left)})
        if result is not None:
            probe.wait(result.done, 120)
    return record


def enter_phase(probe, phase, seed):
    """Reset, then drive the system into the named mission phase; return the goal."""
    try:
        probe.reset(seed)
    except AssertionError as error:
        probe.recoveries.append({'seed': seed, 'reset_error': repr(error),
                                 **recover(probe)})
        probe.reset(seed)
    started = time.monotonic()
    if phase == 'bus_approach':
        goal = DockBus.Goal(bus_id='bus', bay_id='B', max_duration_sec=120.0)
        handle = probe.future(probe.dock.send_goal_async(goal), 5)
        assert handle.accepted, 'dock goal rejected'
        result = handle.get_result_async()
        assert probe.wait(lambda: (probe.speed('bus') or 0) > 0.05 and
                          probe.vehicle('bus').pose.x > 2.0, 30), 'bus never moved'
        return 'bus', handle, result
    kind = 'navigate' if phase == 'navigate_moving' else 'escort'
    handle, result, _ = probe.send(kind, goal='D')
    assert handle is not None, f'{kind} goal rejected'
    if kind == 'escort':
        assert probe.wait_phase('WAIT_READY', started, 30), 'WAIT_READY not reached'
        assert probe.confirm().success, 'readiness rejected'
    robot = lambda: probe.vehicle('robot')  # noqa: E731
    if phase == 'navigate_moving':
        reached = probe.wait(lambda: robot().pose.x > 3.5 and probe.speed('robot') > 0.05, 40)
    elif phase == 'escort_after_crossing':
        reached = probe.wait(lambda: robot().pose.x > 6.0 and abs(robot().pose.y - 2) < .05
                             and probe.speed('robot') > 0.05, 120)
    elif phase == 'escort_in_crossing':
        reached = probe.wait(lambda: intersects_crossing(robot().pose.x, robot().pose.y, 0.2)
                             and probe.speed('robot') > 0.05, 120)
    else:   # escort_replanning: block Cs-J ahead of the robot and wait for the replan
        assert probe.wait(lambda: robot().pose.x > 3.5, 40), 'robot never moved'
        probe.params('m3_synthetic_roads', blocked_edges=['Cs-J'])
        reached = probe.wait(lambda: any(m.event == 'REPLAN'
                                         for _, m in probe.robot_events(started)), 30)
    assert reached, f'phase {phase} not reached'
    return 'robot', handle, result


def final_key(agent):
    """History key of the agent's final command topic."""
    return 'command' if agent == 'robot' else 'bus_command'


def odom_parameter(agent):
    """Simulator switch that silences the agent's odometry."""
    return 'publish_robot_odom' if agent == 'robot' else 'publish_bus_odom'


def outcome(probe, result, seconds):
    """Terminal action status and reason, or None if none arrived in time."""
    if not probe.wait(result.done, seconds):
        return None, 'NO_TERMINAL_RESULT'
    terminal = result.result()
    return terminal.status, terminal.result.reason


def no_motion(probe, agent, since, seconds):
    """Observe for a while; return the number of moving truth samples."""
    probe.pause(seconds)
    return sum(1 for t, m in probe.history['truth'] if t >= since for v in m.vehicles
               if v.vehicle_id == agent and v.speed_mps != 0.0)


def fault_estop(probe, graph, agent, result):
    """T16: assert, false, stale-sensor reset rejected, fresh reset accepted, no restart."""
    injected = time.monotonic()
    probe.operator_heartbeat.set_state(True)
    final_zero = probe.wait(lambda: probe.first_after(
        final_key(agent), injected, zero) is not None, 2.0)
    zero_at = probe.first_after(final_key(agent), injected, zero)
    latched_at = probe.first_after('safety', injected, lambda m: m.stop_latched)
    probe.pause(1.0)
    stopped_at = truth_zero_time(probe, agent, injected)
    probe.pause(1.0)
    probe.operator_heartbeat.set_state(False)
    released = time.monotonic()
    probe.pause(1.0)
    still_latched = bool(probe.samples['safety'].stop_latched)
    moved_after_false = no_motion(probe, agent, released, 0.5)
    probe.params('scenario_runner', **{odom_parameter(agent): False})
    probe.pause(1.3)
    unsafe = probe.future(probe.clear_client.call_async(ClearSafetyStop.Request(
        operator_id='s9-probe', acknowledgement='stale sensor present')))
    probe.params('scenario_runner', **{odom_parameter(agent): True})
    probe.pause(1.5)
    safe = probe.future(probe.clear_client.call_async(ClearSafetyStop.Request(
        operator_id='s9-probe', acknowledgement='inputs fresh; deliberate')))
    cleared = time.monotonic()
    restart_samples = no_motion(probe, agent, cleared, 3.0)
    status, reason = outcome(probe, result, 10)
    observed = {
        'zero_command_latency_sec': None if zero_at is None else zero_at - injected,
        'latch_observed_latency_sec': None if latched_at is None else latched_at - injected,
        'measured_stop_latency_sec': None if stopped_at is None else stopped_at - injected,
        'latched_after_false': still_latched, 'moving_samples_after_false': moved_after_false,
        'unsafe_reset': {'success': unsafe.success, 'reason': unsafe.reason},
        'safe_reset': {'success': safe.success, 'reason': safe.reason},
        'moving_samples_after_clear': restart_samples,
        'action_status': status, 'action_reason': reason,
    }
    failures = []
    if not final_zero or observed['zero_command_latency_sec'] > E_STOP_BOUND:
        failures.append('zero final command not within 0.20 s')
    if not still_latched or moved_after_false:
        failures.append('false E-stop cleared the latch or allowed motion')
    if unsafe.success:
        failures.append('reset accepted with a stale sensor')
    if not safe.success:
        failures.append('reset rejected with fresh inputs')
    if restart_samples:
        failures.append('motion restarted without a new goal')
    if status != GoalStatus.STATUS_ABORTED:
        failures.append(f'action not aborted: {status} {reason}')
    return observed, failures


def fault_kill_controller(probe, graph, agent, result):
    """T17: kill the mission controller; the supervisor must zero the stale candidate."""
    name = 'robot_manager' if agent == 'robot' else 'bus_manager'
    injected = time.monotonic()
    graph.kill(name)
    probe.wait(lambda: probe.first_after(final_key(agent), injected, zero) is not None, 2.0)
    zero_at = probe.first_after(final_key(agent), injected, zero)
    probe.pause(1.0)
    stopped_at = truth_zero_time(probe, agent, injected)
    reasons = sorted({m.reason for t, m in probe.history['safety'] if t >= injected})
    moving = no_motion(probe, agent, injected + CANDIDATE_BOUND + 0.2, 1.0)
    graph.start(name)
    probe.ready()
    observed = {
        'killed': name,
        'zero_command_latency_sec': None if zero_at is None else zero_at - injected,
        'measured_stop_latency_sec': None if stopped_at is None else stopped_at - injected,
        'safety_reasons_after_kill': reasons, 'moving_samples_after_bound': moving,
        'action_status': 'server killed (no result expected)',
    }
    failures = []
    if zero_at is None or zero_at - injected > CANDIDATE_BOUND:
        failures.append(f'supervisor did not zero within {CANDIDATE_BOUND} s')
    if moving:
        failures.append('motion continued after the candidate watchdog bound')
    if not any(r.startswith('candidate') or r == 'clear' for r in reasons):
        failures.append('no logged safety reason')
    return observed, failures


def fault_kill_supervisor(probe, graph, agent, result):
    """T17: kill the supervisor; the simulator adapter must expire the final command."""
    injected = time.monotonic()
    graph.kill('safety_supervisor')
    probe.pause(1.5)
    stopped_at = truth_zero_time(probe, agent, injected)
    moving = no_motion(probe, agent, injected + ADAPTER_BOUND + 0.1, 1.0)
    status, reason = outcome(probe, result, 10)
    graph.start('safety_supervisor')
    probe.ready()
    probe.pause(2.0)
    observed = {
        'killed': 'safety_supervisor',
        'measured_stop_latency_sec': None if stopped_at is None else stopped_at - injected,
        'moving_samples_after_bound': moving,
        'action_status': status, 'action_reason': reason,
    }
    failures = []
    if stopped_at is None or stopped_at - injected > ADAPTER_BOUND:
        failures.append(f'adapter did not stop motion within {ADAPTER_BOUND} s')
    if moving:
        failures.append('motion after adapter bound')
    if status != GoalStatus.STATUS_ABORTED:
        failures.append(f'mission not aborted after supervisor loss: {status} {reason}')
    return observed, failures


def fault_odometry(probe, graph, agent, result):
    """T17: odometry gap above 1 s; zero command and an aborted mission."""
    injected = time.monotonic()
    probe.params('scenario_runner', **{odom_parameter(agent): False})
    probe.wait(lambda: probe.first_after(
        'safety', injected, lambda m: 'odom' in m.reason) is not None, 3.0)
    zero_at = probe.first_after(final_key(agent), injected + 0.9, zero)
    stale_at = probe.first_after('safety', injected, lambda m: 'odom' in m.reason)
    status, reason = outcome(probe, result, 10)
    stopped_at = truth_zero_time(probe, agent, injected)
    probe.params('scenario_runner', **{odom_parameter(agent): True})
    probe.pause(1.5)
    observed = {
        'stale_reason_latency_sec': None if stale_at is None else stale_at - injected,
        'zero_command_latency_sec': None if zero_at is None else zero_at - injected,
        'measured_stop_latency_sec': None if stopped_at is None else stopped_at - injected,
        'safety_reason': next((m.reason for t, m in probe.history['safety']
                               if t >= injected and 'odom' in m.reason), None),
        'action_status': status, 'action_reason': reason,
    }
    failures = []
    if stale_at is None or stale_at - injected > ODOM_BOUND:
        failures.append('supervisor did not report stale odometry within bound')
    if zero_at is None:
        failures.append('no zero final command after odometry loss')
    if status != GoalStatus.STATUS_ABORTED:
        failures.append(f'mission not aborted: {status} {reason}')
    return observed, failures


def _planner_fault(probe, graph, agent, result, late):
    """Remove (or slow) the planner, force a replan, and require explicit failure."""
    injected = time.monotonic()
    graph.kill('route_planner')
    if late:
        graph.start('route_planner', [sys.executable, str(Path(__file__).with_name(
            's9_late_planner.py')), '--delay', '1.5'])
        probe.pause(1.0)
    # Invalidate the active route so a new planner request is required.
    blocked = ['D-J'] if agent == 'robot' else ['B-Cn', 'B-U']
    probe.params('m3_synthetic_roads', blocked_edges=blocked)
    status, reason = outcome(probe, result, 20)
    ended = time.monotonic()
    entity = agent
    requests = [m for t, m in probe.history['event'] if t >= injected and
                m.entity_id == entity and m.event == 'ROUTE_REQUEST']
    late_routes = [m for t, m in probe.history['event'] if t >= injected and
                   m.entity_id == entity and m.event == 'ROUTE']
    probe.params('m3_synthetic_roads', blocked_edges=[''])
    moving = no_motion(probe, agent, ended + 0.5, 3.0 if late else 1.5)
    graph.kill('route_planner')
    graph.start('route_planner')
    probe.pause(1.0)
    observed = {'route_requests_after_fault': len(requests),
                'routes_accepted_after_fault': len(late_routes),
                'action_status': status, 'action_reason': reason,
                'moving_samples_after_failure': moving}
    failures = []
    if len(requests) > 3:
        failures.append(f'{len(requests)} planner requests; at most 1 + 2 retries')
    if status != GoalStatus.STATUS_ABORTED or 'PLANNER' not in (reason or ''):
        failures.append(f'no explicit planner failure: {status} {reason}')
    if late_routes:
        failures.append('a late planner reply was executed')
    if moving:
        failures.append('motion after planner failure')
    return observed, failures


def fault_planner_absent(probe, graph, agent, result):
    """T18: planner process absent."""
    return _planner_fault(probe, graph, agent, result, late=False)


def fault_planner_late(probe, graph, agent, result):
    """T18: planner replies 1.5 s late, after the 1 s client timeout."""
    return _planner_fault(probe, graph, agent, result, late=True)


HANDLERS = dict(zip(FAULTS, (fault_estop, fault_kill_controller, fault_kill_supervisor,
                             fault_odometry, fault_planner_absent, fault_planner_late)))


def main():
    """Run every fault in every phase; record each trial, never stop early."""
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True)
    parser.add_argument('--faults', nargs='+', default=list(FAULTS), choices=FAULTS)
    parser.add_argument('--phases', nargs='+', default=list(PHASES), choices=PHASES)
    args = parser.parse_args()
    directory = Path(args.output).resolve().parent / (Path(args.output).stem + '-raw')
    if directory.exists():
        raise SystemExit('Evidence directory already exists; choose a unique run ID')
    directory.mkdir(parents=True)
    commit = subprocess.run(['git', 'rev-parse', 'HEAD'], capture_output=True,
                            text=True).stdout.strip()
    dirty = bool(subprocess.run(['git', 'status', '--porcelain'], capture_output=True,
                                text=True).stdout.strip())
    report = {'schema': 'smart-mobility-hub/s9-verification-v1', 'tests': ['T16', 'T17', 'T18'],
              'source': 'A section 16 pp22-23', 'commit': commit, 'worktree_dirty': dirty,
              'phases': args.phases, 'faults': args.faults, 'trials': [],
              'latency_note': 'zero-command latency measured from probe injection; an upper '
                              'bound on latency after supervisor receipt',
              'bounds_sec': {'estop_zero': E_STOP_BOUND, 'candidate_watchdog': CANDIDATE_BOUND,
                             'odometry_watchdog': ODOM_BOUND, 'adapter_expiry': ADAPTER_BOUND},
              'nodes': NODES, 'host_cpus': os.cpu_count()}
    graph, probe = Graph(directory), None
    started = time.monotonic()
    try:
        rclpy.init()
        probe = Probe(directory)
        for name in NODES:
            graph.start(name)
        if not probe.ready():
            raise RuntimeError('graph services not ready within 40 s')
        seed = 900
        for fault in args.faults:
            for phase in args.phases:
                seed += 1
                trial = {'fault': fault, 'phase': phase, 'seed': seed, 'status': 'FAIL'}
                began = time.monotonic()
                try:
                    agent, handle, result = enter_phase(probe, phase, seed)
                    trial['agent'] = agent
                    observed, failures = HANDLERS[fault](probe, graph, agent, result)
                    trial.update(observations=observed, failures=failures,
                                 status='FAIL' if failures else 'PASS')
                except Exception as error:
                    trial.update(error=repr(error), traceback=traceback.format_exc())
                    for name in NODES:   # restore any node a failed trial left down
                        if name not in graph.processes:
                            graph.start(name)
                    probe.operator_heartbeat.set_state(False)
                    probe.ready()
                trial['recoveries_before'] = probe.recoveries
                probe.recoveries = []
                trial['elapsed_sec'] = time.monotonic() - began
                report['trials'].append(trial)
                print(json.dumps({k: trial.get(k) for k in ('fault', 'phase', 'status',
                                                            'failures', 'error')}), flush=True)
                Path(args.output).write_text(json.dumps(report, indent=2) + '\n')
        statuses = [t['status'] for t in report['trials']]
        report['status'] = 'PASS' if statuses and all(s == 'PASS' for s in statuses) \
            else 'FAIL'
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
            graph.stop()
        except Exception as error:
            cleanup_error(report, 'nodes', error)
        if probe is not None:
            probe.output.close()
        if rclpy.ok():
            rclpy.shutdown()
        trace = directory / 'trace.jsonl'
        if trace.exists():
            report['trace_sha256'] = hashlib.sha256(trace.read_bytes()).hexdigest()
        report['summary'] = {
            fault: {'pass': sum(1 for t in report['trials']
                                if t['fault'] == fault and t['status'] == 'PASS'),
                    'trials': sum(1 for t in report['trials'] if t['fault'] == fault)}
            for fault in args.faults}
        report['elapsed_sec'] = time.monotonic() - started
        Path(args.output).write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'status': report['status'], 'summary': report['summary'],
                      'output': args.output}), flush=True)
    raise SystemExit({'PASS': 0, 'FAIL': 1, 'BLOCKED': 2}[report['status']])


if __name__ == '__main__':
    main()
