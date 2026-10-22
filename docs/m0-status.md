# M0 observed status

Date: 2026-10-22. Overall gate: BLOCKED. Tooling implementation is separate from ROS verification.

Source baseline: `53c1560379caa9d2398a8578c63edd936eb35fc7` on main. This record accompanies the implementation commit; identify the tested revision from the PR commit containing it. Local files were obtained through the authenticated GitHub connector because host Git is absent. Local Git push authentication was not verified.

| Command/check | Actual result | Status |
|---|---|---|
| `cat /etc/os-release`; `uname -a`; `systemd-detect-virt` | Ubuntu 22.04.5 x86_64; oracle/VirtualBox | PASS (identity only) |
| `free -h`; `df -h /` | About 4 GB RAM, 25 GB free disk | PASS (inventory only) |
| `sudo -n true` | Password required, exit 1 | BLOCKED |
| `bash -n scripts/bootstrap.sh scripts/doctor.sh scripts/smoke.sh` | Exit 0 | PASS |
| `python3 -m unittest discover -s tests -v` | 5 tests passed; side effects, rejection, failure propagation, timeout | PASS (tooling only) |
| `bash scripts/doctor.sh --json` | Exit 2; host identity reported; Git, Docker, daemon, checkout, write auth blocked | BLOCKED |
| `bash scripts/bootstrap.sh --check` | Exit 2; missing runtime reported without installation | PASS (expected rejection) |
| `bash scripts/bootstrap.sh --native` | Exit 2; no host ROS install attempted | PASS (expected rejection) |
| `bash scripts/bootstrap.sh --install` | Exit 2; Docker missing/inaccessible; no build attempted | BLOCKED |
| `python3 scripts/check_docs.py` | Exit 0; local Markdown targets exist | PASS |
| Official image manifest lookup | Registry returned pinned digest recorded in Dockerfile | PASS (identity lookup only) |
| Local container build, ROS delivery, rerun, clean container reproduction | Not executed: runtime absent | BLOCKED |
| Hosted CI | See PR checks; not established by local unit results | NOT RUN at preparation |
| Teammate review | Required before merge | NOT RUN |

The five unit tests use mocks for subprocess failures only; they do not establish any ROS behavior. T01–T18 remain NOT RUN.

## Resume

1. Human installs Git and Docker Engine, handles sudo/sign-in, and configures supported Docker access using [M0 setup](m0.md).
2. Clone the PR branch, run doctor, then bootstrap check/install. Retain the resulting evidence directory and repeat the install to check rerun behavior.
3. Teammate reproduces from a fresh checkout/container and reviews the PR. Attach actual commit/run IDs and update this table.
4. Merge only after local M0 checks, CI, personal branch push and independent review satisfy the documented gates. M1 remains a separate task.
