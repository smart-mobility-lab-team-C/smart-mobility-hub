# Source compliance register

Status recorded 2026-10-25 on `feat/mandatory-simulator-scenarios`.

Authorities, in order:

1. **A**: the assignment PDF. Page numbers are the printed numbers.
2. **N**: the newer instructor announcement. It overrides only the submission and video rules.
3. **H**: the implementation handbook. It is guidance, and A wins where the two differ.

[Requirements](requirements.md) records how the PDFs are handled; their files are not tracked in Git. This register maps every A section and the H-only guidance to the repository's current state.
[T01–T18](test-matrix.md) keeps the authoritative per-test status. This page links to it and does not restate measurements.

Status vocabulary:

| Status | Meaning |
|---|---|
| PASS | Measured evidence met the source acceptance on a recorded run. |
| FAIL | A recorded run missed the acceptance. |
| NOT RUN | Implemented, but acceptance has not been executed. |
| BLOCKED | Cannot run until a prerequisite exists. |
| NOT IMPLEMENTED | Required and absent. |
| DEVIATION | Implemented differently from the source, with the reason given. |

Historical PASS results stay historical. They don't certify later commits.

## Required nodes (A §4 pp5–6, §4.1 p6; H §5.1 p11)

| A node | Repository executable / node name | Status |
|---|---|---|
| scenario_runner | `smart_hub_sim` `scenario_runner` | Implemented. It owns the public `/scenario/reset`, world, private truth and seeded events. |
| passenger_detector | `smart_hub_perception` `passenger_detector` | Implemented: synthetic tracks, homography and debounced tracker. T01–T02 NOT RUN. |
| demand_predictor | `smart_hub_prediction` `demand_predictor` | Implemented: persistence plus ridge model. ROS T03–T04 NOT RUN. |
| bus_manager | `smart_hub_control` `bus_manager` | Implemented. T05 historical PASS, then FAIL on repeat. |
| parking_manager | `smart_hub_control` `parking_manager` | Implemented. T07–T08 PASS once at `58f5afee`. |
| traffic_monitor | `smart_hub_control` `traffic_monitor` | Implemented. T09–T10 PASS once at `58f5afee`. |
| route_planner | `smart_hub_control` `route_planner` | Implemented. T11–T12 NOT RUN. |
| robot_manager | `smart_hub_control` `robot_manager` | Implemented (M6). T11–T14 PASS once at `1218e30` ([evidence](../evidence/m6-1218e30.json)). Congestion-only replanning was added afterwards and is not yet ROS-verified. |
| hub_coordinator | executable `crossing_arbiter`, ROS node name `hub_coordinator` | **DEVIATION** (naming only): the executable name differs from A, while the node name matches. It serves `/crossing/request` and the predictive/reactive dispatch path. |
| safety_supervisor | `smart_hub_safety` `safety_supervisor` | Implemented. M2 probes are current FAIL (see [progress](mandatory-scenarios-progress.md)). |
| actuator_bridge | inside `scenario_runner` (`_active_command`) | **DEVIATION**: final-command expiry and supervisor-loss watchdog run in the simulator process rather than a separate node. A separate bridge is still required before any hardware binding (A §22 p31). |
| metrics_logger | `smart_hub_bringup` `metrics_logger` | Implemented 2026-10-25: per-run `events.jsonl`, `metrics.csv` and `summary.json`. Package tests pass; ROS run NOT RUN. |
| dashboard_marker_publisher | `smart_hub_bringup` `dashboard_marker_publisher` | Implemented, with no control authority. Marker coverage and RViz evidence NOT RUN. |

## Section-by-section register

| Source | Requirement (summary) | State and gap |
|---|---|---|
| A §1.3 p2 | 2D simulator with RViz markers; synthetic detections plus **one camera/video demonstration**; persistence plus trained model; one bus, one robot, three parking slots; waypoint motion, collision checks, crossing mutex, watchdog | Simulator, synthetic detection, model and safety exist. **BLOCKED**: the video demonstration needs team-supplied lawful video. The robot has no mission manager. |
| A §2 p3; H §3.1 p5 | Map M1 geometry and zones | PASS (M1, [m1.md](m1.md)). Derived node coordinates are recorded as approved design choices. |
| A §3.1 p4 | Graph, agent edge permissions, segment–rectangle crossing ownership | PASS for static map checks (M1). Runtime ownership is covered by the M2 probes. |
| A §3.2 p4 | 20 Hz loop, private truth, scenario-file event injection, RViz markers, fixed seed and reset | 20 Hz loop, truth separation and seeded reset are implemented. `scenarios/S1.yaml…S9.yaml` (A §19.1 p26) now declare graph, parameters, stimulus schedule and verifier. Stimuli are still applied by the verifiers, not injected from the file. |
| A §3.3 p4 | Speed caps, radii, clearance, 0.50 s command timeout, 1.0 s freshness, ≤0.20 s stop latency, arrival tolerance, 2.0 s debounce | Encoded and range-checked ([m2.md](m2.md)). Stop latency met in the M2 probes. M2 is currently FAIL on unrelated cases. |
| A §§5–6 pp7–9 | Exact topics, rates, QoS, frames, 14 messages, validity rules | Messages PASS (M1). Rates and QoS are implemented per [interfaces.md](interfaces.md). Real-node `ros2 topic hz` evidence for every topic is NOT RUN. |
| A §7.1 pp10–11 | Six services; 250 ms target; 1 s client timeout; reset acknowledged by all nodes | Five of six servers are implemented. **NOT IMPLEMENTED**: the `/robot/confirm_ready` Trigger. Reset uses an internal 0.9 s deadline inside the 1 s client timeout ([decisions D09](decisions.md)). |
| A §7.2 p12 | DockBus, EscortPassenger, NavigateTo actions with 2 Hz feedback and terminal semantics | DockBus implemented. **NOT IMPLEMENTED**: EscortPassenger and NavigateTo servers (robot_manager). |
| A §7.3 p13; H §5.4 p12 | No blocking loops; async futures; callback groups; locked shared state | Followed in implemented nodes. Callback-group isolation in `scenario_runner` was added 2026-10-25. |
| A §8 p14 (S1) | Tracking, foot-point counting, 4-point homography, 0.4 s debounce, 0.5 s occlusion, 1 s freeze invalidation, 40 s script, **≥100 annotated video frames, MAE ≤1** | Implemented (synthetic path plus NanoDet backend). T01–T02 NOT RUN in ROS. Video evaluation **BLOCKED** on annotated video. |
| A §9 p15 (S2) | ≥30 six-minute episodes split 60/20/20 by episode; ridge vs persistence; p95 <100 ms; dispatch hysteresis; fallback; reactive vs predictive comparison | Offline training: 30 episodes split 18/6/6, test MAE 3.3334 vs persistence 9.8413 (`src/smart_hub_prediction/models/ridge.json`). That is offline fixture evidence only. T03 (ROS, latency) and T04 NOT RUN. The reactive/predictive waiting-time comparison is NOT RUN. H §4.2 p7–8 also asks for one documented case where the model performs worse: NOT DONE. |
| A §10 p16 (S3) | DockBus state machine, crossing acquire/renew/release, door interlock, 10/10, ETA | T05 historical PASS, then repeat FAIL. T06 PASS. See [test matrix](test-matrix.md). |
| A §11 p17 (S4) | Atomic idempotent reservations, expiry, barrier interlock, 20 pairs, p95 <250 ms | T07–T08 PASS once at `58f5afee`. Not repeated. |
| A §12 p18 (S5) | Edge speed and density, CONGESTED/BLOCKED/UNKNOWN timing, ten free-flow runs | T09–T10 PASS once at `58f5afee`. Not repeated. |
| A §13 p19 (S6) | Cost formula, Dijkstra, replan rule, NO_ROUTE, 20-seed oracle, p95 <250 ms | Planner implemented. T11–T12 NOT RUN. Bus/robot replanning acceptance is not implemented. |
| A §14 p20 (S7) | Escort state machine, readiness 20 s, obstacle detour, cancel, 10/10 | Implemented. T13 10/10 and T14 PASS once. The obstacle is modelled as a blocked edge (logical, not a physical footprint). |
| A §15 p21 (S8) | Timed integration, cars on valid edges, FIFO crossing, ten paired seeds, metrics | **NOT IMPLEMENTED**: robot missions, car scenarios and metrics aggregation. An integrated launch exists without S8 acceptance. |
| A §16 p22 (S9) | Fault map; 20 Hz supervisor; latch; deliberate reset; five repetitions at different mission phases; process kills | Supervisor, latch and adapter watchdog are implemented and probed in M2. T16–T18 NOT RUN: there are no mission-phase repetitions, and robot-manager faults can't be exercised yet. |
| A §17 p23 | Scenario communication matrix; minimum parameters with range validation and a final dump each run | Exposed: `queue_confidence_min`, `prediction_horizon_sec`, `dispatch_high`, `dispatch_low`, `robot_speed_limit`, `bus_speed_limit`, `crossing_clear_sec`, `command_timeout_sec`. Added 2026-10-25: `reservation_ttl_sec` (parking; TTL 0 uses it), `congestion_density_threshold` (traffic), `replan_improvement_ratio` (robot). Package tests pass; M4 regression and ROS checks NOT RUN. Dumps are captured by verifiers for some nodes only. |
| A §18 pp24–25 | Algorithm pseudocode (queue, reservation, edge cost, crossing, escort, docking, watchdog) | Implemented in the corresponding nodes except ESCORT (robot_manager). |
| A §19 pp26–27 | Workspace layout, package metadata, flake8/pep257 | **DEVIATION**: application code is split across seven ament_python packages instead of one `smart_hub` package (recommended layout, [architecture](architecture.md)). Quality checks pass in colcon tests. |
| A §20.1 p28 | Launch accepts **scenario, seed and hardware/simulation mode**; team-specific `ROS_DOMAIN_ID` | `hub.launch.py scenario:=S1..S9 seed:= mode:=` added 2026-10-25. `mode:=hardware` refuses to start because no hardware bridge exists. The argument listing and the refusal were checked; full scenario launches are NOT RUN. |
| A §20.2 p28 | rosbag recording of listed topics; replay isolation | **NOT RUN**: no representative bags are recorded yet. |
| A §21.1 p29 | pytest units, launch_testing integration, T01–T18 | Units and quality checks exist. Integration uses custom real-process verifiers (`scripts/verify_m2.py`, `verify_m3.py`, `verify_m4.py`, `verify_s1.py`) rather than `launch_testing`. T01–T18 status in [test-matrix](test-matrix.md). |
| A §21.2–21.3 p30 | Run metadata, mean/std/p50/p95 with N, threshold table | Partial, in verifier JSON. **NOT IMPLEMENTED**: metrics_logger CSV per run. |
| A §22 p31 | Optional physical implementation | Not started, by design: it only follows mandatory simulator acceptance (AGENTS.md). |
| A §23 p32 | Seven-week plan, M1–M5 ownership and cross-review | Role map in [CONTRIBUTING](../CONTRIBUTING.md). **BLOCKED**: independent review and teammate reproduction, because the repository has one contributor. |
| A §24.1 p33; N | Repository snapshot, 12–18-page report, evidence directory, demo, individual defense | Not started. N overrides the 8-minute demo to a 20–30-minute video ([submission](submission.md)). |
| A §24.2 p33 | Rubric (100 points) | The [submission](submission.md) release gates map to it. A failed test must stay in the report with its diagnosis. |
| H §2.3 p4 | Unique team `ROS_DOMAIN_ID`; never commit personal video without permission | Verifiers use isolated domains. No personal footage is committed. |
| H §9.2 p18 | Readiness checklist: exact IDL; one clean build and parameter snapshot; per-scenario YAML, sample output, negative test and evidence; T01–T18 table; license notices; every teammate's commits and cross-review | IDL PASS. Scenario YAMLs NOT IMPLEMENTED. Teammate commits and cross-review BLOCKED. NanoDet carries its Apache-2.0 license file. |

## Known source discrepancies (A wins unless N applies)

- **Readiness service:** A §14.1 makes the button/dashboard the Trigger client. H §4.7 phrases it as the robot requesting readiness. A is followed ([m1.md](m1.md)).
- **Demo duration:** A §24.1 and H §7.3 say 8 minutes. N requires a 20–30-minute all-member video.
- **Traffic monitor ownership:** listed under M3 and M5 in A. H §7.1 treats M3 as the algorithm owner and M5 as the simulator-input owner.

## Highest-impact open work

1. `robot_manager` with `/robot/navigate_to`, `/robot/escort` and `/robot/confirm_ready`. This unblocks S7, S8, T13–T15 and the robot parts of T16–T18.
2. Scenario YAML files and a launch with `scenario`, `seed` and mode arguments.
3. `metrics_logger` and the three missing named parameters.
4. A repeatable M2/M3/M4 pass on a committed tree, then T01–T04, T11–T12 and T16–T18 executions.
5. An annotated-video evaluation, for which the team must supply footage.
