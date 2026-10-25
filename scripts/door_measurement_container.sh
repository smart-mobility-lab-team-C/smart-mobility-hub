#!/usr/bin/env bash
# Internal entry point; the host launcher owns mounts, evidence and the outer deadline.
set -eo pipefail
source /opt/ros/jazzy/setup.bash
cd /workspace
exec python3 scripts/door_measurement.py "${1:?evidence directory required}" \
  "${2:?mode required}" --inside
