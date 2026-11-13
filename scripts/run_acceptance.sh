#!/usr/bin/env bash
# Run every real-node verifier once on the current, clean commit (one acceptance run).
#
#   bash scripts/run_acceptance.sh <run-name>      e.g. run1, run2
#
# Requires a built workspace in .cache/install (see README "Build and test") and an idle
# host. Reports go to evidence/acceptance/<commit>/<run-name>/; raw traces stay in
# .cache/acceptance/ (git-ignored). Every verifier runs even if an earlier one fails, and
# each exit status is recorded; nothing here turns FAIL or BLOCKED into PASS.
set -u
run=${1:?usage: run_acceptance.sh <run-name>}
root=$(cd "$(dirname "$0")/.." && pwd)
cd "$root"
if [ -n "$(git status --porcelain)" ]; then
  echo "refusing: worktree is not clean; acceptance evidence must name one commit" >&2
  exit 2
fi
commit=$(git rev-parse --short=7 HEAD)
raw="$root/.cache/acceptance/$commit/$run"
out="$root/evidence/acceptance/$commit/$run"
if [ -e "$raw" ] || [ -e "$out" ]; then
  echo "refusing: $run already exists for $commit" >&2
  exit 2
fi
mkdir -p "$raw" "$out"
# Use the system Python that ROS Jazzy was built for, not a user environment.
export PATH=/usr/bin:/bin
export ROS_DOMAIN_ID=${ROS_DOMAIN_ID:-84}
# shellcheck disable=SC1091
source /opt/ros/jazzy/setup.bash
# shellcheck disable=SC1091
source "$root/.cache/install/setup.bash"

python3 - "$out/manifest.json" "$commit" "$run" <<'EOF'
import hashlib, json, os, platform, subprocess, sys, time
path, commit, run = sys.argv[1:]
def sh(*cmd):
    return subprocess.run(cmd, capture_output=True, text=True).stdout.strip()
model = 'src/smart_hub_prediction/models/ridge.json'
json.dump({
    'schema': 'smart-mobility-hub/acceptance-manifest-v1', 'run': run,
    'commit': sh('git', 'rev-parse', 'HEAD'), 'started_unix': time.time(),
    'host_cpus': os.cpu_count(), 'load_average': os.getloadavg(),
    'kernel': platform.release(), 'python': platform.python_version(),
    'ros_distro': os.environ.get('ROS_DISTRO'), 'rmw': os.environ.get('RMW_IMPLEMENTATION', 'default'),
    'ros_domain_id': os.environ.get('ROS_DOMAIN_ID'),
    'environment': 'native Ubuntu 24.04 + ROS 2 Jazzy (/opt/ros/jazzy), colcon symlink install in .cache/install',
    'model_sha256': hashlib.sha256(open(model, 'rb').read()).hexdigest(),
}, open(path, 'w'), indent=2)
EOF

status=0
cd "$root/scripts"
for name in m2 m3 m4 m6 s1 s2 s8 s9; do
  started=$(date +%s)
  python3 "verify_$name.py" --output "$raw/$name.json" > "$raw/$name.log" 2>&1
  code=$?
  [ $code -ne 0 ] && status=1
  cp "$raw/$name.json" "$out/$name.json" 2>/dev/null || echo "{\"status\": \"BLOCKED\", \"error\": \"no report\"}" > "$out/$name.json"
  echo "{\"verifier\": \"$name\", \"exit_code\": $code, \"seconds\": $(( $(date +%s) - started ))}" | tee -a "$out/exit-codes.jsonl"
done
exit $status
