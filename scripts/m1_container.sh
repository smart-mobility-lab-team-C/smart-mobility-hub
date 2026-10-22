#!/usr/bin/env bash
# Run inside the Jazzy image as an ordinary user; output directory is caller-owned.
set -euo pipefail
set +u
source /opt/ros/jazzy/setup.bash
set -u
repo=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
results=${1:?Usage: bash scripts/m1_container.sh ABSOLUTE_RESULTS_DIRECTORY}
mkdir -p "$results"
exec > >(tee "$results/transcript.log") 2>&1
workspace=$(mktemp -d /tmp/smh-m1.XXXXXX)
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
cat /etc/os-release
python3 --version
printenv ROS_DISTRO
dpkg-query -W > "$results/package-versions.tsv"
python3 scripts/check_m1.py
ament_flake8 src scripts/check_m1.py scripts/inspect_m1_interfaces.py
ament_pep257 src scripts/check_m1.py scripts/inspect_m1_interfaces.py
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
