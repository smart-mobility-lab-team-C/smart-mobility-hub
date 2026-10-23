#!/usr/bin/env bash
# PC/hosted checks only; a pass does not establish ROS integration.
set -euo pipefail
repo=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
cd "$repo"
python3 --version
python3 - <<'PY'
from pathlib import Path
import subprocess
paths = subprocess.check_output(['git', 'ls-files', '-z']).split(b'\0')
for raw in paths:
    if not raw:
        continue
    path = Path(raw.decode())
    if path.suffix == '.sh':
        subprocess.run(['bash', '-n', str(path)], check=True)
    elif path.suffix == '.py':
        compile(path.read_bytes(), str(path), 'exec')
print('PASS: tracked shell syntax and Python compilation')
PY
python3 -m unittest discover -s tests -v
python3 -m unittest discover -s scripts -p 'test_*.py' -v
python3 scripts/check_m1.py
python3 scripts/check_docs.py
