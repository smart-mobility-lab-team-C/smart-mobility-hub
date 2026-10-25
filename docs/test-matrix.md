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

The fresh `d00b23e` door validation passed all ordered controls and one
seed-304 comparison, with source bounds 8.125094930–8.125098802 s and a
separately retained 8.091999096 s receipt duration. The official nominal M3
gate now uses conservative source bounds; incomplete or threshold-crossing
evidence is BLOCKED. The historical 7.973234 s receipt failure remains
unchanged. See [door measurement validation](door-measurement.md#fresh-validation-and-source-gate-adoption).
The candidate's one clean combined run stopped at M2 (16/18, FAIL); M3 and M4
were NOT RUN. See the [completion record](../evidence/door-validation-completion-20261025.json).

| ID | Area | Stimulus / repetitions | Acceptance | Status |
|---|---|---|---|---|
| T01 | S1 counting | 40 s script: empty, then 0/3/5/4 stable counts; crossing pedestrian at 20 s | Exact debounced foot-point counts; no new crossing entry during occupancy or 2 s clear interval; timestamped count/truth plot and zero conflicts | NOT RUN |
| T02 | S1 occlusion/stale | 0.3 s missing track, repeated frames, camera freeze at 30 s | No duplicate count; preserve identity across 0.5 s occlusion; publish invalid within 1.2 s of feed freeze without restamping old data | NOT RUN |
| T03 | S2 prediction | ≥30 independent six-minute episodes, 60/20/20 split by whole episode before windows; unseen test seeds | Held-out MAE/RMSE; model MAE ≤ persistence; inference p95 <100 ms; no future-data leakage; report baseline choice if model is worse | NOT RUN |
| T04 | S2 dispatch | Noisy predictions around 6, stale forecast and feed gap | Dispatch after ≥6 for three valid predictions only when bus available; one outstanding goal, 30 s cooldown, clear escalation after five values <4; invalid forecast never dispatches; document fresh observed-queue fallback | NOT RUN |
| T05 | S3 docking | 10 nominal approaches with door and boarding trace | 10/10; ≤0.20 m and ≤0.17 rad after 1 s hold at measured speed <0.02 m/s; measured 8 s door interval, zero open-door motion, ≤4 boardings, ETA error ≤3 s at 5 m on valid moving samples | Historical PASS at 58f5afee (10/10); same-commit repeat FAIL (9/10, seed 309 estop_stale); later receipt-duration FAIL (4/5 attempted, seed 304 at 7.973234 s); candidate 67caa06 M3 NOT RUN after M2 FAIL |
| T06 | S3 cancellation | Cancel during approach | Correct terminal status; zero <=0.5 s after cancellation acceptance | PASS first run; harness cancel-during-approach PASS (0.146 s); overall harness verifier FAIL on two cases |
| T07 | S4 atomicity | 20 synchronized concurrent request pairs with P1 occupied, P2/P3 free and same-ID retry | Zero double allocations; one slot per vehicle; identical retry result; correct allocation when capacity exists; service p95 <250 ms with sample count | PASS first run; NOT RUN in repeat (independent review pending) |
| T08 | S4 expiry | Occupancy at t=8 s, P3 sensor loss at 10 s, TTL expiry at 40 s; wrong/expired token release | Occupied or stale slots never become falsely FREE; mismatched release rejected; barrier opens only for a valid owner and fresh clear entrance, with measured acknowledgment | PASS first run; NOT RUN in repeat (independent review pending) |
| T09 | S5 congestion | Free flow, three slow vehicles at 20 s, obstruction at 60 s; ten free-flow runs | NORMAL/CONGESTED/BLOCKED labels; density ≥0.70 or speed <40% free flow for three publications; congestion ≤2 s, blockage within one publication, zero false congestion in ten free-flow runs | PASS first run; NOT RUN in repeat (independent review pending) |
| T10 | S5 stale | Freeze a source at 45 s, remove valid observations and restore | UNKNOWN within 1.2 s of loss of all valid observations; no stale-as-clear; clean recovery with original acquisition timestamps | PASS first run; NOT RUN in repeat (independent review pending) |
| T11 | S6 routing | 20 seeded edge states, geometric and congestion cases | Valid allowed path, independent oracle cost within 10⁻⁶ relative tolerance, p95 <250 ms; invalid route replans immediately, congestion-only replacement no more than once per 2 s and only when ≥15% cheaper | NOT RUN |
| T12 | S6 no route | Block Cs–J and Cn–B for A→E; then restore | Explicit NO_ROUTE and zero candidate motion; validate a new route before resuming | NOT RUN |
| T13 | S7 escort | 10 nominal pickup/readiness/escort missions | 10/10, final error ≤0.20 m held for 1 s, no obstacle contact/crossing conflict, feedback ≥2 Hz apart from documented jitter | NOT RUN |
| T14 | S7 lifecycle | Busy goal, 20 s no-ready timeout, obstacle, moving cancel, unreachable goal, frozen odometry >1 s | Rejection or bounded terminal result; no hang or unsafe movement; measure cancellation request-to-acceptance and acceptance-to-zero separately | NOT RUN |
| T15 | S8 integration | Specified 0–300 s schedule across ten seeds; paired predictive/reactive runs on identical seeds | Zero collisions, overlapping crossing owners, double allocations or duplicate dispatches; report completion, queue wait p50/p95, mean travel, crossing wait and robot success per seed | NOT RUN |
| T16 | S9 stop latch | Assert at 10 s while moving, false input at 12 s, unsafe then safe reset; five phase-varied repetitions | Zero final command ≤0.20 s after supervisor receipt; latch persists after false input, unsafe reset denied, no automatic restart; report measured simulator speed separately | NOT RUN |
| T17 | S9 watchdog | Kill controller, then supervisor; candidate gap >0.5 s and robot odometry gap >1 s across five phase-varied trials | Supervisor and adapter independently stop motion; log reason and zero-command latency and measured velocity | NOT RUN |
| T18 | S9 service loss | Planner absent or late reply across five phase-varied trials | 1 s client timeout, at most two retries, explicit failure and zero motion; no stale-path execution after late reply | NOT RUN |

## Additional mandatory evidence

S1 requires at least 100 manually annotated real-video frames with count MAE <=1 person. Crossing must remain inhibited during occupancy and the two-second clear debounce. Prediction evaluation splits by held-out episodes and compares persistence on the same test targets. Safety faults repeat five times at different mission phases.

The numeric assignment limits for T09/T10/T14/T17/T18 are transcribed above.
Any project-specific watchdog or scheduling margin must remain labelled as a
design choice and cannot weaken these acceptance bounds. The S9 fault map also
includes camera silence/frozen stamps, duplicate reservations, stale parking
sensing, asserted E-stop and disappeared crossing owner; exercise each five times
at different mission phases before claiming T16–T18 complete.

## Execution layers

1. Pure pytest: geometry, stale logic, features, atomicity/idempotency, edge costs, oracle and transitions.
2. launch_testing with real nodes: topic timing/QoS, services, feedback/cancellation, command zero and reset.
3. Seeded integrated ROS runs: physical conflicts, dispatch comparison and fault injection.
4. Video evaluation and clean-checkout reproduction.

Run ament_flake8, ament_pep257 and colcon test-result --verbose. Mocks support unit tests but cannot satisfy layers 2–3.

## Result template

For every row record: status; actual command; commit; run IDs/scenario/seeds;
configuration hash and model ID; start/end time and machine specification;
accepted/rejected goals; threshold and observed value; sample count; individual
results; aggregate mean, standard deviation and p50/p95 when supported; evidence
paths; and failure/blocker reason. Count collisions by ground-truth footprint
overlap and crossing conflicts by incompatible physical occupancy, not software
grants alone. Include passengers still waiting at run end as censored queue-wait
observations. Separate supervisor-receipt-to-zero-command latency from actual
measured stop time. Missing/partial runs remain NOT RUN or BLOCKED, never PASS.

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
The committed `583859e` attempt passed preparation, interface/import checks,
and the two-package incremental build, then failed its first style gate on seven
format findings. All later control, comparison, adoption, and clean acceptance
stages are NOT RUN. See the [isolated-cache result](../evidence/door-validation-isolated-20261025.json).
