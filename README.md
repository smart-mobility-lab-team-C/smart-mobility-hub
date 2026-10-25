# Smart Mobility Hub

ROS 2 Jazzy + Python simulation-first team project.

Verification runs locally in the Ubuntu 24.04/Jazzy Docker environment by default.
GitHub Actions is an optional project tool, not a recorded assignment requirement;
hosted runs require an explicit request. See [verification policy](docs/automation.md#local-verification-default).

**Current acceptance status:** The combined local M2+M3+M4 pipeline passed at
`58f5afee4bd53567634f022d836c6a94f5daeaa7`: M2 18/18, M3 24/24, M4 9/9,
plus a fresh eight-package build and 54 passing package tests. This is one pass,
not evidence of repeatability; independent review remains BLOCKED. The earlier
`5e9757b` `crossing_stale` failure and M2+M3 reference `f6a97fd` remain in the
record. See the [combined evidence index](evidence/m234-combined-20261025.json),
[M4 evidence](evidence/m4-local-completion.json), [M3 handoff](docs/m3.md), and
[setup](docs/setup.md).

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

