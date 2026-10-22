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
| /crossing/request | RequestCrossing | hub_coordinator |
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
