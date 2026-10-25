#!/usr/bin/env bash
# Drive one real verifier case with RViz markers, for screen recording.
# Usage: bash scripts/demo_scenario.sh [CASE]   (default nominal_escort_01)
#   Good cases: nominal_escort_01, blocked_edge_detour, cancel_while_moving,
#               no_route_then_restore, readiness_timeout, frozen_robot_odometry
# In a second terminal first:  ROS_DOMAIN_ID=42 bash scripts/rviz_demo.sh
set -euo pipefail
CASE="${1:-nominal_escort_01}"
RUN=".cache/demo/$(date +%Y%m%dT%H%M%S)-$CASE"
mkdir -p .cache/demo
exec docker run --rm --net=host --user "$(id -u):$(id -g)" -e HOME=/tmp -e ROS_DOMAIN_ID=42 \
  -v "$PWD:/workspace" -w /workspace/scripts smh-m4-local bash -lc "
    source ../.cache/m2fix-install/setup.bash
    ros2 run smart_hub_bringup dashboard_marker_publisher >/dev/null 2>&1 &
    python3 verify_m6.py --nominal-runs 1 --case $CASE --output ../$RUN/result.json
  "
