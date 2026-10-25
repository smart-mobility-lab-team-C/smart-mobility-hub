# Team workflow

All five members contribute code/evidence and explain their work. Actual names and capacity remain unassigned.

Roles and cross-review follow assignment §23.2 p32 (M1–M5). Names are not assigned yet.

| Member | Primary scope (A §23.2) | Reviews / demonstrates |
|---|---|---|
| M1 | Detector, tracking, demand features, model training, S1/S2 experiments | Reviews M3 state validity; explains leakage prevention |
| M2 | Coordinator, bus manager, dispatch hysteresis, crossing arbitration, S3/S8 | Reviews M4 cancellation; explains resource ownership |
| M3 | Parking manager, idempotency, traffic monitor, S4 concurrency tests | Reviews M1 data labels; explains atomic updates |
| M4 | Map graph, route planner, robot manager, S6/S7 tests | Reviews M2 crossing logic; demonstrates blocked-route recovery |
| M5 | Simulator, traffic monitor (simulator inputs), safety, launch, actuator adapter, S5/S9 | Reviews integrated failures; demonstrates watchdog and reset |

Every member writes tests for their own subsystem and reviews another one. M5
coordinates integration tooling. Each member fixes their own integration defects
(A §23.2). Traffic monitoring appears under both M3 and M5 in A; H §7.1 p15 treats
M3 as the algorithm owner and M5 as the simulator-input owner.

## Daily workflow

1. Read current issues, docs and AGENTS.md.
2. Use a personal branch such as feat/parking-reservations or docs/setup.
3. One bounded task per Codex session; separate worktrees for concurrent sessions.
4. Run relevant checks, save evidence, inspect diff.
5. Open PR with requirement IDs, actual commands/results, limitations and evidence.
6. Reviewer checks contracts and integration; integration owner merges.
7. Update status and contributions.

Avoid concurrent edits to interface definitions; review contract changes with all affected owners before implementation. Never force-push shared branches or overwrite uncommitted work.

## Definition of done

Code reviewed, required checks pass, failure paths exercised, documentation current, evidence points to the tested commit, and a teammate can reproduce it. If a check cannot run, document BLOCKED and the cause; do not call the requirement verified.

## Proposed repository settings

Owner configures protected main with PR review and required checks once workflows exist. Grant developers Write, reserve Admin for maintainers. These settings are recommendations and have not been changed.

## Contribution record

For each member record date, issue/PR/commit, implementation responsibility, tests executed, evidence reviewed, report sections and video segment. Commit counts alone do not measure contribution.
