#!/usr/bin/env python3
"""Run focused seed-300 ROS diagnostics, separate from milestone acceptance."""

import argparse
import importlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import traceback

from gap_tools import Recorder, report, timed


COMMANDS = {
    'scenario_runner': ('smart_hub_sim', 'scenario_runner', '--ros-args', '-p', 'm3_mode:=true'),
    'safety_supervisor': ('smart_hub_safety', 'safety_supervisor'),
    'crossing_arbiter': ('smart_hub_control', 'crossing_arbiter'),
    'route_planner': ('smart_hub_control', 'route_planner'),
    'bus_manager': ('smart_hub_control', 'bus_manager'),
    'm3_synthetic_roads': ('smart_hub_control', 'm3_synthetic_roads'),
    'reset_coordinator': ('smart_hub_bringup', 'reset_coordinator',
                          '--ros-args', '-p', 'include_bus:=true'),
}


def register(directory, name, pid):
    """Publish child identity to the independent container sampler."""
    with (directory / 'pids.jsonl').open('a') as stream:
        stream.write(json.dumps({'name': name, 'pid': pid}) + '\n')


def worker(args):
    """Instrument imported classes only in this diagnostic subprocess."""
    import rclpy
    if args.worker == 'observer':
        from geometry_msgs.msg import Twist, TwistStamped
        from nav_msgs.msg import Odometry
        from rclpy.node import Node
        from rclpy.qos import DurabilityPolicy, QoSProfile
        from smart_hub_interfaces.msg import CrossingState, SafetyState, VehicleStateArray
        from std_msgs.msg import Bool
        from rosidl_runtime_py.convert import message_to_ordereddict
        recorder = Recorder(args.output, 'observer')
        rclpy.init()
        node = Node('gap_independent_observer')
        transient = QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL)

        def receive(topic, message):
            header = getattr(message, 'header', None)
            source = (header.stamp.sec + header.stamp.nanosec * 1e-9) if header else None
            values = {'source_wall': source}
            if topic == 'safety':
                values['message'] = message_to_ordereddict(message)
            recorder.emit(topic, **values)

        for name, kind, topic, qos in (
            ('odom', Odometry, '/bus/odom', 10),
            ('vehicles', VehicleStateArray, '/hub/vehicles', 10),
            ('command', Twist, '/bus/cmd_vel', 1),
            ('candidate', TwistStamped, '/bus/cmd_vel_candidate', 1),
            ('safety', SafetyState, '/hub/safety', transient),
            ('crossing', CrossingState, '/crossing/state', transient),
            ('estop', Bool, '/hub/estop', transient),
        ):
            node.create_subscription(kind, topic, lambda msg, k=name: receive(k, msg), qos)
        node.create_timer(0.1, lambda: recorder.emit('executor_heartbeat'))
        try:
            rclpy.spin(node)
        except (KeyboardInterrupt, rclpy.executors.ExternalShutdownException):
            pass
        finally:
            node.destroy_node()
            if rclpy.ok():
                rclpy.shutdown()
            recorder.close()
        return
    modules = {
        'scenario_runner': ('smart_hub_sim.scenario_runner', 'ScenarioRunner',
                            ('_step', '_publish_image', '_publish_vehicles',
                             '_publish_odom_and_tf')),
        'safety_supervisor': ('smart_hub_safety.supervisor', 'SafetySupervisor',
                              ('_tick', '_record', '_candidate_cb', '_estop_cb',
                               '_clear_cb', '_reset_cb', '_finish_reset_cb')),
        'bus_manager': ('smart_hub_control.bus', 'BusManager',
                        ('tick', 'record', 'state', 'publish_state', 'accept')),
        'crossing_arbiter': ('smart_hub_control.crossing', 'CrossingArbiter', ('tick',)),
    }
    module_name, class_name, methods = modules[args.worker]
    module = importlib.import_module(module_name)
    kind = getattr(module, class_name)
    recorder = Recorder(args.output, args.worker)
    if args.crossing_timing and args.worker in ('crossing_arbiter', 'safety_supervisor'):
        from crossing_timing import install
        install(kind, args.worker, recorder)
    if args.no_image and args.worker == 'scenario_runner':
        kind._publish_image = lambda *_: None
    if args.instrument:
        for name in methods:
            stage = {'_step': 'sim.step', '_tick': 'safety.tick',
                     'tick': 'bus.tick'}.get(name, name)
            setattr(kind, name, timed(recorder, stage, getattr(kind, name)))
    if args.worker == 'bus_manager' and args.instrument:
        original_record = kind.record

        def record_input(self, key, message):
            receipt = time.monotonic()
            header = getattr(message, 'header', None)
            stamp = getattr(header, 'stamp', None) if header is not None else None
            source_wall = ((stamp.sec + stamp.nanosec * 1e-9) if stamp is not None else None)
            try:
                return original_record(self, key, message)
            finally:
                recorder.emit('bus_input', key=key, source_wall=source_wall,
                              receipt_monotonic=receipt)

        kind.record = record_input
    original_init = kind.__init__

    def initialize(self, *positional, **keywords):
        original_init(self, *positional, **keywords)
        self.create_timer(0.1, lambda: recorder.emit('executor_heartbeat'))
    kind.__init__ = initialize
    try:
        module.main(args=['--ros-args', '-p', 'm3_mode:=true']
                    if args.worker == 'scenario_runner' else [])
    finally:
        recorder.close()


def stop_processes(processes):
    """Stop every node, including a paused diagnostic process, within bounded deadlines."""
    for process in processes:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGCONT)
            os.killpg(process.pid, signal.SIGINT)
    for process in processes:
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=2)


def attempt(args):
    """Run exactly one nominal mission without continuing into acceptance fault cases."""
    import rclpy
    from action_msgs.msg import GoalStatus
    from ament_index_python.packages import get_package_prefix
    from rclpy.parameter_client import AsyncParameterClient
    from rosidl_runtime_py.convert import message_to_ordereddict
    from verify_m3 import Probe

    directory = Path(args.output).resolve()
    directory.mkdir()
    for name in ('host.jsonl', 'container.jsonl'):
        (directory / name).symlink_to('../' + name)
    recorder = Recorder(directory / 'probe-timing.jsonl', 'probe')
    rclpy.init()
    probe = Probe(directory)
    probe.create_timer(0.1, lambda: recorder.emit('executor_heartbeat'))
    if args.instrument:
        probe.record = timed(recorder, 'probe.record', probe.record)
    processes, logs = [], []
    identities = {'probe': os.getpid()}
    metadata = {
        'seed': 300, 'initial_passengers': 0, 'instrumented': args.instrument,
        'crossing_timing': args.crossing_timing,
        'image_bypassed': args.no_image, 'status': 'ERROR', 'commands': {},
        'acceptance_eligible': False,
        'injected_pause': args.pause_node,
        'active_interval_established': False,
        'clocks': 'same-VM monotonic seconds; wall-backed ROS stamps; fixed-step physics',
    }
    register(directory.parent, directory.name + '/probe', os.getpid())
    metadata['active_start'] = time.monotonic()

    def spawn(name, command):
        log = (directory / (name + '.log')).open('w')
        logs.append(log)
        process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT,
                                   start_new_session=True)
        processes.append(process)
        identities[name] = process.pid
        metadata['commands'][name] = command
        register(directory.parent, directory.name + '/' + name, process.pid)
        return process

    try:
        for name, (package, executable, *extra) in COMMANDS.items():
            if (name in ('scenario_runner', 'safety_supervisor', 'bus_manager')
                    or args.crossing_timing and name == 'crossing_arbiter'):
                command = [sys.executable, __file__, '--worker', name,
                           '--output', str(directory / (name + '-timing.jsonl'))]
                if args.instrument:
                    command.append('--instrument')
                if args.crossing_timing:
                    command.append('--crossing-timing')
                if args.no_image:
                    command.append('--no-image')
            else:
                command = [str(Path(get_package_prefix(package)) / 'lib' / package / executable),
                           *extra]
            spawn(name, command)
        spawn('observer', [sys.executable, __file__, '--worker', 'observer',
                           '--output', str(directory / 'observer.jsonl')])
        assert probe.wait(lambda: probe.action.server_is_ready() and len(probe.samples) >= 8, 20)
        probe.pause(2.5)
        metadata['active_start'] = time.monotonic()
        metadata['active_interval_established'] = True
        probe.params('scenario_runner', initial_passengers=0)
        for node in ('scenario_runner', 'safety_supervisor', 'hub_coordinator',
                     'reset_coordinator', 'route_planner', 'bus_manager', 'm3_synthetic_roads'):
            client = AsyncParameterClient(probe, node)
            assert probe.wait(client.services_are_ready, 5), node
            names = probe.future(client.list_parameters(prefixes=[], depth=0)).result.names
            values = probe.future(client.get_parameters(names)).values
            (directory / (node + '-parameters.json')).write_text(json.dumps(
                dict(zip(names, map(message_to_ordereddict, values))), indent=2) + '\n')
        metadata['run_id'] = probe.reset(300)
        metadata['pre_goal_readiness'] = probe.boarding_goal_readiness()
        _, result = probe.send()
        if args.pause_node:
            assert probe.wait(probe.moving, 20), 'injection requires observed bus motion'
            spawn('pause-injector', [
                sys.executable, str(Path(__file__).with_name('gap_tools.py')), 'pause',
                '--pid', str(identities[args.pause_node]),
                '--output', str(directory / 'injection.jsonl'), '--seconds', '0.8'])
        assert probe.wait(result.done, 180), 'mission deadline exceeded'
        terminal = result.result()
        metadata['terminal'] = message_to_ordereddict(terminal)
        metadata['status'] = ('MISSION_SUCCEEDED' if terminal.status == GoalStatus.STATUS_SUCCEEDED
                              else 'MISSION_FAILED')
        # Preserve post-stop state and five seconds of context without restarting motion.
        probe.pause(5)
    except (Exception, KeyboardInterrupt) as error:
        metadata['error'] = repr(error)
        metadata['traceback'] = traceback.format_exc()
    finally:
        metadata['active_end'] = time.monotonic()
        stop_processes(processes)
        probe.output.close()
        recorder.close()
        for log in logs:
            log.close()
        probe.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
        (directory / 'run.json').write_text(json.dumps(metadata, indent=2) + '\n')
    print(json.dumps({'directory': str(directory), 'status': metadata['status']}), flush=True)


def campaign(args):
    """Bound baseline/instrumented trials; test image contribution only after a gap."""
    root = Path(args.output).resolve()
    deadline = time.monotonic() + args.seconds
    results = []
    comparisons = []
    image_test_due = False
    for index in range(args.runs):
        if time.monotonic() >= deadline:
            break
        instrument = index > 0 or bool(args.pause_node)
        no_image = image_test_due
        image_test_due = False
        variant = 'no-image' if no_image else ('instrumented' if instrument else 'baseline')
        directory = root / f'{index:02d}-{variant}'
        invocation = [sys.executable, __file__, '--attempt', '--output', str(directory)]
        if instrument:
            invocation.append('--instrument')
        if no_image:
            invocation.append('--no-image')
        if args.pause_node:
            invocation.extend(['--pause-node', args.pause_node])
        process = subprocess.Popen(invocation, start_new_session=True)
        try:
            process.wait(timeout=max(0.1, min(240, deadline - time.monotonic())))
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGINT)
            try:
                process.wait(timeout=50)
            except subprocess.TimeoutExpired:
                # Children have their own sessions. Explicitly reap them as well.
                for line in (root / 'pids.jsonl').read_text().splitlines():
                    child = json.loads(line)
                    if child['name'].startswith(directory.name + '/'):
                        try:
                            os.killpg(child['pid'], signal.SIGKILL)
                        except ProcessLookupError:
                            pass
                process.kill()
                process.wait()
        if not (directory / 'run.json').exists():
            results.append({'directory': directory.name, 'status': 'INTERRUPTED'})
            break
        analysis = report(directory)
        metadata = json.loads((directory / 'run.json').read_text())
        results.append({'directory': directory.name, 'status': metadata['status'],
                        'analysis': analysis['status'], 'windows': len(analysis['windows'])})
        comparisons.append({
            'directory': directory.name, 'instrumented': instrument,
            'image_bypassed': no_image, 'mission_status': metadata['status'],
            'cadence': analysis['cadence'], 'callback_metrics': analysis['callback_metrics'],
        })
        if analysis['windows'] and instrument and not no_image and not args.pause_node:
            image_test_due = True
        print(json.dumps(results[-1]), flush=True)
    (root / 'campaign.json').write_text(json.dumps({
        'acceptance_eligible': False, 'max_runs': args.runs, 'max_seconds': args.seconds,
        'attempts': results,
    }, indent=2) + '\n')
    (root / 'overhead-comparison.json').write_text(json.dumps({
        'interpretation': 'Compare baseline/instrumented cadence; uncontrolled scheduling '
                          'and failed missions prevent causal overhead estimates.',
        'attempts': comparisons,
    }, indent=2) + '\n')


def main():
    """Dispatch a campaign, a mission, or an independent worker subprocess."""
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True)
    parser.add_argument('--worker', choices=('observer', 'scenario_runner', 'safety_supervisor',
                                             'bus_manager', 'crossing_arbiter'))
    parser.add_argument('--attempt', action='store_true')
    parser.add_argument('--instrument', action='store_true')
    parser.add_argument('--crossing-timing', action='store_true')
    parser.add_argument('--no-image', action='store_true')
    parser.add_argument('--runs', type=int, default=10)
    parser.add_argument('--seconds', type=float, default=1200)
    parser.add_argument('--pause-node', choices=('probe', 'observer', 'scenario_runner'))
    args = parser.parse_args()
    if not 1 <= args.runs <= 10 or not 0 < args.seconds <= 1200:
        parser.error('runs must be 1..10 and seconds must be >0 and <=1200')
    if args.crossing_timing and not (args.attempt or args.worker):
        parser.error('--crossing-timing requires --attempt; no automatic campaign')
    if args.worker:
        worker(args)
    elif args.attempt:
        attempt(args)
    else:
        campaign(args)


if __name__ == '__main__':
    main()
