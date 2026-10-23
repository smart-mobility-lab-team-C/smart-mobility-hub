#!/usr/bin/env bash
# Build in a fresh workspace, preserve M2 regression and execute real M3 missions.
set -euo pipefail
set +u
source /opt/ros/jazzy/setup.bash
set -u
repo=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
results=${1:?Usage: bash scripts/m3_container.sh ABSOLUTE_RESULTS_DIRECTORY}
if [ -e "$results" ]; then
  echo 'Evidence directory already exists; select a unique run ID.' >&2
  exit 2
fi
mkdir -p "$results"
exec > >(tee "$results/transcript.log") 2>&1
workspace=$(mktemp -d /tmp/smh-m3.XXXXXX)
retain_results() {
  status=$?
  trap - EXIT
  if [ -d "$workspace/log" ]; then
    cp -r "$workspace/log" "$results/colcon-log"
  fi
  printf '%s\n' "$status" > "$results/exit-code.txt"
  rm -rf "$workspace"
  exit "$status"
}
trap retain_results EXIT
python3 - "$repo" "$workspace" <<'PY'
from pathlib import Path
import shutil
import sys
source, target = map(Path, sys.argv[1:])
for name in ('src', 'scripts', 'docs'):
    shutil.copytree(source / name, target / name,
                    ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
PY
cd "$workspace"
date -u
id
cat /etc/os-release
python3 --version
printenv ROS_DISTRO
dpkg-query -W > "$results/package-versions.tsv"
git -C "$repo" rev-parse HEAD > "$results/commit.txt"
git -C "$repo" status --porcelain > "$results/worktree.txt"
python3 - "$results" <<'PY'
import hashlib
from pathlib import Path
import sys
records = []
for root in ('src', 'scripts', 'docs'):
    for path in sorted(Path(root).rglob('*')):
        if path.is_file() and '__pycache__' not in path.parts and path.suffix != '.pyc':
            records.append(hashlib.sha256(path.read_bytes()).hexdigest() + '  ' + str(path))
(Path(sys.argv[1]) / 'source-sha256.txt').write_text('\n'.join(records) + '\n')
PY
bash scripts/smoke.sh
python3 scripts/check_m1.py
ament_flake8 src scripts/check_m1.py scripts/inspect_m1_interfaces.py scripts/verify_m2.py scripts/verify_m3.py
ament_pep257 src scripts/check_m1.py scripts/inspect_m1_interfaces.py scripts/verify_m2.py scripts/verify_m3.py
colcon build --event-handlers console_direct+
set +u
source install/setup.bash
set -u
python3 scripts/inspect_m1_interfaces.py
test_status=0
colcon test --event-handlers console_direct+ --return-code-on-test-failure || test_status=$?
colcon test-result --verbose || test_status=$?
if [ "$test_status" -ne 0 ]; then
  exit "$test_status"
fi
sha256sum src/smart_hub_sim/config/map_m1.yaml docs/contracts/m1-fields.json
export ROS_DOMAIN_ID=72
export ROS_LOCALHOST_ONLY=1
python3 scripts/verify_m2.py --output "$results/m2-regression.json"
export ROS_DOMAIN_ID=73
python3 scripts/verify_m3.py --output "$results/m3/acceptance.json"

if [ "${SMH_VERIFY_M4:-0}" = 1 ]; then
  ament_flake8 scripts/verify_m4.py scripts/plot_m4.py
  ament_pep257 scripts/verify_m4.py scripts/plot_m4.py
  export ROS_DOMAIN_ID=74
  python3 scripts/verify_m4.py --output "$results/m4/acceptance.json"
  python3 scripts/plot_m4.py "$results/m4/trace.jsonl" "$results/m4/measurements.png"
fi
