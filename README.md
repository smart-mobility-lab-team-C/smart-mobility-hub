# Smart Mobility Hub

ROS 2 Jazzy + Python (`rclpy`) simulation-first team project for the Smart Mobility
Engineering Lab assignment. Grading follows the assignment PDF. The implementation
handbook is guidance only; see [requirements](docs/requirements.md) for how the two
relate.

## Current status (2026-11-12)

Each row names its evidence. Runs were on different commits; one frozen revision with
two clean full runs is still open (see [HANDOFF](docs/HANDOFF.md)).

| Area | State | Evidence |
|---|---|---|
| Interfaces, map, packages (M1) | PASS: 23 interfaces, M1 map ([m1](docs/m1.md)) | `docs/contracts/m1-fields.json` |
| Simulator, safety, crossing, reset (M2) | PASS 18/18, twice on 8 vCPUs (`4867e82`). Earlier FAILs kept | `evidence/m2-8vcpu-run{1,2}-4867e82.json` |
| Bus docking S3 (M3, T05–T06) | PASS 24/24, twice on 8 vCPUs (`18e56eb`). First attempt FAIL kept | `evidence/m3-8vcpu-run{1,2}-18e56eb.json` |
| Parking S4, congestion S5 (M4, T07–T10) | PASS 9/9 once (`3da2614`) | `evidence/m4-3da2614.json` |
| Perception S1 (T01–T02, synthetic) | PASS twice. Annotated-video evaluation BLOCKED until footage exists | `evidence/s1-fix-run{1,2}.json` |
| Prediction and dispatch S2 (T03–T04) | PASS 16/16 twice (`b806ec6`), including observed-queue fallback dispatch | `evidence/s2-run{1,2}-b806ec6.json` |
| Routing S6, robot escort S7 (M6, T11–T14) | PASS 18/18 twice (`1218e30`, `f101b60`) | `evidence/m6-1218e30.json`, `evidence/m6-regress-f101b60.json` |
| Integration S8 (T15) | Verifier `scripts/verify_s8.py` implemented 2026-11-12; ten-seed paired run in progress | — |
| Safety/fault suite S9 (T16–T18) | Verifier `scripts/verify_s9.py` implemented 2026-11-12 (six faults × five mission phases); not yet run | — |

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
