# Smart Mobility Hub

ROS 2 Jazzy + Python simulation-first team project.

Verification runs locally in the Ubuntu 24.04/Jazzy Docker environment by default.
GitHub Actions is an optional project tool, not a recorded assignment requirement;
hosted runs require an explicit request. See [verification policy](docs/automation.md#local-verification-default).

**Current acceptance status:** One complete combined run at `58f5afee` passed
M2 18/18, M3 24/24 and M4 9/9, with a fresh build and 54 passing package tests.
The repeat run used the same commit, image and dependencies; M2 passed 18/18,
but M3 nominal seed 309 stopped with `SAFETY_INPUT_UNKNOWN:estop_stale` after
the previous nine nominal cases passed. M4 was NOT RUN in that repeat. The
combined result is not yet repeatable; no production changes were made. See the
[first pass](evidence/m234-combined-20261025.json), [repeat result](evidence/m234-repeat2-20261025.json),
[M4 evidence](evidence/m4-local-completion.json), and [M3 handoff](docs/m3.md).

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

