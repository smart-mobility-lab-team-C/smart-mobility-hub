#!/usr/bin/env bash
# Validate controls before allowing one bounded comparison in the pinned workspace.
set -eo pipefail
source /opt/ros/jazzy/setup.bash
repo=$(pwd)
cached="$repo/.cache/m4-completion-v1"
results=${1:?absolute unique evidence directory required}
mode=${2:?controls or comparison required}
test "$mode" = controls || test "$mode" = comparison
mkdir -p "$results"
test ! -e "$results/$mode.log"
exec > >(tee "$results/$mode.log") 2>&1
dpkg-query -W > "$results/$mode-package-versions.tsv"
test "$(sha256sum "$results/$mode-package-versions.tsv" | cut -d ' ' -f 1)" = \
  437ad4c24291a444fb81f3ae26ae2cd93f59bdf4907e610e2fc46aa64d092259
if [ "$mode" = controls ]; then
  python3 - "$repo" "$cached" "$results" <<'PY'
import hashlib
from pathlib import Path
import shutil
import sys

repo, cached, results = map(Path, sys.argv[1:])
affected = {'smart_hub_sim', 'smart_hub_control'}
for path in sorted((repo / 'src').rglob('*')):
    if not path.is_file() or '__pycache__' in path.parts or '.pytest_cache' in path.parts:
        continue
    relative = path.relative_to(repo)
    if relative.parts[1] not in affected:
        assert path.read_bytes() == (cached / relative).read_bytes(), relative
for package in affected:
    shutil.copytree(repo / 'src' / package, cached / 'src' / package, dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns('__pycache__', '*.pyc', '.pytest_cache'))
shutil.copytree(repo / 'scripts', cached / 'scripts', dirs_exist_ok=True,
                ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
records = []
for root in ('src', 'scripts'):
    for path in sorted((repo / root).rglob('*')):
        if path.is_file() and not {'__pycache__', '.pytest_cache'} & set(path.parts):
            records.append(hashlib.sha256(path.read_bytes()).hexdigest() + '  ' +
                           str(path.relative_to(repo)))
(results / 'controls-source-sha256.txt').write_text('\n'.join(records) + '\n')
PY
  cd "$cached"
  colcon build --packages-select smart_hub_sim smart_hub_control --event-handlers console_direct+
  source install/setup.bash
  ament_flake8 src/smart_hub_sim src/smart_hub_control \
    scripts/door_duration.py scripts/verify_m3.py
  ament_pep257 src/smart_hub_sim src/smart_hub_control \
    scripts/door_duration.py scripts/verify_m3.py
  python3 -m pytest src/smart_hub_sim/test/test_m3_door_evidence.py \
    src/smart_hub_sim/test/test_m2_world.py src/smart_hub_control/test/test_m3_routing.py \
    -v --junitxml="$results/controls.xml"
  touch "$results/controls-passed"
else
  test -e "$results/controls-passed"
  sha256sum --check --quiet "$results/controls-source-sha256.txt"
  source "$cached/install/setup.bash"
  export ROS_DOMAIN_ID=73 ROS_LOCALHOST_ONLY=1
  timeout --signal=INT --kill-after=20s 240s python3 scripts/verify_m3.py \
    --door-comparison --output "$results/comparison/acceptance.json"
fi
