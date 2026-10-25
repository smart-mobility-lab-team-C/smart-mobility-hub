# Smart Mobility Hub

ROS 2 Jazzy + Python (`rclpy`) simulation-first team project for the Smart Mobility
Engineering Lab assignment. Grading follows the assignment PDF. The implementation
handbook is guidance only; see [requirements](docs/requirements.md) for how the two
relate.

## Current status (2026-10-25)

| Area | State |
|---|---|
| Interfaces, map, packages (M1) | PASS: 23 interfaces, M1 map ([m1](docs/m1.md)) |
| Simulator, safety, crossing, reset (M2) | **FAIL on this branch**: 17/18 at `038695b` ([progress](docs/mandatory-scenarios-progress.md)). Last full PASS was 18/18 at `58f5afee`, historical. |
| Bus docking S3 (M3) | T05 historical PASS, then FAIL on repeat; T06 PASS ([test matrix](docs/test-matrix.md)) |
| Parking S4, congestion S5 (M4) | T07–T10 PASS once at `58f5afee`; not repeated |
| Perception S1, prediction S2 | Implemented. ROS acceptance NOT RUN. The video evaluation is blocked until annotated video exists. |
| Routing S6 | Planner implemented; T11–T12 NOT RUN |
| Robot escort S7, integration S8 | **NOT IMPLEMENTED** (`robot_manager` missing) |
| Safety/fault suite S9 | Supervisor and watchdogs implemented; T16–T18 NOT RUN |

The [compliance register](docs/compliance.md) maps every assignment section to its
implementation status, gap and evidence. Implemented, built, executed and verified are
separate states. A requirement is verified only by measured evidence.

## Build and test (local default)

Verification runs in an Ubuntu 24.04/Jazzy Docker container on the development host
([M0](docs/m0.md), [verification policy](docs/automation.md#local-verification-default)).
GitHub Actions is optional tooling and needs an explicit request.

```sh
docker run --rm --user "$(id -u):$(id -g)" -e HOME=/tmp \
  -v "$PWD:/workspace" -w /workspace smh-m4-local bash -lc \
  'source /opt/ros/jazzy/setup.bash && colcon --log-base .cache/log build \
   --base-paths src --build-base .cache/build --install-base .cache/install --symlink-install'
```

Real-node verifiers, run inside the same container after `source .cache/install/setup.bash`:

- `python3 scripts/verify_m2.py --output <file>.json` checks safety, crossing and reset.
- `scripts/verify_m3.py` and `scripts/verify_m4.py` check S3 and S4/S5 respectively.
- Launch files are in `src/smart_hub_bringup/launch/`. They are `m2`, `m3`, `m4`,
  `integrated` (argument `seed`) and `s1_counting`.

## Parameters and limitations

- **Parameter record.** Safety and timing parameters are range-checked at startup.
  Their values and sources are in [M2](docs/m2.md), [M3](docs/m3.md) and the
  [M4 handoff](docs/m4-handoff.md). Verifiers save live parameter dumps in their JSON
  evidence.
- **Missing parameters.** A §17 requires `reservation_ttl_sec`,
  `congestion_density_threshold` and `replan_improvement_ratio` as named parameters.
  They are not exposed yet.
- **Launch.** It does not accept the `scenario` or hardware/simulation-mode arguments
  required by A §20.1. There are no `scenarios/S*.yaml` files.
- **Evidence scope.** All results are simulation-only. Prediction metrics are offline
  fixture evidence.
- **Human gates.** Independent human review and teammate reproduction are BLOCKED,
  because the repository has one contributor.

## Documentation map

0. [Team handoff](docs/HANDOFF.md)
1. [Requirements and sources](docs/requirements.md) and the [compliance register](docs/compliance.md)
2. [Interface contracts](docs/interfaces.md) and [architecture](docs/architecture.md)
3. [Verification matrix T01–T18](docs/test-matrix.md) and [evidence](docs/evidence.md)
4. [Execution plan](docs/plan.md) and [decisions](docs/decisions.md)
5. [Setup](docs/setup.md), [automation](docs/automation.md), [troubleshooting](docs/troubleshooting.md)
6. [Team workflow](CONTRIBUTING.md), [Codex workflow](docs/codex-workflow.md), [AGENTS.md](AGENTS.md)
7. [Submission checklist](docs/submission.md)

The milestone records (`docs/m0*.md`–`m4-handoff.md`) and the diagnostic diaries
(`m3-gap-diagnostic.md`, `door-measurement.md`, `vm-host-repair.md`) are historical
evidence. They are kept unchanged except for status notes.

Development docs contain external links. The final submission must contain none.
Packaging prepares a separate audited copy with all required assets included
([submission](docs/submission.md)).
