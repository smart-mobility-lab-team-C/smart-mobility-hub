# Decisions and open items

| ID | Decision | Reason | Status |
|---|---|---|---|
| D01 | Codex and ROS inside WSL2 Ubuntu 24.04 | Shared Linux runtime on Windows | Superseded for the development host by the M0 update below (VirtualBox Ubuntu 22.04 + Ubuntu 24.04/Jazzy container); WSL remains the documented teammate path |
| D02 | ROS 2 Jazzy + rclpy | Assignment preferred distribution | Planned |
| D03 | Deterministic 2D baseline before optional extensions | Required scope and reproducibility | Planned |
| D04 | Safety supervisor and adapter watchdog from early integration | Independent stop paths | Required |
| D05 | Newer 20–30-minute video rule (N) overrides the 8-minute demo in A §24.1 p33 and H §7.3 p16 | Instructor announcement | Documented |
| D06 | Development links allowed in Git; separate link-free submission staging | Direct-upload submission rule | Planned |
| D07 | Branch + PR for documentation and code changes | Reviewable change to team repository | Adopted; merges remain a human decision |
| D08 | Course PDFs kept as local ignored copies, not tracked | A/H are course material in a public repository | Untracked 2026-10-25; still present in pushed history of `be224bb` until an approved rewrite |
| D09 | Public reset uses an internal 0.9 s deadline | A §7.1 p10 sets a 1 s client timeout; a failure must reach the client before it | Adopted 2026-10-25 (`038695b`); M2 still FAIL |
| D10 | Evaluator-only ground truth published every 20 Hz simulator step | Finer stop-time measurement; topic has no assignment rate; `/hub/vehicles` stays 10 Hz | Adopted 2026-10-25 (`038695b`) |
| D11 | `reset_deadline_sec` parameter: 0.9 s for the M2 graph, 2.0 s when bus/robot mission managers participate (max 2.0 s) | A sets no reset deadline; 0.9 s derived from the generic 1 s client timeout (A §7.1 p10). The 8-participant M6 handshake measured 0.83 s through four of six stages on the dev VM (prepare 0.38, safety 0.24, crossing 0.11, world 0.09 s) | User decision 2026-10-25; verifier reset clients wait 3 s |
| D12 | Retrain the S2 forecaster on the A §9.2 feature vector with no elapsed-time input; episodes randomise arrival rates, rushes and boardings; 50 episodes split 30/10/10 | The previous model used time since episode start, and every episode shared a fixed timetable. That let it learn the schedule, which A §9.2 p15 forbids as an online input | User decision 2026-10-27 (retrain to spec); held-out MAE 2.46 vs persistence 2.80 |
| D13 | `demand_predictor` parameter `forecast_model` (`ridge` default, `persistence`) | A §9.4 p15: a worse model must stay visible and the baseline must be selectable safely | Adopted 2026-10-27 |
| D14 | The coordinator queues every received forecast and counts each one once, in order, on its 1 Hz dispatch tick | The 1 Hz timer and 1 Hz forecasts drift, so counting ticks could double-count a forecast or drop the low value in a 7, 7, 5, 7 sequence. A §9.3 requires three consecutive valid predictions | Adopted 2026-10-27; T04 verified with probe-published forecasts |
| D15 | After a failed or rejected bus mission the coordinator clears dispatch escalation; the next request still waits for the 30 s cooldown, no outstanding goal and bus availability | A §9.3 step 4 clears escalation only after five low samples. A mission that ends in SAFETY_STOP boards nobody, so demand stays high and no bus would ever be sent again. Steps 2–3 (one outstanding goal, 30 s cooldown) still bound retries. The coordinator also treats bus state `SAFE_STOP` (stopped after an aborted mission) as available, because the bus manager accepts a new goal there and rejects unsafe ones itself | Adopted 2026-11-12 for S8 (T15); successful missions keep the step 4 hysteresis. Found by the first S8 smoke run: after the 80 s pedestrian latch no bus was ever re-dispatched |
| D16 | One vehicle-snapshot rule for all `/hub/vehicles` consumers (`smart_hub_sim/observations.py`): exactly one valid bus and robot, plus uniquely named valid `car` or `obstacle` records. The supervisor checks bus and robot footprints against cars (0.3 m) and obstacles (0.35 m) | A §15.1 requires synthetic cars in S8; the M2 supervisor rejected any snapshot other than {bus, robot} (`vehicles_unsupported_in_m2`) and ignored obstacles, so adding cars stopped all motion | Adopted 2026-11-12 |
| D17 | S8 fixtures: `scenario_runner` parameters `synthetic_cars` (JSON node paths on car edges, at most 0.35 m/s, rejected if the footprint could touch C) and `obstruction_active` (obstacle O at (7, 2) on Cs-J, observed as kind `obstacle`) | A §15.1 asks for cars only on valid edges and a lower-road obstruction. Scripted cars have no crossing client, so they are kept out of C rather than entering it unowned | Adopted 2026-11-12; kinematic stimuli, not a car controller |
| D18 | While demand stays at or above `dispatch_high` for three consecutive samples, the coordinator requests another bus after each 30 s cooldown, with at most one outstanding goal. Escalation and its five-low-sample clearing (A §9.3 step 4) are still computed and logged but no longer block re-requests | A §9.3 step 3 keeps a 30 s cooldown "to avoid repeated bus requests every second", which implies repeated requests at the cooldown while demand stays high. With 4 boarding slots per mission, reading step 4 as "one bus per surge" served 4 of 15 passengers in the S8 smoke run (seed 801) and made the reactive/predictive comparison uninformative (0.2 s difference) | User decision 2026-11-12 (chose the higher-scoring option after the trade-off was explained); T04 `t04_one_outstanding_goal_and_escalation` now asserts no re-request inside the cooldown |
| D19 | `/scenario/reset` refuses immediately, with reason `CROSSING_NOT_CLEAR:<state>[:<owner>]`, when the latest crossing state (at most 0.5 s old) shows an owner or occupancy, before any participant enters its reset hold | Found by `verify_s9.py`: an E-stop latched the robot inside C. The next reset was refused at the crossing stage after safety, bus and robot had already entered their holds, and none of them released. Every goal was then rejected (`reset_in_progress`), so the robot could not leave C, and a reset could never succeed. Refusing first keeps the system recoverable: the operator clears the latch and moves the agent out of C, then resets | Adopted 2026-11-12. A stale crossing snapshot still runs the stages, so the M2 missing-participant probe keeps naming the participant |
| D20 | A robot with no goal (or stopping, or with no crossing left on its route) releases the crossing once its footprint plus 0.45 m margin is clear of C, as the bus already does with 0.65 m. The larger approach guard still governs entry and exit while moving | Found by `verify_s9.py`: an E-stop at x = 6.0 on Cs-J aborted the escort inside the robot's approach guard but outside C. The idle robot renewed its token forever, the bus was denied (`ACQUIRE:OWNER_EXISTS`) and every reset was refused (`CROSSING_NOT_CLEAR:OWNED:robot`). The arbiter still releases only when the robot's footprint is observed outside C | Adopted 2026-11-13 |
| D21 | When the crossing is in HOLD (owner's lease lost) and that same agent sends ACQUIRE without a token, the arbiter issues it a new token (`REACQUIRED_OWN_HOLD`). Ownership never passes to a different agent while C is occupied | A §15.2: a lost owner heartbeat holds the crossing until C is observed empty. Found by `verify_s9.py` (T17 controller kill): the restarted robot_manager had no token, so it could neither renew nor acquire (`OWNER_EXISTS`). The robot could never leave C, so C could never be observed empty | Adopted 2026-11-13 |
| D22 | The simulator's 20 Hz timer runs every fixed 0.05 s step that is due by the monotonic clock (a longer stall is dropped and logged), instead of exactly one step per callback. At most 10 steps (0.5 s) are caught up; the executor has 8 threads so other callbacks cannot starve the step timer; callbacks that start more than 0.2 s late, wait over 0.1 s for the simulator lock or run a step over 0.1 s are logged | Native runs (no Docker) showed simulated time falling about 8% behind wall time when timer callbacks slipped; S1's wall-clock windows then failed at commit `8f15c4c` as well as on the new code. With catch-up S1 PASSes with transitions at 5.55/10.55/15.55/30.55 s, M2 stays 18/18 and M4 9/9. The old code also fails M3 natively (2/24, boarding count). With catch-up, M3 hit `STALE_DOOR` twice when the step timer was not scheduled for 1.2–1.3 s, then passed 24/24; diagnostics showed only late scheduling (≈0.2 s), never lock waits or slow steps, hence the larger executor. No `/clock` is used; simulated and wall time now agree within one step | Adopted 2026-11-14 |

## Needed before implementation freeze

Still open on 2026-10-25 unless noted. Assignment gaps are tracked in the [compliance register](compliance.md).

- Submission date/time/timezone.
- Final TEAMNAME and members' GitHub handles.
- Teammate machine resources (development host is recorded in [M0 status](m0-status.md)).
- Available hours and confirmed owner/reviewer per role.
- Authorized real video and annotation responsibility.
- Independent (human) source interface/map review; agent transcription is done in [M1](m1.md).

No performance measurements, test passes, installation success or calendar commitments are established by this documentation.


## M0 execution update

D01 is superseded for the current machine: user selected the existing Oracle VirtualBox Ubuntu 22.04 host. Run Jazzy in an Ubuntu 24.04 container; preserve host OS. M0 only is authorized now. Scoped PRs may merge after actual checks and independent review pass. See [M0 workflow](m0.md) and [status](m0-status.md). No repository permissions are changed.

## M1 decisions (2026-10-22)

M1 is authorized by the current implementation request, superseding the earlier
M0-only scope statement. Adopt the user's approved derived coordinates, no team
namespace, YAML map, Python package boundaries, and synchronized nested headers.
Preserve assignment service direction for readiness despite handbook wording.
Use geometric intersection for all crossing edges, including W–Cn. Runtime
parameters absent from the sources remain unresolved. See [source review](m1.md)
for exact provenance and outstanding acceptance/delivery blockers. No merge is
authorized by this milestone implementation.

## M2 decisions (2026-10-22)

M2 is authorized by the coordinated Luna implementation request. M1 PR #4 is
merged with successful tooling, m1 and ros-container checks; no submitted reviews
or independent reproduction record were found. Those human gates remain open.
Use the lead plus up to three `gpt-6-luna` medium workers with disjoint ownership;
centralize Git and combined ROS execution. The standard workflow is recorded in
[codex-workflow.md](codex-workflow.md).

The user explicitly approved angular cap 1 rad/s, zero future-stamp tolerance,
1 s crossing lease/renewal timeout and exact-zero simulated measured-stop policy;
car motion/headway remain M4. The fixed 0.05 s step follows the required 20 Hz
simulator. M2 uses wall-backed ROS acquisition stamps and monotonic watchdogs,
no `/clock`. Runtime details, internal reset services and limits are in [M2](m2.md).
Do not enable unobserved obstacles in this baseline; that startup configuration
is rejected. Independent source review/reproduction and later scenario/mission
acceptance cannot be inferred from worker reviews or pure tests.

## M3 decisions (2026-10-23)

The user authorized the M3 plan and selected the recommended runtime defaults:
planner retries/backoff, final-approach speed, ETA smoothing/wait validity, edge
freshness and FIFO boarding cadence. [M3](m3.md) records numeric values, source
requirements versus design choices, internal interfaces, synthetic dependencies,
reset and explicit goal recovery. M3 implementation and evidence are scoped to a
branch/PR from merged main after PR #6 (`d58e8f5`). No merge is authorized.
Independent human review and teammate reproduction remain BLOCKED; later gates
cannot inherit PASS from M3 prerequisites.
