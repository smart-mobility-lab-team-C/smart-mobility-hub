#!/usr/bin/env python3
"""Audit a direct-upload submission manifest for file and size limits."""

import argparse
import json
from pathlib import Path


def audit(paths):
    """Require at most ten regular direct files, each no larger than one GB."""
    files = []
    problems = []
    if len(paths) > 10:
        problems.append('more than ten upload files')
    if len(set(paths)) != len(paths):
        problems.append('duplicate upload path')
    for supplied in paths:
        if supplied.startswith(('http://', 'https://')):
            problems.append('external link is not a direct upload: ' + supplied)
            continue
        path = Path(supplied)
        if path.is_symlink() or not path.is_file():
            problems.append('not a regular direct file: ' + supplied)
            continue
        size = path.stat().st_size
        if size > 1_000_000_000:
            problems.append('file exceeds one GB: ' + supplied)
        files.append({'path': str(path.resolve()), 'size_bytes': size})
    return {'status': 'PASS' if not problems else 'FAIL',
            'file_count': len(files), 'files': files, 'problems': problems}


def main():
    """Print machine-readable submission audit and fail on a violated limit."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('files', nargs='+')
    args = parser.parse_args()
    result = audit(args.files)
    print(json.dumps(result, indent=2, sort_keys=True))
    raise SystemExit(0 if result['status'] == 'PASS' else 1)


if __name__ == '__main__':
    main()
