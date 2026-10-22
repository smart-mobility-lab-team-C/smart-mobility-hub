#!/usr/bin/env bash
# Run only inside the M0 container; retained output is managed by bootstrap.
set -eo pipefail
source /opt/ros/jazzy/setup.bash
set -u
source /etc/os-release
[[ "$ID" == ubuntu && "$VERSION_ID" == 24.04 && "$ROS_DISTRO" == jazzy ]]
python3 -c 'import rclpy; import sys; print(sys.version); print(rclpy.__file__)'
colcon version-check --help >/dev/null 2>&1 || colcon --help >/dev/null
cat /opt/smh-package-versions.tsv
work=$(mktemp -d)
cleanup() {
  kill "${talker:-}" "${listener:-}" 2>/dev/null || true
  wait "${talker:-}" "${listener:-}" 2>/dev/null || true
  cat "$work/talker.log" "$work/listener.log"
  rm -rf "$work"
}
trap cleanup EXIT
export ROS_DOMAIN_ID=87 ROS_LOCALHOST_ONLY=1
ros2 run demo_nodes_cpp talker >"$work/talker.log" 2>&1 &
talker=$!
ros2 run demo_nodes_py listener >"$work/listener.log" 2>&1 &
listener=$!
for ((i=0; i<30; i++)); do
  kill -0 "$talker" "$listener"
  if grep -q 'I heard:' "$work/listener.log"; then
    echo 'PASS: real ROS talker/listener delivery'
    exit 0
  fi
  sleep 1
done
echo 'FAIL: no listener delivery within 30 seconds' >&2
exit 1
