# T01–T18 verification plan

Source: assignment §21 pp29–30 and relevant scenario sections. All tests currently NOT RUN. Proposed script: scripts/verify.sh (not implemented).

| ID | Area | Stimulus / repetitions | Acceptance |
|---|---|---|---|
| T01 | S1 counting | Known 0,3,5,4 sequence | Exact stable counts; timestamped plot |
| T02 | S1 occlusion/stale | 0.3 s occlusion, repeated/frozen frames | No duplicate count; invalid within 1.2 s freeze |
| T03 | S2 prediction | Unseen episode seeds | MAE/RMSE; MAE <= persistence; inference p95 <100 ms; no leakage |
| T04 | S2 dispatch | Threshold noise and stale forecast | One outstanding goal; explicit fallback |
| T05 | S3 docking | 10 nominal approaches | 10/10; <=0.20 m and <=0.17 rad after 1 s hold; stopped-door interlock |
| T06 | S3 cancellation | Cancel during approach | Correct terminal status; zero <=0.5 s after cancellation acceptance |
| T07 | S4 atomicity | 20 concurrent request pairs | Zero double allocations; same-ID retry stable; correct allocation when capacity exists |
| T08 | S4 expiry | Occupied/stale slot at TTL | Never falsely free; invalid release rejected |
| T09 | S5 congestion | Free flow, slow dense flow, obstruction | Correct labels; bounded scenario-defined delay; no stale-as-clear |
| T10 | S5 stale | Freeze/restore vehicle observations | UNKNOWN within source-defined threshold; clean recovery |
| T11 | S6 routing | 20 graph-state seeds | Oracle cost match within 1e-6 relative tolerance; no forbidden edges; p95 <250 ms |
| T12 | S6 no route | Block two critical edges | Explicit NO_ROUTE; zero candidate motion |
| T13 | S7 escort | 10 nominal missions | 10/10; final error <=0.20 m |
| T14 | S7 lifecycle | Busy, no-ready, cancel, stale odometry | Rejection or bounded terminal result; no hang |
| T15 | S8 integration | 10 rush-hour seeds; paired predictive/reactive | Zero collision and resource conflicts; paired metrics |
| T16 | S9 stop latch | Assert, false input, unsafe/safe reset attempts | Zero command <=0.20 s after supervisor receipt; deliberate restart |
| T17 | S9 watchdog | Kill controller, then supervisor | Supervisor and adapter independently stop motion |
| T18 | S9 service loss | Planner absent and late reply | Timeout, bounded retry; no stale-path execution |

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
