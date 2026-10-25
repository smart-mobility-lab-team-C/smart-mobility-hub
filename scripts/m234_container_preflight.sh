#!/usr/bin/env bash
# Validate a linked worktree inside the pinned acceptance image without building.
set -euo pipefail

image=smh-m4-local:latest
expected_image_id=sha256:f1c8db36f4874670d2125e3e40be69491da12273b28d4effb4f4d3c8b98a839b

if [[ "${1:-}" == --inside ]]; then
  shift
  if [[ "$#" -ne 3 ]]; then
    echo 'Usage: m234_container_preflight.sh --inside COMMIT BASELINE_SOURCE_MANIFEST PACKAGE_SHA' >&2
    exit 2
  fi
  expected_commit=$1
  baseline_source_manifest=$2
  expected_package_sha=$3
  repo=/workspace

  actual_commit=$(git -C "$repo" rev-parse HEAD)
  if [[ "$actual_commit" != "$expected_commit" ]]; then
    echo "FAIL: source revision $actual_commit != $expected_commit" >&2
    exit 1
  fi
  top=$(git -C "$repo" rev-parse --show-toplevel)
  if [[ "$top" != "$repo" ]]; then
    echo "FAIL: Git worktree root is $top, expected $repo" >&2
    exit 1
  fi
  status=$(GIT_OPTIONAL_LOCKS=0 git -C "$repo" status --porcelain)
  if [[ -n "$status" ]]; then
    echo "FAIL: source worktree is dirty: $status" >&2
    exit 1
  fi

  temp_dir=$(mktemp -d /tmp/m234-preflight.XXXXXX)
  trap 'rm -rf "$temp_dir"' EXIT
  python3 - "$repo" "$baseline_source_manifest" "$temp_dir/source-sha256.txt" <<'PY'
from pathlib import Path
import hashlib
import subprocess
import sys

repo = Path(sys.argv[1])
baseline_path = Path(sys.argv[2])
tracked = subprocess.check_output(
    ['git', '-C', str(repo), 'ls-files', '-z', '--', 'src', 'scripts', 'docs']
).decode().split('\0')
tracked = {path for path in tracked if path}
baseline_lines = baseline_path.read_text().splitlines()
baseline = {}
for line in baseline_lines:
    digest, path = line.split('  ', 1)
    baseline[path] = digest

missing = tracked - baseline.keys()
if missing:
    raise SystemExit(f'baseline source manifest lacks tracked paths: {sorted(missing)[:3]}')
extra = set(baseline) - tracked
if any('/.pytest_cache/' not in f'/{path}/' for path in extra):
    raise SystemExit(f'baseline has unexpected untracked paths: {sorted(extra)[:3]}')

order = {'src': 0, 'scripts': 1, 'docs': 2}
paths = sorted(tracked, key=lambda path: (order[path.split('/', 1)[0]], path))
actual = [hashlib.sha256((repo / path).read_bytes()).hexdigest() + '  ' + path
          for path in paths]
expected = [baseline[path] + '  ' + path for path in paths]
Path(sys.argv[3]).write_text('\n'.join(actual) + '\n')
if actual != expected:
    mismatch = next((p for p, a, e in zip(paths, actual, expected) if a != e), 'unknown')
    raise SystemExit(f'tracked source differs from first-pass manifest at {mismatch}')
print(f'tracked source records: {len(paths)}; ignored pytest-cache extras in baseline: {len(extra)}')
PY
  source_sha=$(sha256sum "$temp_dir/source-sha256.txt" | cut -d ' ' -f 1)

  dpkg-query -W > "$temp_dir/package-versions.tsv"
  package_sha=$(sha256sum "$temp_dir/package-versions.tsv" | cut -d ' ' -f 1)
  if [[ "$package_sha" != "$expected_package_sha" ]]; then
    echo "FAIL: package manifest $package_sha != $expected_package_sha" >&2
    exit 1
  fi
  if [[ "${ROS_DISTRO:-}" != jazzy ]]; then
    echo "FAIL: ROS_DISTRO is ${ROS_DISTRO:-unset}, expected jazzy" >&2
    exit 1
  fi

  printf 'PASS: container Git revision %s\n' "$actual_commit"
  printf 'PASS: clean worktree mounted at %s\n' "$top"
  printf 'PASS: tracked source files match the first-pass manifest (%s)\n' "$source_sha"
  printf 'PASS: package manifest sha256 %s\n' "$package_sha"
  printf 'PASS: ROS_DISTRO=%s, Python=%s\n' "$ROS_DISTRO" "$(python3 --version 2>&1)"
  exit 0
fi

if [[ "$#" -ne 4 ]]; then
  echo 'Usage: bash scripts/m234_container_preflight.sh WORKTREE COMMIT BASELINE_SOURCE_MANIFEST PACKAGE_SHA' >&2
  exit 2
fi
worktree=$(cd -- "$1" && pwd -P)
expected_commit=$2
baseline_source_manifest=$(cd -- "$(dirname -- "$3")" && pwd -P)/$(basename -- "$3")
expected_package_sha=$4
if [[ ! -f "$baseline_source_manifest" ]]; then
  echo "FAIL: baseline source manifest not found: $baseline_source_manifest" >&2
  exit 1
fi

host_commit=$(git -C "$worktree" rev-parse HEAD)
if [[ "$host_commit" != "$expected_commit" ]]; then
  echo "FAIL: host worktree revision $host_commit != $expected_commit" >&2
  exit 1
fi
if [[ -n "$(git -C "$worktree" status --porcelain)" ]]; then
  echo 'FAIL: host worktree is dirty' >&2
  exit 1
fi
common_dir=$(git -C "$worktree" rev-parse --path-format=absolute --git-common-dir)
git_dir=$(git -C "$worktree" rev-parse --path-format=absolute --git-dir)
script_path=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)/$(basename -- "${BASH_SOURCE[0]}")

actual_image_id=$(docker image inspect "$image" --format '{{.Id}}')
if [[ "$actual_image_id" != "$expected_image_id" ]]; then
  echo "FAIL: image $actual_image_id != $expected_image_id" >&2
  exit 1
fi

mounts=(
  --mount "type=bind,src=$worktree,dst=/workspace,readonly"
  --mount "type=bind,src=$worktree,dst=$worktree,readonly"
  --mount "type=bind,src=$common_dir,dst=$common_dir,readonly"
  --mount "type=bind,src=$script_path,dst=/tmp/m234_container_preflight.sh,readonly"
  --mount "type=bind,src=$baseline_source_manifest,dst=/tmp/m234-baseline-source-sha256.txt,readonly"
)
printf 'Pinned image: %s\n' "$actual_image_id"
printf 'Worktree: %s\nGit directory: %s\nCommon Git directory: %s\n' \
  "$worktree" "$git_dir" "$common_dir"
docker run --rm --user "$(id -u):$(id -g)" -e HOME=/tmp \
  "${mounts[@]}" "$image" bash /tmp/m234_container_preflight.sh --inside \
  "$expected_commit" /tmp/m234-baseline-source-sha256.txt "$expected_package_sha"
