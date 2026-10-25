#!/usr/bin/env bash
# Show RViz for a running scenario (demonstration/recording only, no control authority).
# Build once:  docker build -t smh-rviz -f containers/Dockerfile.rviz .
# Then, with a scenario running in the same ROS_DOMAIN_ID:  bash scripts/rviz_demo.sh
set -euo pipefail
xhost +SI:localuser:"$(id -un)" >/dev/null
exec docker run --rm --user "$(id -u):$(id -g)" -e HOME=/tmp -e DISPLAY="${DISPLAY:-:0}" \
  -e ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-0}" -e QT_X11_NO_MITSHM=1 \
  -v /tmp/.X11-unix:/tmp/.X11-unix:ro -v "$PWD:/workspace" -w /workspace smh-rviz \
  bash -lc 'source /opt/ros/jazzy/setup.bash && rviz2 -d src/smart_hub_bringup/rviz/hub.rviz'
