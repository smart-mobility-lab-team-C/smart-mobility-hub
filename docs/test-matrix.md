# T01–T18 verification plan

Source: assignment §21 pp29–30 and relevant scenario sections. The combined
local run at `58f5afee4bd53567634f022d836c6a94f5daeaa7` passed M2 18/18, M3
24/24 and M4 9/9 after a fresh build and 54 package tests. T05 and T06 passed
in that run. The same-commit repeat passed M2 but failed the tenth nominal M3
case with `SAFETY_INPUT_UNKNOWN:estop_stale`; T06 and M4 were NOT RUN in that
repeat. The earlier `5e9757b` `crossing_stale` failure and other outcomes remain
in the [first run](../evidence/m234-combined-20261025.json), [repeat result](../evidence/m234-repeat2-20261025.json),
[M4 attempt index](../evidence/m4-local-completion.json), and [local M3 evidence
index](../evidence/m3-local-completion.json). A later harness-only M3 verifier
run passed all ten nominal seeds and the E-stop latch case, but failed two other
cases (22/24 overall); M2/M4 were NOT RUN. See the [harness attempt](../evidence/m3-operator-isolation-20261025.json).
Repeatability remains open.

| ID | Area | Stimulus / repetitions | Acceptance | Status |
|---|---|---|---|---|
| T01 | S1 counting | Known 0,3,5,4 sequence | Exact stable counts; timestamped plot | NOT RUN |
| T02 | S1 occlusion/stale | 0.3 s occlusion, repeated/frozen frames | No duplicate count; invalid within 1.2 s freeze | NOT RUN |
| T03 | S2 prediction | Unseen episode seeds | MAE/RMSE; MAE <= persistence; inference p95 <100 ms; no leakage | NOT RUN |
| T04 | S2 dispatch | Threshold noise and stale forecast | One outstanding goal; explicit fallback | NOT RUN |
| T05 | S3 docking | 10 nominal approaches | 10/10; <=0.20 m and <=0.17 rad after 1 s hold; stopped-door interlock | Historical PASS at 58f5afee (10/10); same-commit repeat FAIL (9/10, seed 309 estop_stale); latest working-tree run FAIL (4/5 attempted, seed 304 door open 7.973234 s); harness run 10/10 |
| T06 | S3 cancellation | Cancel during approach | Correct terminal status; zero <=0.5 s after cancellation acceptance | PASS first run; harness cancel-during-approach PASS (0.146 s); overall harness verifier FAIL on two cases |
| T07 | S4 atomicity | 20 concurrent request pairs | Zero double allocations; same-ID retry stable; correct allocation when capacity exists | PASS first run; NOT RUN in repeat (independent review pending) |
| T08 | S4 expiry | Occupied/stale slot at TTL | Never falsely free; invalid release rejected | PASS first run; NOT RUN in repeat (independent review pending) |
| T09 | S5 congestion | Free flow, slow dense flow, obstruction | Correct labels; bounded scenario-defined delay; no stale-as-clear | PASS first run; NOT RUN in repeat (independent review pending) |
| T10 | S5 stale | Freeze/restore vehicle observations | UNKNOWN within source-defined threshold; clean recovery | PASS first run; NOT RUN in repeat (independent review pending) |
| T11 | S6 routing | 20 graph-state seeds | Oracle cost match within 1e-6 relative tolerance; no forbidden edges; p95 <250 ms | NOT RUN |
| T12 | S6 no route | Block two critical edges | Explicit NO_ROUTE; zero candidate motion | NOT RUN |
| T13 | S7 escort | 10 nominal missions | 10/10; final error <=0.20 m | NOT RUN |
| T14 | S7 lifecycle | Busy, no-ready, cancel, stale odometry | Rejection or bounded terminal result; no hang | NOT RUN |
| T15 | S8 integration | 10 rush-hour seeds; paired predictive/reactive | Zero collision and resource conflicts; paired metrics | NOT RUN |
| T16 | S9 stop latch | Assert, false input, unsafe/safe reset attempts | Zero command <=0.20 s after supervisor receipt; deliberate restart | NOT RUN |
| T17 | S9 watchdog | Kill controller, then supervisor | Supervisor and adapter independently stop motion | NOT RUN |
| T18 | S9 service loss | Planner absent and late reply | Timeout, bounded retry; no stale-path execution | NOT RUN |

## Additional mandatory evidence

S1 requires at least 100 manually annotated real-video frames with count MAE <=1 person. Crossing must remain inhibited during occupancy and the two-second clear debounce. Prediction evaluation splits by held-out episodes and compares persistence on the same test targets. Safety faults repeat five times at different mission phases.

T09/T10/T14/T17/T18 require scenario-specific numeric deadlines/freshness thresholds to be transcribed and reviewed from their source sections before implementation. The table is not permission to choose weaker limits.

## Execution layers

1. Pure pytest: geometry, stale logic, features, atomicity/idempotency, edge costs, oracle and transitions.
2. launch_testing with real nodes: topic timing/QoS, services, feedback/cancellation, command zero and reset.
3. Seeded integrated ROS runs: physical conflicts, dispatch comparison and fault injection.
4. Video evaluation and clean-checkout reproduction.

Run ament_flake8, ament_pep257 and colcon test-result --verbose. Mocks support unit tests but cannot satisfy layers 2–3.

## Result template

For every row record: status; actual command; commit; run IDs/seeds; threshold; observed value; sample count; individual results; aggregate statistics; evidence paths; failure/blocker reason. Missing/partial runs remain NOT RUN or BLOCKED, never PASS.

## M2 prerequisite probes

`scripts/verify_m2.py` runs real simulator, supervisor, arbiter and reset processes
with controlled synthetic inputs and isolated ROS domains for occupancy faults.
It records startup zero, five candidate-expiry/queue-loss/frozen-stamp/E-stop/recovery/supervisor-
loss trials, invalid observations/commands, physical crossing entry/lease hold,
and reset acknowledgements/rejections. [M2](m2.md) and the committed evidence index
record executed outcomes. This establishes prerequisite behavior only: there are
no mission controllers yet, so these probes do not close T16–T18 across mission
phases, nor any other complete scenario row. Frozen source-stamp logic also has
pure boundary tests; real-node repeated-stamp and missing-publication probes
remain separately identified in the report.

## M3 execution scope

`scripts/verify_m3.py` exercises real route, bus action, simulator, safety,
crossing and reset nodes with explicit synthetic queue/road inputs. The earlier
local run (`f6a97fd`) passed all 24 cases, including ten nominal docking runs
and S3 fault/door/ETA checks. The combined repeat's artifact records T05
failure at seed 309; M4 was not reached. A subsequent harness-only verifier
attempt passed the ten nominal runs, including seed 309, and the E-stop latch
case, but failed `busy_goal_rejection` and
`crossing_denial_renewal_loss_and_explicit_recovery`. Its overall result remains
FAIL; M2/M4 were NOT RUN. Earlier hosted results remain recorded with their
original provenance. Pure routing enumerator and queue tests
do not close T11–T12, perception, mission-phase safety repetition or any other
complete scenario row. M3 fault probes are additional prerequisites; T16–T18
remain NOT RUN.

A targeted correction fixed the simulator's shared-Cn-node deadlock. The first
real-node recovery attempt then exposed a guard/release mismatch: the bus
released ownership while its expanded movement guard still required it, waited
at x=6.247 m for 68.803 s, then stopped on `crossing_stale`. The release rule
was aligned with the movement guard. The follow-up recovery case passed in
67.773 s, and 14 focused M2 world/M3 routing unit tests passed. This verifies
the targeted correction; it does not close the full M3 suite or the combined
M2+M3+M4 pipeline. See the [attempt index](../evidence/m3-node-boundary-fix-20261025.json).

The later official clean-build combined run passed build, interface/style,
58 package tests and M2 (18/18), then failed M3 at nominal seed 304: observed
door-open time was 7.973234 s against the 8.0 s threshold. It stopped on first
failure; remaining M3 cases and M4 were NOT RUN. Prior same-seed runs measured
8.201097 s and 8.118734 s. The physical cause remains unproven. The earlier dwell-timing and margin
recommendation is withdrawn; controller timing is unchanged.
See the [combined result index](../evidence/m234-node-boundary-fix-20261025.json).

## Stopped door measurement controls — 2026-10-25

Source duration evidence remains unvalidated. The original incremental build
failed on the missing cache mount. A user-authorized fresh attempt at `2c9ad87`
passed mount/dependency/import checks, then failed the simulator build on
root-owned cached package metadata. Style, producer/evaluator and harness
controls, world/routing regressions, seed-304 comparison, adoption, and clean
M2+M3+M4 acceptance are NOT RUN for the resume. No retry followed and no historical
test status changed. See [both stopped attempts](door-measurement.md) and the
[resume index](../evidence/door-measurement-resume-20261025.json).

The isolated-cache continuation is authorized in the current user plan. Its
ordered gates and conditional comparison/acceptance are documented in
[door measurement validation](door-measurement.md#isolated-cache-continuation).
