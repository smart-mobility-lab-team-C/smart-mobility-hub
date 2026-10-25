#!/usr/bin/env python3
"""Run one ordered door-validation attempt with pinned mounts and durable evidence."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

from verification import overall_status, run_bounded

IMAGE = 'sha256:f1c8db36f4874670d2125e3e40be69491da12273b28d4effb4f4d3c8b98a839b'
PACKAGE_SHA = '437ad4c24291a444fb81f3ae26ae2cd93f59bdf4907e610e2fc46aa64d092259'
CACHE = '.cache/m4-completion-v1'
CONTROL_GATES = [
    'mounts_and_dependencies', 'incremental_build', 'flake8', 'pep257',
    'producer_and_evaluator_controls', 'harness_controls', 'world_and_routing_regressions',
]
CHECK_SCRIPTS = [
    'scripts/door_duration.py', 'scripts/verify_m3.py', 'scripts/verification.py',
    'scripts/door_measurement.py', 'scripts/test_verification.py',
]


def utc():
    """Return an unambiguous UTC timestamp for each attempt boundary."""
    return datetime.now(timezone.utc).isoformat()


def write_json(path, value):
    """Replace a small ledger atomically so a stopped stage leaves valid JSON."""
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, indent=2) + '\n')
    temporary.replace(path)


def sha(path):
    """Hash an artifact without loading large traces into memory."""
    digest = hashlib.sha256()
    with path.open('rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def source_manifest(repo):
    """Include every source and harness file, excluding generated caches."""
    records = []
    for root in ('src', 'scripts'):
        for path in sorted((repo / root).rglob('*')):
            if (path.is_file() and path.suffix != '.pyc'
                    and not {'__pycache__', '.pytest_cache'} & set(path.parts)):
                records.append(sha(path) + '  ' + str(path.relative_to(repo)))
    return '\n'.join(records) + '\n'


def artifact_manifest(directory):
    """Hash all retained artifacts after a stage, including failed attempts."""
    path = directory / 'artifact-sha256.txt'
    records = [sha(item) + '  ' + str(item.relative_to(directory))
               for item in sorted(directory.rglob('*')) if item.is_file() and item != path]
    path.write_text('\n'.join(records) + '\n')


class GateStop(Exception):
    """End the attempt after its first unsuccessful gate."""


class Ledger:
    """Persist commands, timestamps, exit statuses and all unexecuted gates."""

    def __init__(self, directory, names, filename='gates.json'):
        """Write NOT RUN entries before any gate can fail."""
        self.directory = directory
        self.path = directory / filename
        self.records = [{'name': name, 'status': 'NOT RUN'} for name in names]
        write_json(self.path, self.records)

    def run(self, name, command, cwd, setup=False, bounded=None):
        """Record even command-launch failures and never retry a failed command."""
        record = next(item for item in self.records if item['name'] == name)
        record.update(command=command, cwd=str(cwd), started_utc=utc(), status='BLOCKED')
        write_json(self.path, self.records)
        started = time.monotonic()
        try:
            with (self.directory / (name + '.log')).open('w') as output:
                if bounded:
                    record.update(run_bounded(command, output, **bounded))
                else:
                    result = subprocess.run(command, cwd=cwd, stdout=output,
                                            stderr=subprocess.STDOUT, check=False)
                    record['exit_code'] = result.returncode
            code = record['exit_code']
            record['status'] = ('PASS' if code == 0 else
                                'BLOCKED' if setup or code == 2 else 'FAIL')
            if record.get('timed_out'):
                record['status'] = 'BLOCKED'
        except (Exception, KeyboardInterrupt) as error:
            record.update(status='BLOCKED', error=repr(error), exit_code=None)
        finally:
            record.update(ended_utc=utc(), elapsed_sec=time.monotonic() - started)
            write_json(self.path, self.records)
            artifact_manifest(self.directory)
        print(f"{name}: {record['status']} ({record['elapsed_sec']:.3f} s)", flush=True)
        if record['status'] != 'PASS':
            raise GateStop()


def overlay(command):
    """Load the verified cache for a command without leaking it into a fresh build."""
    return ['bash', '-c', 'set -eo pipefail; source /cache/install/setup.bash; exec "$@"',
            '--', *command]


def preflight(repo, directory):
    """Validate aliases, dependencies, prerequisites and imports before any build."""
    assert repo == Path('/workspace'), 'repository must be mounted at /workspace'
    assert os.path.ismount(repo) and os.path.ismount('/cache'), 'required bind mount missing'
    assert os.path.samefile(repo / CACHE, '/cache'), 'cache alias is not the repository cache'
    with (directory / 'package-versions.tsv').open('w') as output:
        subprocess.run(['dpkg-query', '-W'], stdout=output, check=True)
    assert sha(directory / 'package-versions.tsv') == PACKAGE_SHA, 'dependency manifest differs'
    subprocess.run(overlay([
        'python3', '-c',
        'import rclpy; from smart_hub_interfaces.msg import HubEvent; '
        'from smart_hub_interfaces.action import DockBus; '
        'from rclpy.type_support import check_for_type_support; '
        'check_for_type_support(HubEvent); check_for_type_support(DockBus); '
        'print("PASS: generated message/action imports and native type support")',
    ]), check=True)
    affected = {'smart_hub_sim', 'smart_hub_control'}
    for path in sorted((repo / 'src').rglob('*')):
        if (not path.is_file() or path.suffix == '.pyc'
                or {'__pycache__', '.pytest_cache'} & set(path.parts)):
            continue
        relative = path.relative_to(repo)
        if relative.parts[1] not in affected:
            assert path.read_bytes() == (Path('/cache') / relative).read_bytes(), relative
    for name in sorted(affected):
        shutil.copytree(repo / 'src' / name, Path('/cache/src') / name, dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns('__pycache__', '*.pyc', '.pytest_cache'))
    shutil.copytree(repo / 'scripts', '/cache/scripts', dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns('__pycache__', '*.pyc', '.pytest_cache'))
    print('PASS: mounts, pinned dependencies, imports and unchanged prerequisite sources')


def inside(repo, results, mode):
    """Run controls incrementally using the verified mount aliases."""
    directory = results / mode
    if mode == 'controls':
        ledger = Ledger(directory, CONTROL_GATES)
        commands = [
            ('mounts_and_dependencies', [sys.executable, str(Path(__file__).resolve()),
                                         str(results), 'preflight', '--inside']),
            ('incremental_build', ['colcon', 'build', '--packages-select', 'smart_hub_sim',
                                   'smart_hub_control', '--event-handlers', 'console_direct+']),
            ('flake8', ['ament_flake8', 'src/smart_hub_sim', 'src/smart_hub_control',
                        *CHECK_SCRIPTS]),
            ('pep257', ['ament_pep257', 'src/smart_hub_sim', 'src/smart_hub_control',
                        *CHECK_SCRIPTS]),
            ('producer_and_evaluator_controls', [
                'python3', '-m', 'pytest', '-x', '-v',
                'src/smart_hub_sim/test/test_m3_door_evidence.py',
                f'--junitxml={directory}/producer-controls.xml']),
            ('harness_controls', ['python3', '-m', 'pytest', '-x', '-v',
                                  'scripts/test_verification.py',
                                  f'--junitxml={directory}/harness-controls.xml']),
            ('world_and_routing_regressions', [
                'python3', '-m', 'pytest', '-x', '-v',
                'src/smart_hub_sim/test/test_m2_world.py',
                'src/smart_hub_control/test/test_m3_routing.py',
                f'--junitxml={directory}/regressions.xml']),
        ]
        try:
            for name, command in commands:
                cwd = repo if name == 'mounts_and_dependencies' else Path('/cache')
                if name not in ('mounts_and_dependencies', 'incremental_build'):
                    command = overlay(command)
                ledger.run(name, command, cwd, setup=name == 'mounts_and_dependencies')
        except GateStop:
            pass
        return {'PASS': 0, 'FAIL': 1, 'BLOCKED': 2}[overall_status(ledger.records)]
    if mode == 'preflight':
        preflight(repo, results / 'controls')
        return 0
    raise ValueError(mode)


def host(repo, results, mode):
    """Launch the pinned image with both mounts and preserve the complete attempt."""
    if mode == 'controls':
        results.mkdir(parents=True, exist_ok=False)
        write_json(results / 'attempt.json', {
            'schema': 'smart-mobility-hub/door-validation-resume-v1',
            'started_utc': utc(), 'image_id': IMAGE, 'expected_package_sha256': PACKAGE_SHA,
            'revision': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=repo,
                                                text=True).strip(),
            'worktree': subprocess.check_output(['git', 'status', '--porcelain'], cwd=repo,
                                                text=True),
            'automatic_retries': 0,
            'gates': {name: 'NOT RUN' for name in
                      ('controls', 'comparison', 'adoption', 'clean_M2_M3_M4')},
        })
        (results / 'source-sha256.txt').write_text(source_manifest(repo))
        with (results / 'source.patch').open('w') as output:
            subprocess.run(['git', 'diff', 'HEAD'], cwd=repo, stdout=output, check=True)
    attempt_path = results / 'attempt.json'
    attempt = json.loads(attempt_path.read_text())
    directory = results / mode
    directory.mkdir(exist_ok=False)
    ledger = Ledger(directory, ['host_preflight', 'container'], filename='host-gates.json')
    container_name = 'smh-door-' + str(os.getpid())
    command = [
        'docker', 'run', '--rm', '--init', '--name', container_name,
        '--user', f'{os.getuid()}:{os.getgid()}', '-e', 'HOME=/tmp',
        '-e', 'ROS_DOMAIN_ID=73', '-e', 'ROS_LOCALHOST_ONLY=1',
        '--mount', f'type=bind,src={repo},dst=/workspace',
        '--mount', f'type=bind,src={repo / CACHE},dst=/cache', '-w', '/workspace', IMAGE,
    ]
    container_results = Path('/workspace') / results.relative_to(repo)
    if mode == 'comparison':
        command += overlay(['python3', 'scripts/verify_m3.py', '--door-comparison',
                            '--output', str(container_results / mode / 'mission/acceptance.json')])
    else:
        command += ['bash', 'scripts/door_measurement_container.sh', str(container_results), mode]

    def docker_signal(signum, deadline):
        try:
            subprocess.run(['docker', 'kill', '--signal', signum, container_name],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           timeout=max(0.01, min(1.0, deadline - time.monotonic())), check=False)
        except subprocess.TimeoutExpired:
            pass

    started = time.monotonic()
    try:
        if mode == 'comparison':
            assert attempt['gates']['controls'] == 'PASS', 'controls did not pass'
            assert attempt['gates']['comparison'] == 'NOT RUN', 'comparison already attempted'
            assert source_manifest(repo) == (results / 'source-sha256.txt').read_text(), \
                'source changed after controls'
        ledger.run('host_preflight', ['docker', 'image', 'inspect', IMAGE], repo, setup=True)
        bounded = None
        if mode == 'comparison':
            bounded = {
                'total_seconds': 240.0, 'cleanup_seconds': 20.0,
                'interrupt': lambda deadline: docker_signal('INT', deadline),
                'kill': lambda deadline: docker_signal('KILL', deadline),
            }
        ledger.run('container', command, repo, bounded=bounded)
    except GateStop:
        pass
    except (Exception, KeyboardInterrupt) as error:
        ledger.records[0].update(status='BLOCKED', error=repr(error))
        write_json(ledger.path, ledger.records)
    finally:
        status = overall_status(ledger.records)
        attempt['gates'][mode] = status
        attempt[mode] = {'ended_utc': utc(), 'elapsed_sec': time.monotonic() - started,
                         'status': status, 'command': command}
        attempt['status'] = status
        write_json(attempt_path, attempt)
        artifact_manifest(results)
    return {'PASS': 0, 'FAIL': 1, 'BLOCKED': 2}[status]


def main():
    """Require a fresh run directory for controls and the same directory for comparison."""
    parser = argparse.ArgumentParser()
    parser.add_argument('results', type=Path)
    parser.add_argument('mode', choices=('controls', 'comparison', 'preflight'))
    parser.add_argument('--inside', action='store_true')
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    results = args.results.resolve()
    results.relative_to(repo)
    if args.inside:
        return inside(repo, results, args.mode)
    if args.mode == 'preflight':
        parser.error('preflight is an internal gate')
    return host(repo, results, args.mode)


if __name__ == '__main__':
    raise SystemExit(main())
