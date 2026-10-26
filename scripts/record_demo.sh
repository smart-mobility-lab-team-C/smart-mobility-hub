#!/usr/bin/env bash
# Record one real verifier case to MP4 for the team video (demonstration only, no control authority).
# Usage: bash scripts/record_demo.sh [CASE]      (cases as in scripts/demo_scenario.sh)
#        bash scripts/record_demo.sh --render RUN_DIR   (re-render an existing run)
# Build once:  docker build -t smh-rviz -f containers/Dockerfile.rviz .
#              docker build -t smh-record -f containers/Dockerfile.record .
# Phase 1 runs the case with a ROS bag and no rendering, so recording cannot load the run.
# Phase 2 replays the bag into RViz on a virtual 1920x1080 screen and encodes clip.mp4.
# Output in RUN_DIR: result.json, bag/, cues.csv (event times in seconds since bag start), clip.mp4.
set -euo pipefail
DOMAIN=43   # separate from the interactive demo (42) so nothing else sees this traffic

render() {
  local run="$1"
  docker run --rm --network none --user "$(id -u):$(id -g)" -e HOME=/tmp -e ROS_DOMAIN_ID=$DOMAIN \
    -e LIBGL_ALWAYS_SOFTWARE=1 -v "$PWD:/workspace" -w /workspace smh-record bash -lc "
      set -eo pipefail   # no -u: the colcon setup script reads unset variables
      source .cache/m2fix-install/setup.bash
      start_ns=\$(python3 scripts/demo_events.py cues $run/bag $run/cues.csv)
      # Burned-in caption so every clip states its case and verifier outcome.
      python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); print(\"Case\", d[\"only_case\"], \"| verifier result\", d[\"status\"], \"| replay of the recorded run\")' \
        $run/result.json > /tmp/caption.txt
      # RViz on the left 1280x1080 with no Displays panel; event log on the right.
      sed -e 's/^  Width: .*/  Width: 1280/' -e 's/^  Height: .*/  Height: 1080/' \
          -e 's/^  X: .*/  X: 0/' -e 's/^  Y: .*/  Y: 0/' -e 's/^Panels:$/Panels: []/' \
          -e '/^  - Class: rviz_common\/Displays/,/^    Tree Height/d' -e '/QMainWindow State/d' \
          src/smart_hub_bringup/rviz/hub.rviz > /tmp/record.rviz
      Xvfb :99 -screen 0 1920x1080x24 -nolisten tcp >/dev/null 2>&1 &
      export DISPLAY=:99
      sleep 1
      rviz2 -d /tmp/record.rviz >/tmp/rviz.log 2>&1 &
      xterm -geometry 70x56+1280+0 -fa 'DejaVu Sans Mono' -fs 11 -bg black -fg white \
        -e bash -c \"python3 scripts/demo_events.py view \$start_ns 2>/tmp/view.log\" &
      sleep 8
      ffmpeg -loglevel error -f x11grab -video_size 1920x1080 -framerate 30 -draw_mouse 0 -i :99 \
        -vf 'drawtext=fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf:textfile=/tmp/caption.txt:x=24:y=1040:fontsize=24:fontcolor=white:box=1:boxcolor=black@0.7:boxborderw=8' \
        -c:v libx264 -preset veryfast -crf 20 -pix_fmt yuv420p -y $run/clip.mp4 &
      encoder=\$!
      ros2 bag play $run/bag >/dev/null
      sleep 2
      kill -TERM \$encoder
      wait \$encoder || true
    "
  echo "Rendered $run/clip.mp4"
}

if [ "${1:-}" = "--render" ]; then
  render "${2:?usage: record_demo.sh --render RUN_DIR}"
  exit 0
fi

CASE="${1:-nominal_escort_01}"
RUN=".cache/demo/$(date +%Y%m%dT%H%M%S)-$CASE"
mkdir -p "$RUN"
docker run --rm --net=host --user "$(id -u):$(id -g)" -e HOME=/tmp -e ROS_DOMAIN_ID=$DOMAIN \
  -v "$PWD:/workspace" -w /workspace/scripts smh-m4-local bash -lc "
    source ../.cache/m2fix-install/setup.bash
    ros2 run smart_hub_bringup dashboard_marker_publisher >/dev/null 2>&1 &
    ros2 bag record -o ../$RUN/bag /hub/markers /hub/events /hub/safety >/dev/null 2>&1 &
    recorder=\$!
    status=0
    python3 verify_m6.py --nominal-runs 1 --case $CASE --output ../$RUN/result.json || status=\$?
    kill -TERM \$recorder   # background jobs ignore SIGINT in a non-interactive shell
    wait \$recorder || true
    exit \$status
  " || echo "Verifier exited non-zero; see $RUN/result.json. Rendering anyway."
render "$RUN"
