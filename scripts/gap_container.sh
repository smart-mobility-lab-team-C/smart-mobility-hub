#!/usr/bin/env bash
# Diagnostic build and runtime; never used to establish milestone acceptance.
set -euo pipefail
set +u
source /opt/ros/jazzy/setup.bash
set -u
results=${1:?absolute results directory required}
runs=${2:-10}
seconds=${3:-1200}
repo=$(pwd)
workspace=$(mktemp -d /tmp/smh-gap.XXXXXX)
sampler=''
cleanup() {
  status=$?
  trap - EXIT
  if [ -n "$sampler" ]; then
    kill -TERM "$sampler" 2>/dev/null || true
    wait "$sampler" || true
  fi
  printf '%s\n' "$status" > "$results/container-exit-code.txt"
  rm -rf "$workspace"
  exit "$status"
}
trap cleanup EXIT
cp -r src scripts "$workspace/"
cat /etc/os-release > "$results/container-os.txt"
python3 --version > "$results/python-version.txt"
printenv ROS_DISTRO > "$results/ros-distro.txt"
dpkg-query -W > "$results/package-versions.tsv"
cd "$workspace"
colcon build --event-handlers console_direct+ > "$results/build.log" 2>&1
set +u
source install/setup.bash
set -u
export ROS_DOMAIN_ID=74 ROS_LOCALHOST_ONLY=1
python3 scripts/gap_tools.py sample --layer container --output "$results/container.jsonl" \
  --registry "$results/pids.jsonl" &
sampler=$!
extra=()
if [ -n "${4:-}" ]; then
  extra=(--pause-node "$4")
fi
python3 scripts/diagnose_m3_gap.py --output "$results" --runs "$runs" --seconds "$seconds" \
  "${extra[@]}"
