# M4 parking and congestion handoff

M4 verification is active on `fix/m4-local-completion`. The latest full attempt
at `d09f882` passed build/package checks and M2, then passed 22/24 M3 cases
(ten nominal docks) but failed reset and crossing-denial cases before M4.
Focused reset/M4 probes will verify the follow-up changes before a full rerun.
See [current M4 attempts](../evidence/m4-local-completion.json). T07–T10 remain
NOT RUN until the M4 probes execute. The earlier M3 completion below is retained
with its original source and outcome.

M4 implementation and earlier local verification tooling are on `main`.
The latest fresh Ubuntu 24.04/Jazzy M3 run at
`f6a97fd` passed M2 18/18, all 53 package tests, and all 24 M3 cases including
T05–T06. Its completion changes from `fix/m3-local-completion` are merged into
local `main` and have not been pushed. M4 was not run; T07–T10 remain **NOT RUN** and are the next acceptance
gate. Earlier M3 failures remain historical records. See the
[local M3 evidence index](../evidence/m3-local-completion.json). M5–M7 have not
started under the one-milestone-at-a-time rule.

The local runtime exposed two regression issues and fixed them on
`fix/m4-jazzy-runner`: import ordering rejected by ament lint, and car routing
expectations still using the previous 0.40 m/s cap. Commits are `6ba2bd3` and
`16e5918`. Their file changes are included in the published `main` tree.

The implementation is pushed to `main` in commit
[`faf8769`](https://github.com/smart-mobility-lab-team-C/smart-mobility-hub/commit/faf87696472fe85bf001794fe990025f1d77ef75).
The tested source commit is `16e5918`; the local runtime report was added to the
published tree after that run.

## Implemented behavior

- Parking initializes UNKNOWN, requires multiple valid sensor samples spanning
  0.5 s, and allocates only fresh FREE slots under one lock. Missing/invalid,
  duplicate, frozen or low-confidence sensors cannot fabricate availability.
  Confidence >=0.5 is the declared sensing policy; freshness is 1.0 s for both
  acquisition and receipt clocks. Invalidated sensing must debounce again.
- Reservations enforce TTL 5–120 s, unique ownership tokens, one slot per vehicle,
  and operation-scoped request deduplication. Identical retries return their
  original result, including after expiry; changed payloads are rejected.
  Preferred slots fall back to shortest car-network distance from entrance U,
  since ReserveParking has no vehicle location field. Ownership expiry/release
  never overrides sensed occupancy. The request ledger is capped at 10,000 keys
  per reset epoch; new keys are rejected at capacity while existing retries work.
- Barrier opening requires an entrance vehicle matching active ownership, fresh
  clear entrance sensing, and a fresh measured status heartbeat. The simulator
  independently checks current owner/token/expiry, supervisor freshness/latch,
  and a 0.5 s command lease. It holds an occupied passage open on authority loss
  and closes after physical clearance. Startup remains closed; no launch sends
  an operator heartbeat or clears a stop latch.
- Traffic validates acquisition/receipt age, advancing array stamps, identities,
  kind/edge restrictions, finite bounded speeds and corridor geometry. Its
  0.50 m corridor and 0.03 m endpoint margin accommodate the simulator's bounded
  0.02 m pose noise. Bad known-edge records invalidate their edge; an unknown
  edge or duplicate identity invalidates the full snapshot. A valid empty
  synchronized snapshot means zero vehicles. Asynchronous source aggregators
  must mark old individual records invalid; the public nested VehicleState has
  no per-record timestamp, so a silently restamped frozen individual record
  cannot be distinguished from a stationary vehicle.
- Speed is the median of current track IDs' samples in the last five seconds;
  disappeared tracks do not create ghost congestion. Density counts current
  distinct vehicles. Capacities fit car centers over usable length:
  `K = floor(max(0, L - 2r) / headway) + 1`, with r=0.30 m and headway=0.80 m.
  Declared free-flow speed is 0.35 m/s; car routing uses the same cap. Map limits
  and provenance now include those user-approved M4 defaults.
- Congestion is density >=0.70 or speed below 40% free flow for three 2 Hz
  publications. An observed `kind=obstacle` sentinel must lie in its claimed
  corridor and have zero speed; it blocks that edge at the next publication, even if another record makes
  density invalid (blocked=true, valid=false).
  Labels NORMAL/CONGESTED/BLOCKED/UNKNOWN are emitted as HubEvent transitions
  while public EdgeState fields remain unchanged. The M2/M3 safety supervisor
  conservatively inhibits motion for unsupported extra agents/obstacles; mixed
  moving traffic safety remains an M7 integration task.
- Traffic publishes at 2 Hz. Source and receipt watchdogs are conservatively
  0.65 s, allowing the next 0.5 s publication within 1.15 s of source loss,
  leaving 0.05 s scheduling margin inside the assignment's 1.2 s limit. This is
  a design policy, not a measured timing guarantee. Frozen ROS time cannot
  defeat the independent monotonic receipt watchdog.
- Parking/traffic reset acknowledgments require a fresh supervisor reset hold,
  clear caches/windows, and publish UNKNOWN. `include_m4` adds both participants
  before world reset within the existing total one-second coordinator deadline.
  The simulator rejects reset when its barrier passage is occupied.

## Runtime entry point and internal endpoints

`ros2 launch smart_hub_bringup m4.launch.py seed:=17` runs the simulator, safety,
crossing, routing, bus, parking, traffic and reset nodes. M2/M3 launches remain
unchanged. M4 replaces the synthetic road fixture with traffic_monitor and moves
measured bay-clear publication to the simulator. Synthetic queue ownership remains
explicitly simulator-owned until M5.

| Internal endpoint | Owner | Contract |
|---|---|---|
| /parking/entrance_clear | scenario_runner → parking_manager | Bool, R1 volatile, 10 Hz; fresh true means clear; 0.5 s receipt timeout |
| /parking/entry_vehicle_id | scenario_runner → parking_manager | String, R1 volatile, 10 Hz; measured entrance identity; empty denies; 0.5 s timeout |
| /parking/barrier_heartbeat | parking_manager → simulator adapter | Bool, R1 volatile, 10 Hz watchdog heartbeat; true only with current permission; 0.5 s timeout; public barrier request remains on change |
| /parking/reset_state | parking_manager | ResetScenario; requires coordinator safety hold; clears ownership/sensing/cache |
| /traffic/reset_state | traffic_monitor | ResetScenario; requires coordinator safety hold; clears window/labels |

Public barrier request/status QoS stays R1 volatile. A request is never an
acknowledgment. Parking state stays 2 Hz plus changes, R1 transient-local;
traffic stays 2 Hz R10. HubEvent logs decisions, label changes, barrier commands
and separate observed acknowledgments. Default callback groups serialize each
adapter; core parking mutations additionally share an RLock.

M4 simulator parameters expose occupied/invalid slots, parking and vehicle
publication/freeze faults, entrance identity, passage occupancy, entrance
publication and barrier-status publication. These are labelled simulator inputs,
not evaluator subscriptions or controls for real hardware. The launch never
silently enables bus/robot motion.

## Verification and reproduction

Local Ubuntu 24.04/Jazzy Docker runs are the default under the user's 2026-10-24
instruction. GitHub Actions is optional project tooling, not a recorded professor
requirement. See the [verification policy](automation.md#local-verification-default).

Actual local outcomes and commands: [local evidence](../evidence/m4-local.json).
The expanded suite includes ownership races, expiration, nearest allocation,
capacity geometry, invalid individual sources, frozen clocks, sensing recovery,
barrier lease/occupancy tests and existing simulator/safety prerequisites.

Run in the supported Docker environment as the caller's non-root UID/GID:

```sh
sg docker -c 'docker buildx build --load -t smh-m4 -f containers/Dockerfile .'
sg docker -c 'docker buildx build --load -t smh-m4-local -f containers/Dockerfile.local .'
sg docker -c 'docker run --rm --user "$(id -u):$(id -g)" -e HOME=/tmp \
  -v "$PWD:/workspace" smh-m4-local \
  bash scripts/m4_container.sh /workspace/evidence/runs/m4-UNIQUE-RUN-ID'
```

This host's current login does not include its configured `docker` supplementary
group. `sg docker -c` supplies that group for each Docker command; a newly started
login session may inherit it directly.

The M4 runner reuses the fresh M3 build, interface/style/colcon checks and M2/M3
real-node regressions, then runs `verify_m4.py` in ROS domain 74. It retains
source hashes, commit/worktree identity, versions, parameter dumps, node logs,
raw JSONL messages, bag input/output, individual outcomes, paired service latency
samples and traffic classification measurements. Ten six-second free-flow
plateaus use distinct track identities; classification precision/recall uses
explicit stable checkpoints, with transition delays reported separately.
`plot_m4.py` renders measured traffic/parking/barrier traces into a standalone PNG.
The hosted verification workflow now invokes this M4 path; it has not been run
for this continuation.

Acceptance probes include 20 actual async service pairs, duplicate/conflicting
keys, all-full/wrong-token release, observed occupancy/stale expiry, deliberately
recovered barrier opening, unknown entrance rejection, occupied-passage hold,
frozen parking, congestion/obstruction, invalid geometry/IDs, valid empty traffic,
invalid individual sources, frozen stamps, feed loss and recovery. Until executed,
these are implemented probes, not results. The runner also implements the canonical S4 t=5/6/8/10/40 sequence and S5
t=20/45/60 faults with recovery. Actual source-sequence timing, moving
integration and independent teammate reproduction still require validation.

## Historical local blocker

The earlier full local Cyclone campaign at `d660a94` passed two docking missions,
then nominal mission 3 (seed 302) aborted with `SAFE_STOP/SAFETY_STOP`. The trace
has a 0.888-second gap in safety observations and a 0.762-second gap in
final-command observations near the abort, while odometry continued. Independent
host sampling had a largest interval of 0.185 seconds over the run. The blocker
was cleared for M3/T05–T06 by the later full local M3 PASS at `f6a97fd`; M4 has
not yet been executed. Thresholds remain unchanged.

Earlier Fast DDS runs failed the one-second reset deadline. Reset diagnostics
identified `/bus/prepare_reset` and intermittent callback delivery delays. The
same-source middleware comparison passed five resets with Cyclone DDS and failed
the first with Fast DDS. This supports the local project profile, not a general
middleware-defect claim or a scenario PASS. Earlier callback-group and other
executor experiments did not resolve the issue. A later dedicated observation
executor change on `fix/m3-local-completion` passed full M3 locally and has since
been merged into local `main`; it has not been pushed.

Raw runs and the feed-gap context remain under
`evidence/runs/m4-local-20261024-cyclone-full/`; their tracked result index
preserves commit, image, configuration, seeds, outcomes and artifact hashes.
M3's local prerequisite now passes, but M4 T07–T10 remain NOT RUN until the M4
suite is executed. Real-video acceptance and independent teammate review remain
separate human gates.
