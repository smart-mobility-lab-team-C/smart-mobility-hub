# Requirements traceability

Sources inspected: Smart_Mobility_Hub_Assignment (1) (1).pdf (A); Smart_Mobility_Hub_ROS2_Implementation_Handbook (1).pdf (H); newer instructor announcement supplied in conversation (N). Page numbers below refer to printed assignment pages.

Original PDFs are not published in this public repository. Keep authorized local copies available for Codex contract review. Do not upload course material or identifiable footage publicly without permission. H supplies implementation guidance; A defines assessed technical behavior; N updates submission rules.

| ID | Source | Required behavior | Intended implementation | Verification/evidence |
|---|---|---|---|---|
| R01 | A §§1–4 pp2–6 | Integrated deterministic Python/rclpy simulator; M1 geometry and agent constraints | Simulator/config/launch | Seed replay, map and footprint checks |
| R02 | A §§5–7 pp7–13 | Exact topics/messages/services/actions, rates, QoS and frames | Interface package + nodes | Build, interface inspect, launch tests |
| S1 | A §8 p14 | Tracking, queue counting, crossing occupancy, stale feed handling; real-video evidence | passenger_detector | T01–T02; >=100 annotated video frames; exact stable synthetic counts; video MAE <=1 |
| S2 | A §9 p15 | Trained 30-second forecast, persistence comparison, safe dispatch | demand_predictor + coordinator | T03–T04; held-out episodes; MAE <= persistence; inference p95 <100 ms |
| S3 | A §10 p16 | Arrival/docking, stopped-door interlock, feedback/cancel | bus_manager | T05–T06; 10/10; <=0.20 m, <=0.17 rad, 1 s hold |
| S4 | A §11 p17 | Atomic reservations, sensing, idempotency, expiry/release | parking_manager | T07–T08; 20 pairs, zero double allocation |
| S5 | A §12 p18 | Congestion, blocked and UNKNOWN/stale states | traffic_monitor | T09–T10; labels, transition timing, recovery logs |
| S6 | A §13 p19 | Cost-aware route/replan and explicit NO_ROUTE | route_planner | T11–T12; 20 seeds, oracle within 1e-6 relative tolerance; p95 <250 ms |
| S7 | A §14 p20 | Readiness, navigation/escort, cancellation/failures | robot_manager | T13–T14; 10/10 nominal; <=0.20 m |
| S8 | A §15 p21 | Concurrent coordination, exclusive crossing and policy comparison | hub_coordinator | T15; 10 paired seeded episodes; zero conflicts/collisions |
| S9 | A §16 p22 | Latched stop, independent watchdogs, stale/service failure and deliberate recovery | safety_supervisor + adapters | T16–T18; <=0.20 s stop command; fault repetitions |
| R03 | A §17 p23 | Exposed validated scenario parameters | Config + startup validation | Saved final parameter dump |
| R04 | A §21 pp29–30 | Actual metrics, repeatable runs and independent evaluation | Test/evidence pipeline | Raw run records and aggregates |
| R05 | A §24 pp33–34; N | Report, direct uploads, source/data ZIP and individual contributions | Submission staging | Packaging audit and member validation |
| R06 | N | 20–30-minute all-member video, full code walkthrough/results/demos | Recording plan | Duration and participation check |
| R07 | N | <=10 files; <=1 GB each; no external links; leader upload, others validate | Packaging + portal process | Size/link audit and validation record |

This is the initial traceability register. Current implementation and observed checks are recorded in [M0 status](m0-status.md), [M1 status](m1.md), [M2 status](m2.md), [M3 status](m3.md), and [M4 handoff](m4-handoff.md). The first combined local acceptance at `58f5afee` passed M2 18/18, M3 24/24 and M4 9/9, with a fresh build and 54 package tests. A repeat at the same implementation commit passed M2 but failed M3 nominal seed 309 on `SAFETY_INPUT_UNKNOWN:estop_stale`; M4 was NOT RUN. A later harness-only M3 verifier passed all ten nominal runs, including seed 309, but failed two other cases (22/24 overall); M2/M4 were NOT RUN. Candidate `67caa06` passed targeted door controls and one seed-304 comparison, then its clean combined run failed M2 (16/18); M3 and M4 were NOT RUN. That result does not replace the earlier PASS or establish repeatability. See the [first run](../evidence/m234-combined-20261025.json), [repeat result](../evidence/m234-repeat2-20261025.json), [harness attempt](../evidence/m3-operator-isolation-20261025.json), [candidate result](../evidence/door-validation-completion-20261025.json), [local M4 evidence](../evidence/m4-local-completion.json), and [local M3 evidence](../evidence/m3-local-completion.json). Independent review remains BLOCKED. The M3 completion changes from `fix/m3-local-completion` are merged into local
`main` and published to `origin/main`. M4 changes are merged into local `main` from `fix/m4-local-completion` and published to `origin/main`. Other assignment scenario rows remain NOT RUN and require their own verification.

## Assignment acceptance details omitted by the summary rows

These are assignment contracts, not evidence of implementation or PASS. Printed page
numbers refer to A. The linked [T01–T18 matrix](test-matrix.md) records execution
status separately.

| Requirement | Source | Required behavior and measured acceptance |
|---|---|---|
| S1 / T01–T02 | A §8 p14 | Count confirmed track foot-points inside Q, not cumulative detections; debounce appearance/disappearance for 0.4 s, preserve identity through a 0.5 s occlusion, and invalidate a frozen feed after 1 s. Run the 40 s script: empty for 5 s, add three tracks at t=5 s and two at t=10 s, remove one at t=15 s, occupy C for 4 s from t=20 s, and freeze the camera at t=30 s. Stable counts are 0→3→5→4; a 0.3 s occlusion cannot add a passenger, invalid state appears within 1.2 s of freeze, and C remains closed to new entry through 2 s of continuous clearance. Report ≥100 manually annotated video frames, count MAE ≤1 person, and partial-occlusion results. A homography using at least four coplanar points is required when converting image coordinates to map coordinates. |
| S2 / T03–T04 | A §9 p15 | Forecast 30 s ahead from 60 s of queue history. Generate ≥30 independent six-minute episodes and split whole episodes 60/20/20 before windowing; keep test seeds unseen and online features free of future truth. Report held-out MAE/RMSE versus persistence and inference p95 <100 ms, with model MAE no worse than persistence. Dispatch only after predictions ≥6 for three consecutive valid samples when the bus is available, keep one outstanding goal and a 30 s cooldown, and clear escalation only after five consecutive predictions below 4. Invalid forecasts cannot dispatch; record a fresh observed-queue fallback. |
| S3 / T05–T06 | A §10 p16 | Dock within 0.20 m and 0.17 rad for 1 s at measured speed <0.02 m/s. Keep the door open for an 8 s boarding interval with zero motion, board at most four waiting passengers, and confirm closure before completion or departure. Require 10/10 nominal dockings without collision, cancellation-to-zero command ≤0.5 s after acceptance, and ETA absolute error ≤3 s at 5 m for valid moving samples; report invalid ETA duration. |
| S4 / T07–T08 | A §§7.1, 11 pp10, 17 | Start slots UNKNOWN until fresh sensing is stable for 0.5 s. Enforce TTL 5–120 s, same-result retries for matching request ID and payload, unique slot/vehicle ownership, and release that cannot override physical occupancy. Start with P1 occupied and P2/P3 free; request P2 concurrently for C1/C2 at t=5 s, retry C1's ID at t=6 s, occupy C1's slot at t=8 s, disconnect P3 sensing at t=10 s, and expire remaining reservations at t=40 s. Require zero double allocations and service p95 <250 ms over 20 synchronized pairs. Barrier opening requires a valid owner and fresh clear entrance; record request and measured acknowledgment. |
| S5 / T09–T10 | A §12 p18 | Validate edge identity and corridor pose; use a 5 s window, density `min(1, n/K)`, and congestion when density ≥0.70 or mean speed stays below 40% of free flow for three publications. Require CONGESTED within 2 s of sustained threshold, BLOCKED within one publication of an observed obstruction, UNKNOWN within 1.2 s of lost valid observations, clean recovery, and zero false congestion in ten free-flow runs. |
| S6 / T11–T12 | A §13 p19 | Use nonnegative cost `length / max(valid_speed, 0.05) × (1 + 2 × density) + expected_crossing_wait`; remove blocked, stale-critical and forbidden edges. At equal speed and no density/wait, verify the 10 m A–Cs–J–E baseline and 14 m A–N–Cn–B–U–E detour. Replan immediately for an invalid route; for congestion-only changes, wait ≥2 s and require an alternative at least 15% cheaper. Compare 20 seeded graphs with an independent oracle to 10⁻⁶ relative cost and p95 <250 ms. Blocking Cs–J and Cn–B must return NO_ROUTE and zero candidate motion. |
| S7 / T13–T14 | A §14 p20 | The button/dashboard calls `/robot/confirm_ready`; the robot accepts it only at pickup in WAIT_READY and aborts after 20 s without readiness. Require 10/10 nominal escorts, final error ≤0.20 m held for 1 s, feedback at least 2 Hz apart from documented jitter, no obstacle/crossing conflict, and bounded outcomes for busy, unreachable, canceled and frozen-odometry cases. Measure cancellation request-to-acceptance separately from acceptance-to-zero command. |
| S8 / T15 | A §15 p21 | Across ten seeded episodes, warm up the queue with P1 occupied/P2–P3 free at 0–60 s; raise arrivals at 60 s; request C1/C2 parking at 65 s, escort at 70 s and readiness at 75 s; occupy C at 80–85 s; insert a lower-road obstruction at 90 s, remove it at 120 s, and finish within 180–300 s. Assert outcomes from observed state rather than fixed arrival times. Require zero collisions, overlapping crossing ownership, double allocations and duplicate dispatches. Pair predictive and reactive runs on identical seeds; report completion rate, queue wait p50/p95, mean vehicle travel time, crossing wait and robot success per run. |
| S9 / T16–T18 | A §16 p22 | Exercise camera silence/frozen stamp, robot odometry gap >1 s, candidate gap >0.5 s, planner absence/late reply with 1 s timeout and at most two retries, duplicate reservation, stale parking sensing, asserted E-stop and disappeared crossing owner. At a 20 Hz safety tick, prove zero final command ≤0.20 s after supervisor receipt, preserve the latch after false input, reject unsafe reset, and require a new goal after safe reset. Repeat each fault five times at different mission phases and report actual simulator velocity separately from zero-command latency. |

R03 (A §17 p23) requires at least `queue_confidence_min`,
`prediction_horizon_sec`, `dispatch_high`, `dispatch_low`,
`reservation_ttl_sec`, `congestion_density_threshold`,
`replan_improvement_ratio`, `robot_speed_limit`, `bus_speed_limit`,
`crossing_clear_sec`, and `command_timeout_sec` as validated parameters, with
the final parameter dump recorded for every run. R04 (A §21 pp29–30) requires
per-run ID, scenario, seed, commit and configuration hashes, model ID, times, machine
specification, accepted and rejected goals, metrics and failure reasons; report
individual trials and aggregate mean, standard deviation and p50/p95 with
sample counts. Count collisions from ground-truth footprint overlap and crossing
conflicts from incompatible physical occupancy, not just software grants.
Passengers still waiting at run end are censored, not dropped from queue-wait
results. Same-host latency uses monotonic time; physical stop time and
zero-command latency are distinct measurements.

## Mandatory source-review gate

Before M1 is frozen, transcribe M1 node coordinates, graph directionality/agent restrictions, footprints, velocities, clearance and freshness thresholds from A §§2–3; compare interface details against A §§5–7; review scenario-specific algorithms in §§8–18. This register is an implementation map, not a replacement for those contracts. Preserve source section/page next to every resulting configuration and test criterion.

Exact source details not yet represented in configuration must remain open; no guessed defaults may be promoted to requirements.

## Verification environment and source of policy

The assignment requires repeatable tests and measured evidence; the reviewed
requirement register contains no requirement to use GitHub Actions. Hosted CI was
a project tooling choice. The user's 2026-10-24 instruction makes local
Ubuntu 24.04/Jazzy Docker execution the default and requires documentation to be
updated whenever such workflow choices change. Hosted execution requires an
explicit request or a cited instructor requirement. See the [local verification
policy](automation.md#local-verification-default). Historical hosted results keep
their original provenance and do not establish local-machine acceptance.
