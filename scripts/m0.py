#!/usr/bin/env python3
"""M0 tooling. Never installs ROS or changes configuration on the host."""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
IMAGE = 'smart-mobility-hub:m0'


def run(args, timeout=20, **kwargs):
    return subprocess.run(args, text=True, capture_output=True, timeout=timeout,
                          check=False, **kwargs)


def os_release():
    return dict(line.split('=', 1) for line in Path('/etc/os-release').read_text()
                .replace('"', '').splitlines() if '=' in line)


def probe(args):
    try:
        result = run(args)
        # Never include command stderr, remotes, environment or credentials.
        return result.returncode == 0, result.stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return False, ''


def diagnose():
    checks = []

    def add(name, ok, detail):
        checks.append(dict(name=name, status='PASS' if ok else 'BLOCKED', detail=detail))

    release = os_release()
    add('host', release.get('ID') == 'ubuntu' and release.get('VERSION_ID') in
        ('22.04', '24.04'), f"{release.get('PRETTY_NAME')}; {platform.machine()}")
    virt = probe(['systemd-detect-virt'])[1] or 'unknown'
    add('virtualization', True, virt)
    add('disk', True, f'{shutil.disk_usage(ROOT).free} bytes free; simulator capacity unverified')
    add('memory', True, Path('/proc/meminfo').read_text().splitlines()[0])
    for binary in ('git', 'docker'):
        add(binary, shutil.which(binary) is not None, 'available' if shutil.which(binary)
            else f'Install {binary}; see docs/m0.md')
    ok, _ = probe(['docker', 'info', '--format', '{{.ServerVersion}}'])
    add('docker_daemon', ok, 'accessible' if ok else 'Docker absent, stopped or inaccessible')
    ok, _ = probe(['git', '-C', str(ROOT), 'rev-parse', '--is-inside-work-tree'])
    add('git_checkout', ok, 'checkout available' if ok else 'No local Git checkout')
    add('git_write_auth', False, 'Not probed: verify by pushing a personal branch; no credentials inspected')
    return {'schema_version': 1, 'checks': checks}


def command(args, log):
    log.write('$ ' + ' '.join(args) + '\n')
    log.flush()
    result = subprocess.run(args, stdout=log, stderr=subprocess.STDOUT, check=False)
    if result.returncode:
        raise RuntimeError(f'{args[0]} failed (exit {result.returncode}); see transcript.log')


def bootstrap(args):
    if args.native:
        print('BLOCKED: native installation is outside M0; Jazzy requires Ubuntu 24.04. '
              'Use the container workflow.', file=sys.stderr)
        return 2
    report = diagnose()
    required = {'host', 'docker', 'docker_daemon'}
    blocked = [c for c in report['checks'] if c['name'] in required and c['status'] != 'PASS']
    if args.check or not args.install:
        print(json.dumps(report, indent=2))
        return 2 if blocked else 0
    if blocked:
        print('BLOCKED: ' + '; '.join(c['detail'] for c in blocked), file=sys.stderr)
        return 2
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    folder = ROOT / 'evidence' / 'runs' / (stamp + '-' + uuid.uuid4().hex[:8])
    folder.mkdir(parents=True, exist_ok=False)
    ok, commit = probe(['git', '-C', str(ROOT), 'rev-parse', 'HEAD'])
    dirty_ok, dirty = probe(['git', '-C', str(ROOT), 'status', '--porcelain'])
    metadata = dict(status='NOT RUN', command=sys.argv[1:], commit=commit if ok else None,
                    dirty=bool(dirty) if dirty_ok else None, host=report,
                    started_at=stamp, image=IMAGE,
                    dockerfile_sha256=hashlib.sha256(
                        (ROOT / 'containers/Dockerfile').read_bytes()).hexdigest())
    result = 1
    try:
        with (folder / 'transcript.log').open('w') as log:
            command(['docker', 'build', '-f', str(ROOT / 'containers/Dockerfile'),
                     '-t', IMAGE, str(ROOT)], log)
            command(['docker', 'image', 'inspect', IMAGE], log)
            command(['docker', 'version'], log)
            command(['docker', 'run', '--rm', '--user', f'{os.getuid()}:{os.getgid()}',
                     '--env', 'HOME=/tmp', '--mount',
                     f'type=bind,source={ROOT},target=/workspace,readonly',
                     IMAGE, 'bash', '/workspace/scripts/smoke.sh'], log)
        metadata['status'] = 'PASS'
        result = 0
    except (OSError, RuntimeError) as error:
        metadata.update(status='FAIL', reason=str(error))
        print(str(error), file=sys.stderr)
    finally:
        metadata['ended_at'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        (folder / 'metadata.json').write_text(json.dumps(metadata, indent=2) + '\n')
        print(f"{metadata['status']}: {folder}")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='operation', required=True)
    doctor = sub.add_parser('doctor')
    doctor.add_argument('--json', action='store_true')
    boot = sub.add_parser('bootstrap')
    mode = boot.add_mutually_exclusive_group()
    mode.add_argument('--check', action='store_true')
    mode.add_argument('--install', action='store_true')
    boot.add_argument('--native', action='store_true')
    args = parser.parse_args()
    if args.operation == 'bootstrap':
        return bootstrap(args)
    report = diagnose()
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        for check in report['checks']:
            print(f"{check['status']}: {check['name']}: {check['detail']}")
    return 2 if any(c['status'] != 'PASS' for c in report['checks']) else 0


if __name__ == '__main__':
    sys.exit(main())
