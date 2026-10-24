# T01–T18 verification plan

Source: assignment §21 pp29–30 and relevant scenario sections. Status below
reflects the current local verification target. The latest local run
(`f6a97fd`) passed all 24 M3 cases, including 10/10 nominal docking runs and
T05–T06. M4 T07–T10 remain NOT RUN. Earlier local failures, including the
`d660a94` observation-gap failure, remain historical evidence. See the
[local M3 evidence index](../evidence/m3-local-completion.json).

| ID | Area | Stimulus / repetitions | Acceptance | Status |
|---|---|---|---|---|
| T01 | S1 counting | Known 0,3,5,4 sequence | Exact stable counts; timestamped plot | NOT RUN |
| T02 | S1 occlusion/stale | 0.3 s occlusion, repeated/frozen frames | No duplicate count; invalid within 1.2 s freeze | NOT RUN |
| T03 | S2 prediction | Unseen episode seeds | MAE/RMSE; MAE <= persistence; inference p95 <100 ms; no leakage | NOT RUN |
| T04 | S2 dispatch | Threshold noise and stale forecast | One outstanding goal; explicit fallback | NOT RUN |
| T05 | S3 docking | 10 nominal approaches | 10/10; <=0.20 m and <=0.17 rad after 1 s hold; stopped-door interlock | PASS |
| T06 | S3 cancellation | Cancel during approach | Correct terminal status; zero <=0.5 s after cancellation acceptance | PASS |
| T07 | S4 atomicity | 20 concurrent request pairs | Zero double allocations; same-ID retry stable; correct allocation when capacity exists | NOT RUN |
| T08 | S4 expiry | Occupied/stale slot at TTL | Never falsely free; invalid release rejected | NOT RUN |
| T09 | S5 congestion | Free flow, slow dense flow, obstruction | Correct labels; bounded scenario-defined delay; no stale-as-clear | NOT RUN |
| T10 | S5 stale | Freeze/restore vehicle observations | UNKNOWN within source-defined threshold; clean recovery | NOT RUN |
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
crossing and reset nodes with explicit synthetic queue/road inputs. The latest
local run (`f6a97fd`) passed all 24 cases, including ten nominal docking runs and
S3 fault/door/ETA checks, closing local T05–T06. Earlier hosted results remain
recorded with their original provenance. Pure routing enumerator and queue tests
do not close T11–T12, perception, mission-phase safety repetition or any other
complete scenario row. M3 fault probes are additional prerequisites; T16–T18
remain NOT RUN.
