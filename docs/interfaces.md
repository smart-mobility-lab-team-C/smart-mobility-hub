# ROS interface planning register

Authoritative source: assignment §§5–7, printed pp7–13; readiness and auxiliary interlocks also appear in scenario sections. This register captures the principal endpoints. Before implementation freeze, transcribe and peer-review all message fields, service/action definitions and auxiliary contracts directly from the PDFs. Do not treat this summary as a complete interface definition.

## Topics

Custom types use smart_hub_interfaces. R = reliable/volatile; number = keep-last depth; T = transient-local. Camera uses sensor-data QoS.

| Topic | Type | Rate | QoS |
|---|---|---|---|
| /camera/image_raw | sensor_msgs/Image | 10 Hz | sensor |
| /hub/queue | QueueState | 5 Hz | R10 |
| /hub/demand | DemandPrediction | 1 Hz | R10 |
| /hub/vehicles | VehicleStateArray | 10 Hz | R10 |
| /hub/bus_arrival | BusArrival | 2 Hz | R10 |
| /parking/observed | SlotObservationArray | 5 Hz | R10 |
| /parking/state | ParkingState | 2 Hz + change | R1T |
| /traffic/edges | EdgeStateArray | 2 Hz | R10 |
| /crossing/state | CrossingState | 10 Hz | R1T |
| /robot/odom | nav_msgs/Odometry | 20 Hz | R10 |
| /robot/cmd_vel_candidate | geometry_msgs/TwistStamped | 20 Hz | R1 |
| /robot/cmd_vel | geometry_msgs/Twist | 20 Hz | R1 |
| /bus/cmd_vel_candidate | geometry_msgs/TwistStamped | 20 Hz | R1 |
| /bus/cmd_vel | geometry_msgs/Twist | 20 Hz | R1 |
| /hub/estop | std_msgs/Bool | event + 10 Hz | R1T |
| /hub/safety | SafetyState | 10 Hz | R1T |
| /hub/events | HubEvent | on change | R100 |
| /hub/markers | visualization_msgs/MarkerArray | 5 Hz | R10 |

## Services and actions

| Endpoint | Type | Owner |
|---|---|---|
| /parking/reserve_slot | ReserveParking | parking_manager |
| /parking/release_slot | ReleaseParking | parking_manager |
| /route/compute | ComputeRoute | route_planner |
| /crossing/request | RequestCrossing | hub_coordinator (node name; executable `crossing_arbiter`) |
| /scenario/reset | ResetScenario | scenario_runner |
| /safety/clear_stop | ClearSafetyStop | safety_supervisor |
| /bus/dock | DockBus action | bus_manager |
| /robot/escort | EscortPassenger action | robot_manager |
| /robot/navigate_to | NavigateTo action | robot_manager |

Service normal response target: 250 ms; client timeout: 1 s. Action feedback: 2 Hz. Cancellation must confirm zero before canceled(); all terminal paths return results. Normal completion requires observed arrival and one-second stability.

Also review /robot/confirm_ready and door/barrier request/status contracts in scenario sections. Their definitions must be documented before consuming them; do not invent types.

## Frames and freshness

World frame map; robot chain map → robot/odom → robot/base_link, with bus equivalents and one transform authority per edge. Candidate commands use the agent base frame. Observation timestamps reflect acquisition, not republishing. Check source age and local receipt age; reject future timestamps beyond declared tolerance. Transient-local samples can still be stale.

## Semantic invariants

- Top-level states carry std_msgs/Header; synchronized nested records may omit it. Independently aged records need their own acquisition timestamp.
- Invalid/low-confidence queue is UNKNOWN; valid empty is zero.
- Parking states: FREE, RESERVED, OCCUPIED, UNKNOWN. Allocate only fresh FREE.
- Expiry never makes physical occupancy FREE.
- ETA is meaningful only when eta_valid; invalid eta_sec is -1.
- Crossing acquisition/renew/release uses ownership token; expired lease never overrides occupied crossing.
- Reset denies hazards, stale critical inputs, asserted stop and nonzero motion.
- False estop does not clear latch. Clear-stop permits readiness, never automatic restart.
- Reserve retries use the same request ID after timeout.

## Freeze checklist

- [ ] Exact .msg fields/types and headers reviewed.
- [ ] Exact .srv/.action request/result/feedback fields reviewed.
- [ ] Readiness and door/barrier auxiliary contracts reviewed.
- [ ] Rates, QoS, publisher ownership, frames and validity verified.
- [ ] colcon build and ros2 interface show captured.
- [ ] Real-node timing, cancellation and stale input checks captured.


## M1 transcription and endpoint ownership

The 14 messages, six services and three actions are now transcribed in
`src/smart_hub_interfaces`; [field register](contracts/m1-fields.json) records every
field and section. See [M1 review/status](m1.md) for source hashes, header policy,
source discrepancies and build blockers. The preceding freeze checklist remains
open until generated ROS checks and independent review execute.

Publisher ownership for the topic table above, in the same order: scenario_runner
(camera); passenger_detector (queue); demand_predictor (demand); scenario_runner
(vehicles); bus_manager (arrival); scenario_runner (slot observations);
parking_manager (parking state); traffic_monitor (edges); hub_coordinator
(crossing); scenario_runner/driver (odom, one authority); robot_manager (robot
candidate); safety_supervisor (robot final); bus_manager (bus candidate);
safety_supervisor (bus final); operator/scenario_runner (estop);
safety_supervisor (safety); all decision nodes (transition events);
dashboard_marker_publisher (markers). Real sensor/driver adapters replace their
simulation source; they must not become competing publishers.

| Auxiliary endpoint | Contract | Owner / consumer | Rate and semantics |
|---|---|---|---|
| /robot/confirm_ready | std_srvs/Trigger service | robot_manager server; button/dashboard client | Event; success only in WAIT_READY at pickup; 20 s readiness deadline |
| /bus/door_request | std_msgs/Bool, reliable volatile keep-last 1 | bus_manager → safety/actuator_bridge | On change; true requests open; measured stopped/docked interlock |
| /bus/door_open | std_msgs/Bool, reliable volatile keep-last 1 | actuator_bridge → bus_manager/safety | Measured status; true means open; propulsion needs confirmed closure |
| /parking/barrier_request | std_msgs/Bool, reliable volatile keep-last 1 | parking_manager → actuator_bridge | On change; true requests open; valid owner and fresh clear entrance required |
| /parking/barrier_open | std_msgs/Bool, reliable volatile keep-last 1 | actuator_bridge → parking_manager | Observed status; true means open; request is never acknowledgment |

Assignment pp16–17 fixes auxiliary QoS but supplies no numeric status publication
rate. On-change request policy and parking request ownership are M1 design choices;
status heartbeat/freshness must be declared before runtime use. Bool has no source
stamp: local receipt watchdogs and independent measured interlocks are required;
never infer safety from an old status. These topics have no geometric frame.

Map observations use map metres/radians; odometry uses robot/odom with
robot/base_link child (bus equivalents). Candidate TwistStamped uses the agent's
base frame. Final Twist is interpreted in the same base frame without a header.
Counts are people, confidence and density dimensionless [0,1], speeds m/s,
ETA/cost/deadlines seconds, expires_at ROS time. Header stamps are acquisition time
for observations; prediction/state/event stamps identify their computation or
transition while retaining source-age validity internally. Nested observations
share one acquisition timestamp. Monotonic time measures local receipt age,
watchdogs and latency; ROS time stamps data and reservation expiry, with one
consistent use_sim_time policy per run. No /clock publisher exists in M1.

Service targets, action feedback and terminal rules above remain mandatory.
Reservations accept TTL 5–120 s (client default 30 s); crossing operations are
ACQUIRE/RENEW/RELEASE with matching ownership tokens. A denied/expired resource,
invalid input, timeout, cancellation or NO_ROUTE cannot imply success or motion.
Scenario reset acknowledges all nodes after cancellation/zero and seeded reset;
clear-stop rejects hazards/stale inputs/asserted stop/nonzero motion and never
restarts a mission. Shared callback state needs synchronization and bounded async
retries. Progress across replans still needs an explicit runtime definition.

## M2 runtime additions and resolved policies

[M2](m2.md) records user-approved numeric policies, watchdogs, crossing state
semantics and the reset handshake. Public M1 message/service/action schemas remain
unchanged. `/bus/odom` uses `nav_msgs/Odometry`, 20 Hz reliable volatile depth 10,
`bus/odom` with child `bus/base_link`, matching the documented bus-equivalent frame
chain. Both odometry streams carry measured linear and angular velocities;
clear/reset require exact zero for both simulated agents.

Internal `/safety/reset_state`, `/safety/finish_reset`, `/crossing/reset_state`
and `/sim/reset_world` use `ResetScenario`. The `scenario_runner` node owns the
public `/scenario/reset` and awaits launched participants under one monotonic
deadline: 0.9 s since `038695b` (D09), so that a failure reaches the client inside its 1 s
timeout (A §7.1 p10). No mission servers participate until their milestone implements
the corresponding cancellation/acknowledgement behavior. Measured door/barrier
status heartbeat is 10 Hz in this simulator, with a 0.5 s local watchdog for door
safety; this is a declared M2 choice where the assignment specifies no rate.
Evaluator-only `/sim/evaluator/ground_truth` is `VehicleStateArray`, R10 in
`map`. It is published at 20 Hz (every simulator step) since `038695b` (D10), and was 10 Hz
before that. It is excluded from all control subscriptions.

The former `reset_coordinator` node was removed from M2–M4 launches when
public ownership was restored to `scenario_runner` on the mandatory-scenarios
branch. The fresh real-node regression at `038695b` is FAIL (17/18); see
[progress](mandatory-scenarios-progress.md).

## M3 runtime additions

[M3](m3.md) preserves every public M1 schema. `route_planner` owns `/route/compute`;
`bus_manager` owns `/bus/dock`, `/hub/bus_arrival` (2 Hz R10), bus candidates
(20 Hz R1), and on-change door requests (R1). Action feedback is 2 Hz.
Only `safety_supervisor` publishes final bus motion. Control uses fresh transformed
bus odometry and observed vehicles; evaluator truth remains evaluation-only.

M3 synthetic bringup opts into simulator-owned `/hub/queue` (5 Hz R10) and a
labelled fixture-owned `/traffic/edges` (2 Hz R10). Neither implements perception
or traffic monitoring. Internal bay/goal/run/arrival/reset endpoints, ownership,
QoS, watchdogs and invalid-value conventions are documented in M3. Public reset
remains `/scenario/reset`, owned by scenario_runner. M3 adds explicit bus
prepare/finish acknowledgements within the existing total reset deadline (0.9 s since D09).

The bus process uses internal `bus_observations` solely to receive the existing
bus input topics and TF on a dedicated single-thread executor. The mission node
retains its two-thread executor, all public publishers/actions/services and final
safety authority remains in the supervisor. Shared state is locked; the helper
shares existing bus reset acknowledgements and adds no public endpoint or custom
behavioral parameter. Bus finish-reset may wait up to 0.25 s for fresh measured
zero and an unlatched supervisor reset hold, within the unchanged total reset
deadline; timeout retains the hold. See [local M3 acceptance](m3.md#current-local-verification--2026-10-24).

## M4 implementation and functional acceptance

M4 preserves all public schemas and M2/M3 launch behavior. Its separate launch
uses traffic_monitor as the sole active road-state publisher and simulator-owned
measured bay-clear sensing. Parking publishes 2 Hz plus changes (R1 transient-local),
traffic publishes 2 Hz (R10), and public barrier requests remain on change (R1).

Internal sensor/actuator endpoints are `/parking/entrance_clear` (Bool),
`/parking/entry_vehicle_id` (String), and `/parking/barrier_heartbeat` (Bool), all
10 Hz reliable volatile depth 1 with a 0.5 s receipt watchdog. Simulator sensing
owns the first two; parking_manager owns the watchdog heartbeat. The simulator
independently validates fresh ownership/expiry and physical passage clearance;
heartbeat receipt is not measured barrier acknowledgment.

`/parking/reset_state` and `/traffic/reset_state` use ResetScenario and require
a fresh supervisor reset hold. `include_m4` adds both acknowledgments before
world reset within the existing total deadline. Per-source invalidity must be
preserved by upstream aggregators; synchronized arrays cannot silently restamp
an old individual observation as fresh. `kind=obstacle` is a corridor-validated,
zero-speed observed sentinel for the traffic monitor. Existing M2/M3 motion
safety conservatively rejects unsupported extra entities.

Traffic transition events carry JSON label/speed/density; UNKNOWN retains
`valid=false`, and a fresh known obstruction can remain `blocked=true` while
other records make density invalid. Parking reservation/release events use the
service request ID as correlation ID. Full endpoint ownership, reset behavior,
freshness policies and acceptance blockers are in the [M4 handoff](m4-handoff.md).

Assignment-scoped T07–T10 passed the independent fresh M4 run at `b7d1df7` and
the combined M2+M3+M4 run at `58f5afee4bd53567634f022d836c6a94f5daeaa7`.
The simulator's existing `freeze_parking` fault now repeats the last published
acquisition immediately, without taking one extra frame on its next tick.
Public message/QoS/timing contracts and stale thresholds are unchanged.
The first combined M2/M3/M4 regression passed, while a same-commit repeat failed
M3 on stale estop input before reaching M4. Repeatability and moving integration
remain open. Both results are recorded in the [combined evidence indexes](../evidence/m234-combined-20261025.json)
and [repeat result](../evidence/m234-repeat2-20261025.json); the earlier
`5e9757b` failure remains in the [M4 evidence index](../evidence/m4-local-completion.json).
