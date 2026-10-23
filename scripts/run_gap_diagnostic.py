#!/usr/bin/env python3
"""Capture independent VM-host timing while running a non-root Jazzy container."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time


def capture(command):
    """Capture exact read-only environment commands with their exit codes."""
    result = subprocess.run(command, capture_output=True, text=True)
    return {'command': command, 'returncode': result.returncode,
            'stdout': result.stdout, 'stderr': result.stderr}


def main():
    """Build once and run at most ten missions or twenty minutes, retaining all failures."""
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True)
    parser.add_argument('--image', default='smh-m3:latest')
    parser.add_argument('--runs', type=int, default=10)
    parser.add_argument('--seconds', type=float, default=1200)
    parser.add_argument('--pause-node', choices=('probe', 'observer', 'scenario_runner'))
    args = parser.parse_args()
    if os.getuid() == 0:
        parser.error('run as the ordinary workspace user')
    if not 1 <= args.runs <= 10 or not 0 < args.seconds <= 1200:
        parser.error('runs must be 1..10 and seconds must be >0 and <=1200')
    repo = Path(__file__).resolve().parents[1]
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    metadata = {'start_wall': time.time(), 'platform': platform.platform(),
                'uname': list(platform.uname()), 'acceptance_eligible': False}
    metadata['environment'] = [capture(command) for command in (
        ['git', 'rev-parse', 'HEAD'], ['git', 'status', '--porcelain'],
        ['docker', 'image', 'inspect', args.image], ['cat', '/etc/os-release'],
        ['systemd-detect-virt'], ['lscpu'])]
    metadata['source_sha256'] = {
        str(path.relative_to(repo)): hashlib.sha256(path.read_bytes()).hexdigest()
        for root in ('src', 'scripts') for path in sorted((repo / root).rglob('*'))
        if path.is_file() and '__pycache__' not in path.parts and path.suffix != '.pyc'
    }
    name = 'smh-gap-' + str(os.getpid())
    command = ['docker', 'run', '--rm', '--name', name,
               '--user', f'{os.getuid()}:{os.getgid()}', '-e', 'HOME=/tmp',
               '-v', f'{repo}:/workspace:ro', '-v', f'{output}:/gap-results',
               args.image, 'bash', 'scripts/gap_container.sh', '/gap-results',
               str(args.runs), str(args.seconds)]
    if args.pause_node:
        command.append(args.pause_node)
    metadata['command'] = command
    sampler = subprocess.Popen([sys.executable, str(repo / 'scripts/gap_tools.py'),
                                'sample', '--layer', 'host',
                                '--output', str(output / 'host.jsonl'),
                                '--registry', str(output / 'host-pids.jsonl')])
    process = None
    try:
        with (output / 'transcript.log').open('w') as log:
            process = subprocess.Popen(command, cwd=repo, stdout=log, stderr=subprocess.STDOUT)
            (output / 'host-pids.jsonl').write_text(json.dumps(
                {'name': 'docker-client', 'pid': process.pid}) + '\n')
            metadata['returncode'] = process.wait()
    except KeyboardInterrupt:
        metadata['interrupted'] = True
    finally:
        if process and process.poll() is None:
            subprocess.run(['docker', 'stop', '--time', '10', name], capture_output=True)
            process.wait(timeout=20)
        sampler.terminate()
        sampler.wait(timeout=5)
        metadata['end_wall'] = time.time()
        (output / 'environment.json').write_text(json.dumps(metadata, indent=2) + '\n')
        hashes = {str(path.relative_to(output)): hashlib.sha256(path.read_bytes()).hexdigest()
                  for path in sorted(output.rglob('*')) if path.is_file()}
        (output / 'artifact-sha256.json').write_text(json.dumps(hashes, indent=2) + '\n')
    print(json.dumps({'output': str(output), 'returncode': metadata.get('returncode')}))
    raise SystemExit(metadata.get('returncode', 130))


if __name__ == '__main__':
    main()
