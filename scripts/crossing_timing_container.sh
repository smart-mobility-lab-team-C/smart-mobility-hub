#!/usr/bin/env bash
# Targeted diagnostic only: reuse generated interfaces, overlay current Python, no rebuild.
set -eo pipefail
source /opt/ros/jazzy/setup.bash
repo=$(pwd)
results=${1:?absolute fresh evidence directory required}
cached_workspace=${2:-$repo/.cache/m4-completion-v1}
mode=${3:---crossing-timing}
case "$mode" in
  --crossing-timing|--event-timing) ;;
  *) echo 'Expected --crossing-timing or --event-timing' >&2; exit 2 ;;
esac
test ! -e "$results/mission"
mkdir -p "$results"
source "$cached_workspace/install/setup.bash"
for package in "$repo"/src/*; do
  if [ -f "$package/$(basename "$package")/__init__.py" ]; then
    export PYTHONPATH="$package:${PYTHONPATH:-}"
  fi
done
python3 - "$repo" "$cached_workspace" "$results" <<'PY'
import hashlib
import importlib
import json
from pathlib import Path
import sys
from ament_index_python.packages import get_package_share_directory

repo, cached, output = map(Path, sys.argv[1:])
source = repo / 'src/smart_hub_interfaces'
old = cached / 'src/smart_hub_interfaces'
definitions = {p.relative_to(source) for p in source.rglob('*')
               if p.suffix in ('.msg', '.srv', '.action')}
assert definitions == {p.relative_to(old) for p in old.rglob('*')
                       if p.suffix in ('.msg', '.srv', '.action')}
assert all((source / p).read_bytes() == (old / p).read_bytes() for p in definitions)
installed_map = Path(get_package_share_directory('smart_hub_sim')) / 'config/map_m1.yaml'
assert installed_map.read_bytes() == (repo / 'src/smart_hub_sim/config/map_m1.yaml').read_bytes()
records = {'scope': 'one M3 diagnostic; no acceptance; no build', 'modules': {}}
for name in ('smart_hub_sim.scenario_runner', 'smart_hub_safety.supervisor',
             'smart_hub_control.crossing', 'smart_hub_control.bus',
             'smart_hub_control.routing', 'smart_hub_bringup.reset'):
    path = Path(importlib.import_module(name).__file__).resolve()
    assert path.is_relative_to(repo / 'src'), path
    records['modules'][name] = {'path': str(path),
                              'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
(output / 'reuse-provenance.json').write_text(json.dumps(records, indent=2) + '\n')
PY
git rev-parse HEAD > "$results/commit.txt"
git status --porcelain > "$results/worktree.txt"
git diff > "$results/worktree.patch"
export ROS_DOMAIN_ID=74 ROS_LOCALHOST_ONLY=1
sampler=''
if [ "$mode" != --event-timing ]; then
  python3 scripts/gap_tools.py sample --layer container --output "$results/container.jsonl" \
    --registry "$results/pids.jsonl" &
  sampler=$!
fi
cleanup() {
  status=$?
  trap - EXIT
  if [ -n "$sampler" ]; then
    kill -TERM "$sampler" 2>/dev/null || true
    wait "$sampler" || true
  fi
  printf '%s\n' "$status" > "$results/container-exit-code.txt"
  exit "$status"
}
trap cleanup EXIT
timeout --signal=INT --kill-after=20s 240s python3 scripts/diagnose_m3_gap.py \
  --attempt "$mode" --output "$results/mission"
