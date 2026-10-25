#!/usr/bin/env python3
"""Run one ordered door-validation attempt with pinned mounts and durable evidence."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import time

from verification import cleanup_error, overall_status, run_bounded

IMAGE = 'sha256:f1c8db36f4874670d2125e3e40be69491da12273b28d4effb4f4d3c8b98a839b'
PACKAGE_SHA = '437ad4c24291a444fb81f3ae26ae2cd93f59bdf4907e610e2fc46aa64d092259'
CACHE = '.cache/m4-completion-v1'
AFFECTED = {'smart_hub_sim', 'smart_hub_control'}
DISPOSABLE = {'__pycache__', '.pytest_cache', '.mypy_cache', '.ruff_cache'}
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


def tree_manifest(directory, metadata=False):
    """Fingerprint content, links and executable bits without transient Python caches."""
    records = []
    for path in [directory, *sorted(directory.rglob('*'))]:
        if not metadata and (DISPOSABLE & set(path.parts) or path.suffix in ('.pyc', '.pyo')):
            continue
        info = path.lstat()
        value = (os.readlink(path) if path.is_symlink() else
                 sha(path) if path.is_file() else 'directory')
        record = {'path': str(path.relative_to(directory)), 'value': value,
                  'mode': stat.S_IMODE(info.st_mode) if metadata else info.st_mode & 0o111}
        if metadata:
            record.update(uid=info.st_uid, gid=info.st_gid, mtime_ns=info.st_mtime_ns)
        records.append(record)
    return records


def copy_owned(source, destination):
    """Create writable user-owned copies, retaining data and executable permissions only."""
    if source.is_symlink():
        target = os.readlink(source)
        if os.path.isabs(target):
            raise ValueError(f'absolute cache symlink: {source}')
        destination.symlink_to(target)
    elif source.is_dir():
        destination.mkdir()
        for child in sorted(source.iterdir()):
            if child.name not in DISPOSABLE | {'log', 'logs'} and child.suffix not in (
                    '.pyc', '.pyo', '.log'):
                copy_owned(child, destination / child.name)
    else:
        mode = 0o666 | (source.stat().st_mode & 0o111)
        descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
        with os.fdopen(descriptor, 'wb') as target, source.open('rb') as original:
            shutil.copyfileobj(original, target)


def writable_tree(directory, recursive=True):
    """Check effective access and exercise create/replace/delete in each directory."""
    paths = [directory, *sorted(directory.rglob('*'))] if recursive else [directory]
    for path in paths:
        if path.is_symlink():
            path.resolve().relative_to(directory.resolve())
        mode = os.W_OK | (os.X_OK if path.is_dir() else 0)
        if not os.access(path, mode, effective_ids=True):
            raise PermissionError(f'not effectively writable: {path}')
    count = 0
    for path in paths:
        if path.is_dir() and not path.is_symlink():
            with tempfile.TemporaryDirectory(prefix='.door-write-probe-', dir=path) as temporary:
                first, second = Path(temporary) / 'first', Path(temporary) / 'second'
                first.write_text('create')
                second.write_text('replace')
                first.replace(second)
                second.unlink()
            count += 1
    print(f'PASS: effective access and create/replace/delete probes in {count} directories')


def selected_cache(repo, attempt):
    """Resolve only the dedicated workspace recorded for this attempt."""
    cache = repo / attempt['cache_relative']
    cache.resolve().relative_to((repo / '.cache/door-validation').resolve())
    assert not cache.is_symlink(), 'cache root must not be a symlink'
    return cache


def prepare_cache(repo, results):
    """Copy prerequisites as the normal user and discard only affected build outputs."""
    assert os.geteuid() != 0, 'cache preparation must run as the normal user'
    attempt = json.loads((results / 'attempt.json').read_text())
    source, cache = repo / CACHE, selected_cache(repo, attempt)
    assert not cache.exists(), 'dedicated cache already exists'
    original = tree_manifest(source, metadata=True)
    write_json(results / 'original-cache-before.json', original)
    try:
        cache.parent.mkdir(parents=True, exist_ok=True)
        writable_tree(cache.parent, recursive=False)
        for path in source.rglob('*'):
            if path.is_symlink():
                path.resolve().relative_to(source.resolve())
        copy_owned(source, cache)
        for root in ('build', 'install'):
            for name in sorted(AFFECTED):
                path = cache / root / name
                if path.exists():
                    shutil.rmtree(path)
        writable_tree(cache)
        write_json(results / 'prepared-cache.json', tree_manifest(cache))
        attempt['mount_identity'] = {
            name: [path.stat().st_dev, path.stat().st_ino]
            for name, path in (('repo', repo), ('cache', cache))}
        write_json(results / 'attempt.json', attempt)
    finally:
        after = tree_manifest(source, metadata=True)
        write_json(results / 'original-cache-after.json', after)
        assert original == after, 'original cache changed during preparation'


def installation_manifest(cache):
    """Identify the exact tested sources, harness and installed artifacts."""
    return {root: tree_manifest(cache / root) for root in ('src', 'scripts', 'install')}


def verify_workspace(repo, results, fingerprint=False):
    """Require the committed source and exact installation used by the controls."""
    attempt = json.loads((results / 'attempt.json').read_text())
    cache = selected_cache(repo, attempt)
    assert source_manifest(repo) == (results / 'source-sha256.txt').read_text(), \
        'source changed after controls'
    assert subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=repo,
                                   text=True).strip() == attempt['revision'], 'revision changed'
    assert not subprocess.check_output(['git', 'status', '--porcelain'], cwd=repo), \
        'dirty worktree'
    for name, path in (('repo', repo), ('cache', cache)):
        assert [path.stat().st_dev, path.stat().st_ino] == attempt['mount_identity'][name], \
            f'{name} mount identity changed'
    manifest = installation_manifest(cache)
    path = results / 'tested-installation.json'
    if fingerprint:
        write_json(path, manifest)
    else:
        assert manifest == json.loads(path.read_text()), 'tested workspace changed'
    print('PASS: committed sources and tested workspace fingerprint')


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

    def run(self, name, command, cwd, setup=False, bounded=None, propagate_blocked=False):
        """Record even command-launch failures and never retry a failed command."""
        record = next(item for item in self.records if item['name'] == name)
        if any(item['status'] in ('FAIL', 'BLOCKED') for item in self.records):
            raise GateStop()
        assert record['status'] == 'NOT RUN', 'gate already attempted'
        record.update(command=command, cwd=str(cwd), started_utc=utc(), status='BLOCKED')
        write_json(self.path, self.records)
        started = time.monotonic()
        try:
            with (self.directory / (name + '.log')).open('w') as output:
                record.update(run_bounded(command, output, cwd=cwd, **(
                    bounded if bounded is not None else {'total_seconds': 1800.0})))
            code = record['exit_code']
            blocked = setup or (propagate_blocked and code == 2)
            record['status'] = 'PASS' if code == 0 else 'BLOCKED' if blocked else 'FAIL'
            if record.get('timed_out') or record.get('interrupted'):
                record['status'] = 'BLOCKED'
            if record.get('cleanup_errors') and record['status'] == 'PASS':
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


def preflight(repo, results, comparison=False):
    """Validate aliases, dependencies, prerequisites and imports before any build."""
    assert repo == Path('/workspace'), 'repository must be mounted at /workspace'
    assert os.path.ismount(repo) and os.path.ismount('/cache'), 'required bind mount missing'
    attempt = json.loads((results / 'attempt.json').read_text())
    cache = selected_cache(repo, attempt)
    assert os.path.samefile(cache, '/cache'), 'cache alias is not the selected workspace'
    for name, path in (('repo', repo), ('cache', cache)):
        assert [path.stat().st_dev, path.stat().st_ino] == attempt['mount_identity'][name], \
            f'{name} mount identity differs'
    directory = results / ('comparison' if comparison else 'controls')
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
    prerequisites = {}
    for path in sorted((repo / 'src').iterdir()):
        if path.is_dir() and path.name not in AFFECTED:
            expected = tree_manifest(path)
            assert expected == tree_manifest(cache / 'src' / path.name), path.name
            prerequisites[path.name] = expected
    write_json(directory / 'prerequisite-source-hashes.json', prerequisites)
    writable_tree(cache)
    writable_tree(directory)
    if not comparison:
        for name in sorted(AFFECTED):
            shutil.copytree(repo / 'src' / name, cache / 'src' / name, dirs_exist_ok=True,
                            ignore=shutil.ignore_patterns('__pycache__', '*.pyc', '.pytest_cache'))
        shutil.copytree(repo / 'scripts', cache / 'scripts', dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns('__pycache__', '*.pyc', '.pytest_cache'))
        writable_tree(cache)
    else:
        assert installation_manifest(cache) == json.loads(
            (results / 'tested-installation.json').read_text()), 'tested installation changed'
    print('PASS: mounts, dependencies, imports, prerequisites and effective write access')


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
        preflight(repo, results)
        return 0
    if mode == 'comparison':
        ledger = Ledger(directory, ['mounts_and_dependencies', 'mission'])
        try:
            command = [sys.executable, str(Path(__file__).resolve()), str(results),
                       'comparison-preflight', '--inside']
            ledger.run('mounts_and_dependencies', command, repo, setup=True)
            command = overlay(['python3', 'scripts/verify_m3.py', '--door-comparison',
                               '--output', str(directory / 'mission/acceptance.json')])
            ledger.run('mission', command, repo, propagate_blocked=True)
        except GateStop:
            pass
        return {'PASS': 0, 'FAIL': 1, 'BLOCKED': 2}[overall_status(ledger.records)]
    if mode == 'comparison-preflight':
        preflight(repo, results, comparison=True)
        return 0
    raise ValueError(mode)


def host(repo, results, mode):
    """Launch once with a dedicated cache and retain evidence even on setup failure."""
    started = time.monotonic()
    started_utc = utc()
    deadline = started + 240.0 if mode == 'comparison' else None
    if mode == 'controls':
        results.mkdir(parents=True, exist_ok=False)
        cache = repo / '.cache/door-validation' / results.name
        write_json(results / 'attempt.json', {
            'schema': 'smart-mobility-hub/door-validation-isolated-v1',
            'started_utc': started_utc, 'image_id': IMAGE,
            'expected_package_sha256': PACKAGE_SHA,
            'revision': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=repo,
                                                text=True).strip(),
            'worktree': subprocess.check_output(['git', 'status', '--porcelain'], cwd=repo,
                                                text=True),
            'cache_path': str(cache), 'cache_relative': str(cache.relative_to(repo)),
            'original_cache_path': str(repo / CACHE), 'automatic_retries': 0,
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
    gates = CONTROL_GATES if mode == 'controls' else ['mounts_and_dependencies', 'mission']
    Ledger(directory, gates)
    preparation = 'cache_preparation' if mode == 'controls' else 'workspace_integrity'
    names = ['host_preflight', preparation, 'container']
    if mode == 'controls':
        names.append('installation_fingerprint')
    ledger = Ledger(directory, names, filename='host-gates.json')
    container_name = 'smh-door-' + str(os.getpid())
    cache = selected_cache(repo, attempt)
    command = [
        'docker', 'run', '--rm', '--init', '--name', container_name,
        '--user', f'{os.getuid()}:{os.getgid()}', '-e', 'HOME=/tmp',
        '-e', 'ROS_DOMAIN_ID=73', '-e', 'ROS_LOCALHOST_ONLY=1',
        '--mount', f'type=bind,src={repo},dst=/workspace',
        '--mount', f'type=bind,src={cache},dst=/cache', '-w', '/workspace', IMAGE,
        'bash', 'scripts/door_measurement_container.sh',
        str(Path('/workspace') / results.relative_to(repo)), mode,
    ]

    def docker_signal(signum, limit):
        result = subprocess.run(
            ['docker', 'kill', '--signal', signum, container_name],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            timeout=max(0.01, min(1.0, limit - time.monotonic())), check=False)
        if result.returncode and 'No such container' not in result.stderr:
            raise RuntimeError(result.stderr)

    bounded = {'deadline': deadline} if deadline is not None else None
    try:
        ledger.run('host_preflight', [sys.executable, str(Path(__file__).resolve()),
                                      str(results), 'host-preflight', '--stage', mode],
                   repo, setup=True, bounded=bounded)
        stage = 'prepare-cache' if mode == 'controls' else 'verify-workspace'
        ledger.run(names[1], [sys.executable, str(Path(__file__).resolve()), str(results), stage],
                   repo, setup=True, bounded=bounded)
        container_bounds = {
            'total_seconds': 240.0 if mode == 'comparison' else 1800.0,
            'cleanup_seconds': 20.0, 'deadline': deadline,
            'interrupt': lambda limit: docker_signal('INT', limit),
            'kill': lambda limit: docker_signal('KILL', limit),
        }
        ledger.run('container', command, repo, bounded=container_bounds, propagate_blocked=True)
        if mode == 'controls':
            ledger.run('installation_fingerprint', [sys.executable, str(Path(__file__).resolve()),
                                                    str(results), 'fingerprint'], repo, setup=True)
    except GateStop:
        pass
    finally:
        status = overall_status(ledger.records)
        attempt = json.loads(attempt_path.read_text())
        record = {'started_utc': started_utc, 'status': status, 'command': command}
        try:
            if mode == 'controls' and (cache / 'log').exists():
                shutil.copytree(cache / 'log', directory / 'colcon-log', symlinks=True)
        except Exception as error:
            cleanup_error(record, 'retain_colcon_logs', error)
        attempt['gates'][mode] = record['status']
        record.update(ended_utc=utc(), elapsed_sec=time.monotonic() - started)
        if deadline is not None:
            record.update(total_limit_sec=240.0, cleanup_reserve_sec=20.0)
        attempt[mode] = record
        attempt['status'] = record['status']
        write_json(attempt_path, attempt)
        artifact_manifest(directory)
        artifact_manifest(results)
    return {'PASS': 0, 'FAIL': 1, 'BLOCKED': 2}[attempt['status']]


def host_preflight(repo, results, stage):
    """Check pinned image, clean revision and prior gates within the outer deadline."""
    attempt = json.loads((results / 'attempt.json').read_text())
    assert os.geteuid() != 0, 'validation must run as the normal user'
    assert not attempt['worktree'], 'controls require a committed clean worktree'
    assert attempt['gates'][stage] == 'NOT RUN', 'stage already attempted'
    if stage == 'comparison':
        assert attempt['gates']['controls'] == 'PASS', 'controls did not pass'
    subprocess.run(['docker', 'image', 'inspect', IMAGE], check=True)


def main():
    """Require a fresh run directory for controls and the same directory for comparison."""
    parser = argparse.ArgumentParser()
    parser.add_argument('results', type=Path)
    parser.add_argument('mode', choices=(
        'controls', 'comparison', 'preflight', 'comparison-preflight',
        'prepare-cache', 'verify-workspace', 'fingerprint', 'host-preflight'))
    parser.add_argument('--stage', choices=('controls', 'comparison'))
    parser.add_argument('--inside', action='store_true')
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    results = args.results.resolve()
    results.relative_to(repo)
    if args.inside:
        return inside(repo, results, args.mode)
    if args.mode == 'prepare-cache':
        prepare_cache(repo, results)
        return 0
    if args.mode in ('verify-workspace', 'fingerprint'):
        verify_workspace(repo, results, fingerprint=args.mode == 'fingerprint')
        return 0
    if args.mode == 'host-preflight':
        host_preflight(repo, results, args.stage)
        return 0
    if args.mode not in ('controls', 'comparison'):
        parser.error('preflight is an internal container gate')
    return host(repo, results, args.mode)


if __name__ == '__main__':
    raise SystemExit(main())
