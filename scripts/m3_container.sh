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
mkdir -p "$results/gate-logs"
gates=(smoke m1_check style operator_controls fresh_build installed_fingerprint
       overlay_check interface_check package_tests evaluator_controls harness_controls reference_hashes
       m2 m3)
if [ "${SMH_VERIFY_M4:-0}" = 1 ]; then
  gates+=(m4_style m4 m4_plot)
fi
python3 "$repo/scripts/m234_gate.py" "$results" init "${gates[@]}"
run_gate() {
  local name=$1
  local result
  shift
  python3 "$repo/scripts/m234_gate.py" "$results" start "$name" "$@"
  if "$@" 2>&1 | tee "$results/gate-logs/$name.log"; then
    result=0
  else
    result=$?
  fi
  python3 "$repo/scripts/m234_gate.py" "$results" finish "$name" "$result"
  if [ "$result" -ne 0 ]; then
    exit "$result"
  fi
}
workspace=$(mktemp -d /tmp/smh-m3.XXXXXX)
retain_results() {
  status=$?
  trap - EXIT
  if [ -d "$workspace/log" ]; then
    cp -r "$workspace/log" "$results/colcon-log"
  fi
  printf '%s\n' "$status" > "$results/exit-code.txt"
  python3 "$repo/scripts/m234_gate.py" "$results" finalize "$status"
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
run_gate smoke bash scripts/smoke.sh
run_gate m1_check python3 scripts/check_m1.py
run_gate style bash -c 'ament_flake8 src scripts/check_m1.py scripts/inspect_m1_interfaces.py scripts/verify_m2.py scripts/verify_m3.py scripts/m3_operator_heartbeat.py scripts/test_m3_operator_heartbeat.py scripts/door_duration.py scripts/verification.py scripts/door_measurement.py scripts/test_verification.py scripts/m234_gate.py && ament_pep257 src scripts/check_m1.py scripts/inspect_m1_interfaces.py scripts/verify_m2.py scripts/verify_m3.py scripts/m3_operator_heartbeat.py scripts/test_m3_operator_heartbeat.py scripts/door_duration.py scripts/verification.py scripts/door_measurement.py scripts/test_verification.py scripts/m234_gate.py'
run_gate operator_controls python3 scripts/test_m3_operator_heartbeat.py
run_gate fresh_build colcon build --event-handlers console_direct+
run_gate installed_fingerprint python3 scripts/m234_gate.py "$results" fingerprint "$workspace/install"
run_gate overlay_check bash -c 'source install/setup.bash'
set +u
source install/setup.bash
set -u
run_gate interface_check python3 scripts/inspect_m1_interfaces.py
run_gate package_tests bash -c 'test_status=0; colcon test --event-handlers console_direct+ --return-code-on-test-failure || test_status=$?; colcon test-result --verbose || test_status=$?; exit "$test_status"'
run_gate evaluator_controls python3 -m pytest -x -v src/smart_hub_sim/test/test_m3_door_evidence.py
run_gate harness_controls python3 -m pytest -x -v scripts/test_verification.py
run_gate reference_hashes sha256sum src/smart_hub_sim/config/map_m1.yaml docs/contracts/m1-fields.json
export ROS_DOMAIN_ID=72
export ROS_LOCALHOST_ONLY=1
if [ "${SMH_M4_ONLY:-0}" = 1 ]; then
  if [ "${SMH_VERIFY_M4:-0}" != 1 ]; then
    echo 'M4-only scope requires the M4 runner.' >&2
    exit 2
  fi
  printf '%s\n' '{"scope":"M4 T07-T10 only","m2":"NOT RUN","m3":"NOT RUN"}' \
    > "$results/scope.json"
  echo 'SCOPE: M4 T07-T10 only; M2/M3 regressions NOT RUN in this invocation.'
else
  run_gate m2 python3 scripts/verify_m2.py --output "$results/m2-regression.json"
  export ROS_DOMAIN_ID=73
  run_gate m3 python3 scripts/verify_m3.py --output "$results/m3/acceptance.json"
fi

if [ "${SMH_VERIFY_M4:-0}" = 1 ]; then
  run_gate m4_style bash -c 'ament_flake8 scripts/verify_m4.py scripts/plot_m4.py && ament_pep257 scripts/verify_m4.py scripts/plot_m4.py'
  export ROS_DOMAIN_ID=74
  run_gate m4 python3 scripts/verify_m4.py --output "$results/m4/acceptance.json"
  run_gate m4_plot python3 scripts/plot_m4.py "$results/m4/trace.jsonl" "$results/m4/measurements.png"
fi
