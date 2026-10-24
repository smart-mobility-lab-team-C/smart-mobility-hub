# Automation contracts

M0 bootstrap and doctor are implemented for the container workflow; see [M0](m0.md). Documentation link checks are also implemented. Other scripts below remain planned API contracts. Local container build and ROS delivery pass; see [observed status](m0-status.md) for remaining gates.

| Proposed command | Required behavior | Success evidence |
|---|---|---|
| scripts/bootstrap.sh | Detect OS/arch; install pinned/resolved prerequisites using official sources; initialize rosdep where needed; safe reruns; never request stored passwords | OS, versions, dependency checks and install transcript |
| scripts/doctor.sh | Read-only environment, PATH, ROS distro, disk, Python imports, Git and workspace diagnostics | Machine-readable checks; actionable failures |
| scripts/build.sh | Source Jazzy; resolve declared dependencies; colcon build; preserve log | Build exit code and package results |
| scripts/test.sh | Unit and real ROS launch tests; colcon test-result --verbose | Per-suite results; no missing tests treated as success |
| scripts/run.sh | Select scenario/seed/config; launch graph; readiness gates; orderly cleanup | Unique run ID and complete metadata |
| scripts/verify.sh | Execute exact T01–T18 repetitions; aggregate raw measurements | Threshold/sample/evidence table |
| scripts/train.sh | Episode split, persistence and regression, saved model and evaluation | Split manifest, model ID, MAE/RMSE, inference timing |
| scripts/report.sh | Generate tables from evidence only | All claims trace to run artifacts |
| scripts/package.sh | Stage allowlisted files; link audit; size/asset checks; checksum manifest; ZIP | Reproducible package and audit |
| scripts/check_docs.py | Validate local Markdown links and required planning records | Documentation check output |

## Shared requirements

Use strict error handling, explicit exit codes, repository-relative paths, run-scoped logs, config validation, and cleanup traps. Never swallow a failed subprocess. Support check-only mode before installing. Do not reset global system settings or delete user files. Avoid duplicate shell profile entries and conflicting ROS sources.

Bootstrap stops on unsupported environments. It should use apt/rosdep for ROS dependencies and a documented ROS-compatible environment for additional Python packages; do not use sudo pip or bypass Ubuntu's externally managed Python protections.

Record resolved versions for reproduction. Pin downloads appropriately and verify provenance/checksums where supplied. A rerun should skip already satisfied steps and resume failed steps.

## Human steps

Windows feature enablement/reboot, Linux account creation, administrator password, Codex/Git sign-in, provision of authorized video, source review, presentation participation, and final portal upload/validation remain human tasks.

## Local verification default

The assignment requires reproducible tests and measured evidence. GitHub Actions
was a project workflow choice; no reviewed assignment requirement mandates it.
The user's 2026-10-24 instruction selects local Ubuntu 24.04/Jazzy Docker
verification as the default. Do not move verification to a hosted service because
local tests fail. Investigate and retain local failures with their actual status.
Update this policy and other affected documentation whenever workflow choices or
their attributed source change.

Run `bash scripts/check_fast.sh` on the local PC for syntax, tooling tests, M1
source contracts and documentation links. This does not establish ROS acceptance.
From the repository root, use the installed Jazzy image for full M4 verification:

```sh
sg docker -c 'docker buildx build --load -t smh-m4 -f containers/Dockerfile .'
sg docker -c 'docker buildx build --load -t smh-m4-local -f containers/Dockerfile.local .'
sg docker -c 'docker run --rm --user "$(id -u):$(id -g)" -e HOME=/tmp \
  -v "$PWD:/workspace" smh-m4-local \
  bash scripts/m4_container.sh /workspace/evidence/runs/m4-UNIQUE-RUN-ID'
```

`sg docker` uses this user's configured Docker group when the current login has
not inherited it. Run only one simulator/acceptance campaign at a time on this
VM. Stop earlier project demonstration launches cleanly before a campaign;
preserve their development shell and unrelated processes. Keep thresholds and
watchdogs unchanged when diagnosing scheduler or observation gaps.

The local profile selects `rmw_cyclonedds_cpp`. In a same-source, same-image
comparison on this VM, Cyclone DDS passed five reset repetitions while Fast DDS
failed the first reset with `RESET_DEADLINE`. This is a project configuration
choice, not an assignment requirement or proof of a general Fast DDS defect.
The full local campaign still failed a later safety-observation check; this
profile is not acceptance PASS. The base image and middleware remain available
for comparison. All nodes within
a run must use the recorded profile; public schemas, QoS and timing thresholds
are unchanged. The package and selection are supported by the
[official Jazzy Cyclone DDS documentation](https://docs.ros.org/en/jazzy/Installation/RMW-Implementations/DDS-Implementations/Working-with-Eclipse-CycloneDDS.html).

The container runner creates a fresh workspace, builds all packages, checks
interfaces/style, runs colcon tests, then M2/M3/M4 real-node checks. It retains
source and configuration hashes, commit/worktree identity, package versions,
logs, measurements and explicit exit status under `evidence/runs/`. Preserve
FAIL, BLOCKED and NOT RUN separately. Large raw evidence remains ignored; commit
small result indexes that identify the exact run. Independent local reproduction
is a separate human gate.

M2 captures live parameters through native asynchronous ROS parameter services,
matching M3. The probe continues servicing its operator heartbeat and observation
callbacks during capture. Each node retains a ten-second overall capture bound,
with three-second service/list/get phase bounds; missing or incomplete responses
fail capture. The retained JSON text is also valid YAML and contains the actual
`ros__parameters` values. This replaces blocking ROS CLI subprocesses after the
local `m3-local-20261024-completion-baseline` attempt timed out on two dumps;
that attempt remains FAIL and did not reach M3. No runtime watchdog is changed.

For the observed `/bus/prepare_reset` timeout, source a locally built Jazzy
workspace and run `python3 scripts/verify_reset.py --output
evidence/runs/reset-UNIQUE/report.json`. The default five repetitions use seeds
300–304 and the real M3 graph. Coordinator and bus logs distinguish service
delivery, lock acquisition, zero/door/pose observations and coroutine completion.
This focused probe is diagnostic-only and cannot close docking or M4 scenario
rows. After a repair, rerun the full fresh-workspace acceptance command above.

## Optional hosted verification

[Hosted verification](../.github/workflows/verify.yml) and the M0–M3 diagnostic
workflows are manual-only in this checkout. Hosted runs require an explicit user
request or a cited instructor requirement; pushing code alone is not such a
request. This trigger change takes effect on GitHub when the workflow change is
pushed. It does not cancel an already active run. Repository permissions and
branch protection are unchanged.

When explicitly requested, select `full_suite=true` for the fresh Jazzy suite;
otherwise only quick checks run. A successful skipped integration job is not ROS
acceptance. Historical hosted results remain valid evidence for their recorded
environment, not proof of local VM timing. The optional workflow retains image
identity, UTC times and acceptance artifacts. GitHub Actions cache stores
package-image layers only, never test results or build workspaces.

## M4 acceptance path and current result

The local full-suite command invokes `scripts/m4_container.sh`, which reuses the
fresh M3 build, style/interface/colcon checks and M2/M3 regressions, then runs M4
in ROS domain 74 and renders the recorded measurement plot. M2/M3 diagnostic
launches and default `m3_container.sh` behavior are preserved. The latest local Jazzy
build and M2 checks passed; two M3 docking missions passed, then mission 3 stopped
on a gap in safety observations. M4 acceptance was not reached. See the
[local full-run result](../evidence/m4-local-cyclone-attempt.json). See the [M4 handoff](m4-handoff.md)
and [local runtime evidence](../evidence/m4-jazzy-runtime.json).
