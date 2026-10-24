# Smart Mobility Hub

ROS 2 Jazzy + Python simulation-first team project.

Verification runs locally in the Ubuntu 24.04/Jazzy Docker environment by default.
GitHub Actions is an optional project tool, not a recorded assignment requirement;
hosted runs require an explicit request. See [verification policy](docs/automation.md#local-verification-default).

**Current acceptance status:** The fresh M4-only run at `b7d1df7` passed all
9/9 M4 cases, 54 package tests, and a fresh eight-package build. Its scoped
runner explicitly left M2/M3 NOT RUN. Assignment-scoped M4 functional
acceptance T07–T10 is complete, pending independent review. The latest combined
regression (`5e9757b`) passed M2 18/18 but failed at its first nominal M3 case
with `SAFE_STOP/SAFETY_INPUT_UNKNOWN:crossing_stale`; T05 is FAIL in that
attempt and T06 was NOT RUN. An earlier full M3 run (`f6a97fd`) passed 24/24,
including T05–T06, and remains historical evidence. Combined regression is
still open at M3; this does not leave M4 assignment acceptance open. Current M4
changes are on `fix/m4-local-completion`, not merged or pushed. See the [M4
evidence index](evidence/m4-local-completion.json), [M3 handoff](docs/m3.md),
and [setup](docs/setup.md). Independent review remains BLOCKED.

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

