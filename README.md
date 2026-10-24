# Smart Mobility Hub

ROS 2 Jazzy + Python simulation-first team project.

Verification runs locally in the Ubuntu 24.04/Jazzy Docker environment by default.
GitHub Actions is an optional project tool, not a recorded assignment requirement;
hosted runs require an explicit request. See [verification policy](docs/automation.md#local-verification-default).

**Current acceptance status:** An earlier full M3 run (`f6a97fd`) passed 24/24
cases, including T05–T06; it remains historical evidence. The latest full
regression (`5976e15`) passed build, 53 package tests, and M2 18/18. Its M3
artifact records 9/10 nominal docking passes followed by seed 309 ending in
`SAFE_STOP/SAFETY_INPUT_UNKNOWN:estop_stale`. The outer runner exited 143
without finalization; the cause is unknown, so the full regression is incomplete
and the artifact failure is not a clean full-run result. T06 and M4 were not
reached. A separate focused preflight passed 20/20 reset probes and 9/9 M4 cases
(T07–T10), but does not close the full regression; the overall gate remains
open. See the [M4 evidence index](evidence/m4-local-completion.json),
[M3 handoff](docs/m3.md), and [setup](docs/setup.md).
The M3 completion changes from `fix/m3-local-completion` are merged into local
`main` and have not been pushed. Independent human review/reproduction remains BLOCKED.

## Start here

1. [Windows and Ubuntu setup](docs/setup.md)
2. [Execution plan](docs/plan.md)
3. [Codex workflow](docs/codex-workflow.md)
4. [Requirements and sources](docs/requirements.md)
5. [Architecture and diagrams](docs/architecture.md)
6. [Interface contracts](docs/interfaces.md)
7. [Verification matrix](docs/test-matrix.md)
8. [Automation specification](docs/automation.md)
9. [Team collaboration](CONTRIBUTING.md)
10. [Evidence and reproducibility](docs/evidence.md)
11. [Submission checklist](docs/submission.md)
12. [Troubleshooting](docs/troubleshooting.md)
13. [Decisions and open items](docs/decisions.md)

## Completion rule

Implemented, built, executed, and verified are separate states. A requirement is verified only when measured evidence satisfies its acceptance criteria. Every team implements S1–S8 plus mandatory S9.

Development documentation contains external reference links. The final submission must contain no external links; packaging must prepare a separate submission copy, include required assets directly, and audit it.

Read [AGENTS.md](AGENTS.md) before using a coding agent.

