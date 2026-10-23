#!/usr/bin/env python3
"""Diagnose M3 reset acknowledgements locally without claiming scenario acceptance."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import time
import traceback

from ament_index_python.packages import get_package_prefix
from diagnose_m3_gap import COMMANDS
import rclpy
from rclpy.utilities import get_rmw_implementation_identifier
from verify_m3 import Probe


def main():
    """Exercise the real M3 reset chain and retain each participant's diagnostic log."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True)
    parser.add_argument('--runs', type=int, default=5)
    args = parser.parse_args()
    if not 1 <= args.runs <= 20:
        parser.error('runs must be in 1..20')
    directory = Path(args.output).resolve().parent
    directory.mkdir(parents=True, exist_ok=False)
    report = {
        'schema': 'smart-mobility-hub/reset-diagnostic-v1',
        'status': 'FAIL', 'acceptance_eligible': False,
        'scope': 'M3 reset only; no docking or M4 scenario acceptance',
        'cases': [], 'commands': {}, 'entrypoint_sha256': {},
        'cpu_affinity': sorted(os.sched_getaffinity(0)),
    }
    repo = Path(__file__).resolve().parents[1]
    report['source_commit'] = subprocess.check_output(
        ['git', '-C', str(repo), 'rev-parse', 'HEAD'], text=True).strip()
    report['worktree'] = subprocess.check_output(
        ['git', '-C', str(repo), 'status', '--porcelain'], text=True)
    report['configuration_sha256'] = hashlib.sha256(
        (repo / 'src/smart_hub_sim/config/map_m1.yaml').read_bytes()).hexdigest()
    report['source_sha256'] = {
        str(path.relative_to(repo)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in (
            repo / 'src/smart_hub_control/smart_hub_control/bus.py',
            repo / 'src/smart_hub_bringup/smart_hub_bringup/reset.py',
            Path(__file__).resolve(),
        )
    }
    processes, logs = [], []
    rclpy.init()
    report['rmw_implementation'] = get_rmw_implementation_identifier()
    probe = Probe(directory)
    try:
        for name, command in COMMANDS.items():
            package, executable, *arguments = command
            installed = Path(get_package_prefix(package)) / 'lib' / package / executable
            invocation = [str(installed), *arguments]
            report['commands'][name] = invocation
            report['entrypoint_sha256'][name] = hashlib.sha256(installed.read_bytes()).hexdigest()
            log = (directory / (name + '.log')).open('w')
            logs.append(log)
            processes.append(subprocess.Popen(
                invocation, stdout=log, stderr=subprocess.STDOUT, start_new_session=True))
        assert probe.wait(lambda: probe.action.server_is_ready() and
                          len(probe.samples) >= 8, 15), 'M3 graph not ready'
        for name, client in probe.parameters.items():
            assert probe.wait(client.services_are_ready, 8), name + ' parameters unavailable'
        probe.pause(2.5)
        probe.params('scenario_runner', initial_passengers=0)
        for index in range(args.runs):
            started = time.monotonic()
            record = {'seed': 300 + index, 'status': 'FAIL'}
            try:
                record['run_id'] = probe.reset(record['seed'])
                record['status'] = 'PASS'
            except Exception as error:
                record['error'] = repr(error)
                record['traceback'] = traceback.format_exc()
            record['elapsed_sec'] = time.monotonic() - started
            report['cases'].append(record)
            print(json.dumps(record), flush=True)
            if record['status'] != 'PASS':
                break
        if len(report['cases']) == args.runs and all(
                case['status'] == 'PASS' for case in report['cases']):
            report['status'] = 'PASS'
    except Exception as error:
        report['error'] = repr(error)
        report['traceback'] = traceback.format_exc()
    finally:
        for process in processes:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGINT)
        for process in processes:
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=2)
        probe.output.close()
        probe.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
        for log in logs:
            log.close()
        Path(args.output).write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'status': report['status'], 'output': args.output}), flush=True)
    return 0 if report['status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
