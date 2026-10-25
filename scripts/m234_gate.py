#!/usr/bin/env python3
"""Record ordered clean M2+M3+M4 gates and installed artifact hashes."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import stat
import time


def utc():
    """Return a timestamp with its UTC offset."""
    return datetime.now(timezone.utc).isoformat()


def write(path, value):
    """Persist a complete ledger after each gate transition."""
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, indent=2) + '\n')
    temporary.replace(path)


def fingerprint(directory, output):
    """Hash installed file bytes and record symlink targets and modes."""
    records = []
    for path in sorted(directory.rglob('*')):
        info = path.lstat()
        relative = path.relative_to(directory)
        if path.is_symlink():
            value = 'link:' + os.readlink(path)
        elif path.is_file():
            digest = hashlib.sha256()
            with path.open('rb') as source:
                for chunk in iter(lambda: source.read(1024 * 1024), b''):
                    digest.update(chunk)
            value = digest.hexdigest()
        else:
            continue
        records.append(f'{value}  {stat.S_IMODE(info.st_mode):04o}  {relative}')
    output.write_text('\n'.join(records) + '\n')
    print(f'Fingerprint: {len(records)} installed artifacts in {output}', flush=True)


def main():
    """Initialize, update, and finish a fail-fast pipeline ledger."""
    parser = argparse.ArgumentParser()
    parser.add_argument('results', type=Path)
    parser.add_argument('action', choices=('init', 'start', 'finish', 'fingerprint', 'finalize'))
    parser.add_argument('args', nargs=argparse.REMAINDER)
    options = parser.parse_args()
    path = options.results / 'gates.json'
    if options.action == 'init':
        write(path, {'schema': 'smart-mobility-hub/m234-gates-v1',
                     'started_utc': utc(), 'started_monotonic': time.monotonic(),
                     'gates': [{'name': name, 'status': 'NOT RUN'} for name in options.args]})
        return
    data = json.loads(path.read_text())
    if options.action == 'fingerprint':
        fingerprint(Path(options.args[0]), options.results / 'installed-sha256.txt')
        return
    if options.action == 'finalize':
        data['ended_utc'] = utc()
        data['elapsed_sec'] = time.monotonic() - data['started_monotonic']
        data['exit_code'] = int(options.args[0])
        statuses = [item['status'] for item in data['gates']
                    if os.environ.get('SMH_M4_ONLY') != '1'
                    or item['name'] not in ('m2', 'm3')]
        data['status'] = next((status for status in statuses
                               if status in ('FAIL', 'BLOCKED')),
                              'PASS' if all(status == 'PASS' for status in statuses)
                              else 'BLOCKED')
    else:
        name = options.args[0]
        record = next(item for item in data['gates'] if item['name'] == name)
        if options.action == 'start':
            assert record['status'] == 'NOT RUN'
            assert not any(item['status'] in ('FAIL', 'BLOCKED')
                           for item in data['gates'])
            record.update(status='BLOCKED', started_utc=utc(),
                          started_monotonic=time.monotonic(),
                          command=options.args[1:], cwd=os.getcwd(),
                          log=f'gate-logs/{name}.log')
        else:
            code = int(options.args[1])
            record.update(exit_code=code, ended_utc=utc(),
                          elapsed_sec=time.monotonic() - record['started_monotonic'],
                          status='PASS' if code == 0 else 'BLOCKED' if code == 2 else 'FAIL')
    write(path, data)


if __name__ == '__main__':
    main()
