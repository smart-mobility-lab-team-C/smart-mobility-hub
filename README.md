# Smart Mobility Hub

ROS 2 Jazzy + Python simulation-first team project.

Verification runs locally in the Ubuntu 24.04/Jazzy Docker environment by default.
GitHub Actions is an optional project tool, not a recorded assignment requirement;
hosted runs require an explicit request. See [verification policy](docs/automation.md#local-verification-default).

**Current local status:** M2 passed 18/18 cases, and the latest local M3 run
passed 24/24 cases, including 10/10 nominal docking runs and T05–T06. The run
passed 53 package tests. M4 T07–T10 remain NOT RUN and are the next acceptance
gate. The M3 completion changes are on `fix/m3-local-completion`; that branch is
not merged or pushed. Earlier local M3 failures remain historical records. See
the [local M3 evidence index](evidence/m3-local-completion.json), [M4 handoff](docs/m4-handoff.md),
and [setup](docs/setup.md).
Independent human review/reproduction remains BLOCKED.

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

