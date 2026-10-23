# Smart Mobility Hub

ROS 2 Jazzy + Python simulation-first team project.

Verification runs locally in the Ubuntu 24.04/Jazzy Docker environment by default.
GitHub Actions is an optional project tool, not a recorded assignment requirement;
hosted runs require an explicit request. See [verification policy](docs/automation.md#local-verification-default).

**Status: M2 and M3 implementation and automated acceptance PASS; T05–T06 PASS; independent human review/reproduction BLOCKED.** M4 parking and traffic implementation is on `main`; its container build and M2 regression pass, while M3 regression failed on `RESET_DEADLINE`, leaving T07–T10 NOT RUN. See the [M4 handoff](docs/m4-handoff.md) and [local Jazzy runtime evidence](evidence/m4-jazzy-runtime.json). See [M3 status and policies](docs/m3.md) and the [verification evidence index](evidence/m3-verification-attempts.json). Current target: Oracle VirtualBox Ubuntu 22.04 host with an Ubuntu 24.04/Jazzy container. See [M2 acceptance](docs/m2.md) and [setup](docs/setup.md). The WSL instructions remain an alternative setup.

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

