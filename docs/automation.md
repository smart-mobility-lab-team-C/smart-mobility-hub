# Automation contracts

M0 bootstrap and doctor are implemented for the container workflow; see [M0](m0.md). Documentation link checks are also implemented. Other scripts below remain planned API contracts. Container validation is BLOCKED locally; implementation is not verification.

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

