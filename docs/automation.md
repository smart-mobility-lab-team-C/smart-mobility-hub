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

## CI rollout

First add documentation checks. Once code exists, add Ubuntu/Jazzy build and unit/launch tests; then seeded headless regressions and scheduled/manual full trials. A hosted Ubuntu job does not verify WSL display or local performance. No green badge until the corresponding workflow actually runs. Keep workflow token permissions minimal; do not expose credentials to untrusted PR code.


## Canonical hosted verification

[Hosted verification](../.github/workflows/verify.yml) is the automatic PR/main
workflow. Its check names are **Quick checks**, **Change classification**,
**Jazzy integration**, and **Verification gate**. The gate always evaluates job
results; a failed quick/classification job or missing required integration fails
it. Repository permissions and branch protection settings are unchanged; any
existing required milestone check names must be reviewed by the repository owner
before adopting the new gate. M0–M3 workflows are retained as manual diagnostics.

Run `bash scripts/check_fast.sh` on the PC for shell syntax, Python compilation,
M0 tooling tests, diagnostic-tool tests, CI policy tests, M1 source contracts and
local documentation links. These checks do not establish ROS integration.

Draft PRs run quick checks only. Marking ready triggers classification and, when
required, integration. The classifier diffs the PR base to its head cumulatively
(including deleted and renamed paths). Only known top-level prose, `docs/*.md`
(including subdirectories), and `evidence/` are exempt; `docs/contracts/` always
requires integration. Source, scripts, containers, workflows, tests, unknown paths
and unavailable/empty change sets require it. Changes to a PR base retrigger routing.
Documentation/evidence-only skips explicitly record **ROS acceptance NOT RUN**;
a green policy gate for a skip is not executed acceptance. Superseded runs on the
same PR are canceled. Manual runs default to quick checks; select `full_suite`
for fresh integration. Main pushes classify their complete push range.

The integration job builds one pinned-base Jazzy image with Buildx, loads it
locally and never publishes it. The [Docker GitHub Actions cache](https://docs.docker.com/build/ci/github-actions/cache/)
stores dependency image layers only (`scope=smh-jazzy`, `mode=max`). Export uses
`ignore-error=true`, so cache export failure does not fail verification; build
and test failures still fail. Build logs must be inspected to distinguish an
actual cache export from a suppressed failure. The next normal integration run
provides cache-reuse timing; do not schedule a mission suite just to benchmark.

`scripts/m3_container.sh` uses a new temporary colcon workspace every run: M0
real talker/listener smoke, M1 source/lint/hash/generated-interface checks, fresh
build and colcon tests, 18 M2 regression cases, and all 24 M3 cases (ten nominal
docks). It retains versions, source hashes, commit/worktree, logs, and explicit
exit status. Build/install/log directories and test results are never restored as
acceptance evidence. Artifact `hosted-verification-RUN_ID-ATTEMPT` also contains
image identity and UTC start/finish times; Buildx logs/build record retain cache
and image build timing. Evidence/status updates must cite the actual run and
commit and preserve failures separately from NOT RUN/BLOCKED checks.
