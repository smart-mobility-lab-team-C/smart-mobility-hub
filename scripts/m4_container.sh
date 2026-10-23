#!/usr/bin/env bash
# Reuse the fresh Jazzy build and M2/M3 regressions, then run M4 in its own domain.
set -euo pipefail
repo=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
export SMH_VERIFY_M4=1
exec bash "$repo/scripts/m3_container.sh" "${1:?Usage: bash scripts/m4_container.sh ABSOLUTE_RESULTS_DIRECTORY}"
