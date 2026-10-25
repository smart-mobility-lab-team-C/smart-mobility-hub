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
For Python-only diagnosis, reuse the verified generated-interface install and
overlay current sources rather than rebuilding every package. The
[bounded crossing diagnostic and test tiers](m3-gap-diagnostic.md#bounded-crossing-boundary-diagnostic--2026-10-25)
describe identity checks, recorded results and limits. This development shortcut
does not replace final clean-build acceptance. The single crossing diagnostic
did not reproduce `crossing_stale`; it failed separately with `STALE_DOOR`, so
integration readiness remains blocked and no runtime correction is claimed.

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
An earlier full local campaign failed a safety-observation check; that historical
failure was followed by a full M3 local PASS on the same recorded Cyclone image
profile. This does not establish an M4 PASS. The base image and middleware remain
available for comparison. All nodes within
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
M4 now uses the same asynchronous capture approach for its three parameter
dumps, retaining JSON text (valid YAML) in the existing `.yaml` files. It keeps
the probe's synthetic input and operator heartbeat callbacks active during
evidence capture rather than blocking on ROS CLI subprocesses.

Supervisor-loss verification sends the termination signal, continues receiving
truth observations, and measures the first fresh post-signal zero-speed sample
against the unchanged 0.65 s observer bound. Process reaping is measured
separately afterward. Each trial retains signal/source/receipt times and speed
samples, including partial data on failure. The earlier M4 completion baseline
failed the old combined timing check at 0.678 s; it remains FAIL, with M3/M4
NOT RUN in that attempt. Its missing per-trial trace cannot establish when the
physical stop occurred. Runtime watchdogs and their thresholds are unchanged.

During the later `m4-local-20261024-active-probe` attempt, M2 passed but M3 had
two failed fault cases: a total reset deadline and an unexpected `estop_stale`
stop during crossing-denial testing. The evaluator probe had roughly 0.7 s
callback gaps while independent host sampling continued. M3's explicit operator
heartbeat now runs in a joined publisher thread within the probe process,
independent of evaluator callback dispatch. It publishes only the probe's chosen
stop value; process suspension still suspends it, and real stop assertions and
watchdogs are unchanged. Launches still provide no operator heartbeat.
The later full run at `5976e15` still failed its tenth docking mission with
`estop_stale`, so the publisher-thread change alone did not establish a complete
repair. The focused M4 checks passed, but full regression remains open. The M3
probe now retains operator publication start/return timestamps in a separate
JSONL file; the independent diagnostic observer also receives the stop topic.
These records distinguish publisher scheduling from observer/supervisor receipt.
The first recorded baseline mission succeeded without stale stop input. Its
publisher intervals reached 0.365 s and publish calls reached 0.170 s; it did not
provide supervisor callback spans because the campaign analyzer stopped before
instrumented attempts. The test heartbeat now uses an absolute monotonic 10 Hz
schedule, skipping missed slots without a catch-up burst. This avoids adding a
publish call's duration to every nominal 100 ms interval. Full verification is
still required; this timing correction does not change the receiver watchdog.

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

For linked worktrees, `.git` is a pointer to a Git admin directory outside the
worktree. A container must mount the worktree at `/workspace`, the same source
at its original absolute path (for the admin `gitdir` backlink), and the common
Git directory at its original absolute path. Use the provenance-only preflight
before a repeat run:

```sh
bash scripts/m234_container_preflight.sh /tmp/smh-m234-preflight-58f5afee \
  58f5afee4bd53567634f022d836c6a94f5daeaa7 \
  evidence/runs/combined-m234-20261025/source-sha256.txt \
  437ad4c24291a444fb81f3ae26ae2cd93f59bdf4907e610e2fc46aa64d092259
```

It runs inside the pinned acceptance image with read-only mounts and checks the
revision, worktree status, tracked source records, package manifest and ROS
runtime. It does not build or run milestone checks. The corrected mount setup
passed; results are in the [preflight record](../evidence/m234-container-preflight-20261025.json).

Assignment §§11–12 assess S4/S5 independently; §12.3 explicitly permits S5
without motion commands. T07–T10 do not require ten bus docking missions first.
The default combined M2/M3/M4 runner is a project regression choice, not an
additional instructor acceptance condition. To execute all M4 probes from a
fresh build, including package/style/interface checks, use:

```sh
sg docker -c 'docker run --rm --user "$(id -u):$(id -g)" -e HOME=/tmp \
  -v "$PWD:/workspace" smh-m4-local \
  bash scripts/m4_container.sh /workspace/evidence/runs/m4-UNIQUE --m4-only'
```

This explicit scope writes `scope.json` with M2/M3 **NOT RUN** and retains all
nine M4 probes, bags, parameter dumps and plots. Omitting the flag runs the full
M2/M3 prerequisite checks before M4. M4-only PASS establishes T07–T10,
not M3 recovery, moving integration, or T15–T18. The combined run at
`58f5afee4bd53567634f022d836c6a94f5daeaa7` now passes M2, M3 and M4 once;
the earlier `5e9757b` `crossing_stale` result remains a FAIL for that run.
The same-commit repeat passed M2 18/18 but failed M3 nominal seed 309 with
`SAFETY_INPUT_UNKNOWN:estop_stale`; M4 was NOT RUN. Repeatability and independent
review remain open. See the [repeat result](../evidence/m234-repeat2-20261025.json).

The local full-suite command invokes `scripts/m4_container.sh`, which reuses the
fresh M3 build, style/interface/colcon checks and M2/M3 regressions, then runs M4
in ROS domain 74 and renders the recorded measurement plot. M2/M3 diagnostic
launches and default `m3_container.sh` behavior are preserved. The combined
local run at `58f5afee4bd53567634f022d836c6a94f5daeaa7` passed M2 18/18, M3
24/24 including seeds 300–309, and M4 9/9, after a fresh eight-package build,
style/interface checks and 54 package tests. Optional diagnostic instrumentation
was disabled; the first run took 21m 44.868s. A same-commit repeat passed the
build, package tests, and M2, then failed M3 nominal seed 309 on stale estop
input; M4 was NOT RUN. See the [first pass](../evidence/m234-combined-20261025.json)
and [repeat result](../evidence/m234-repeat2-20261025.json).
The M3 completion changes from `fix/m3-local-completion` are merged into local
`main` and published to `origin/main`. See the
[local M3 evidence index](../evidence/m3-local-completion.json), [M4 handoff](m4-handoff.md),
and [local runtime evidence](../evidence/m4-jazzy-runtime.json).
Later prerequisite failures and M4 completion evidence are retained in
the [M4 attempt index](../evidence/m4-local-completion.json).
