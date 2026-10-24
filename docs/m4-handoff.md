# M4 parking and congestion handoff

M4 software and assignment-scoped automated acceptance: **PASS**. T07–T10:
**PASS**. Fresh source `b7d1df7d36b457ad7c8d416e3c9f9d9a63d51ca7` passed all
eight package builds, style/interface checks, 54 package tests and all nine
real-node M4 probes. Independent teammate review/reproduction remains BLOCKED.
Changes are on `fix/m4-local-completion`, unmerged and unpushed.

Assignment §§11–12 assess parking and congestion independently; §12.3 permits
S5 without commanding motion. The combined regression runner is an additional
project check. Its latest clean run at `5e9757b` passed M2 but failed M3's first
mission on `crossing_stale`; that failure remains unresolved. This M4 result does
not establish reliable bus missions or moving integration. Historical M3 PASS
and all failed/interrupted M4 attempts remain in the [evidence index](../evidence/m4-local-completion.json).

The M4-only run exposed and fixed a real freeze fault: the simulator previously
acquired one extra parking frame on the next 5 Hz tick after freeze was requested.
It now repeats the last published acquisition immediately. A regression test
covers freezing between ticks and resuming acquisition; the one-second freshness
policy and 1.2-second acceptance bound remain unchanged.

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

Use the local Cyclone/Jazzy image described in [automation](automation.md#local-verification-default).
From the repository root, this creates a fresh workspace and runs every M4 probe:

```sh
sg docker -c 'docker run --rm --user "$(id -u):$(id -g)" -e HOME=/tmp \
  -v "$PWD:/workspace" smh-m4-local \
  bash scripts/m4_container.sh /workspace/evidence/runs/m4-UNIQUE --m4-only'
```

The destination must not exist. Omitting `--m4-only` preserves the combined
M2/M3/M4 regression command; its failure is retained separately. Explicit scope
is recorded in `scope.json`, with M2/M3 NOT RUN in an M4-only invocation. No
GitHub Actions execution is required or was launched for this work.

| Measurement | Observed | Criterion / scope |
|---|---:|---|
| Concurrent reservation pairs | 20; zero double allocations | 20 pairs, unique slots/tokens |
| Service response p95 | 94.214 ms (40 samples) | <250 ms |
| Frozen parking to UNKNOWN | 1.014 s | ≤1.2 s |
| Congestion detection | 0.305 / 0.492 s | ≤2 s |
| Obstacle input acquisition to blocked publication | 0.200 / 0.369 s | Within one 2 Hz publication |
| Probe-change to received blockage | 0.354 / 0.542 s | Includes input timer and delivery |
| Frozen / missing vehicle feed to UNKNOWN | 0.692 / 0.719 s | ≤1.2 s |
| Free-flow repetitions | 10 × 6 s; zero false congestion | Distinct tracks, same simulator seed 17 |
| Classification precision / recall | 1.0 / 1.0 per class | 15 stable scripted checkpoints |
| Valid edge fraction | 0.8566 over 258 frames | Includes deliberately invalid intervals |

All expiry/occupancy/UNKNOWN, matching ownership, request deduplication, wrong
release, barrier entrance/occupied-passage, geometry/ID validation, valid-empty
traffic, individual-invalid-source and recovery assertions passed. The canonical
S4 t=5/6/8/10/40 sequence and S5 t=20/45/60 plus recovery ran against real nodes.
The two blockage acquisition/publication bounds are independently computed from
the recorded bag, separate from end-to-end probe timing.

Raw run: `evidence/runs/m4-local-20261025-freeze-fix/`. It retains source and
configuration hashes, clean commit/worktree identity, resolved versions, three
live parameter dumps, raw JSONL, a 6,286-message / seven-topic MCAP bag, the
measurement PNG, and blockage timing analysis. The [tracked index](../evidence/m4-local-completion.json)
contains exact commands, all nine outcomes, sample counts and artifact hashes.
No trained model or real-video result is claimed. M5–M7, RViz integration,
mission-phase safety repetitions and independent human review remain separate
work; M3 timing recovery must be resolved before claiming combined integration.
