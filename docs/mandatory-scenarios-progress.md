# Mandatory scenario implementation progress

Status recorded 2026-10-25 on branch `feat/mandatory-simulator-scenarios`, based
on `31701cf`. This is an implementation checkpoint, not milestone acceptance.
The previous agent's full S1–S9 plan is not complete in this revision.

## Implemented in this checkpoint

- Moved the public `/scenario/reset` workflow from the bringup coordinator into
  `scenario_runner`. It awaits the configured safety, crossing, simulator, bus,
  parking and traffic reset participants under a monotonic one-second deadline.
  M2–M4 launch files and verifiers no longer start or inspect
  `reset_coordinator`. The M2 verifier's missing-participant probe now stops the
  crossing participant while leaving the public server alive.
- Added a synthetic image pedestrian source, four-point homography, debounced
  foot-point tracker, short occlusion retention, source-stamp freshness handling,
  and a 40-second S1 simulator fixture. Added an offline NanoDet backend and a
  local video-frame evaluator. The team has not supplied annotated video; the
  required 100-frame evaluation remains open.
- Added episode-level ridge training and a runtime demand predictor. The checked
  in training report uses 18/6/6 episodes, with seeds held out before windowing.
  Its synthetic six-episode test reports MAE 3.3334 versus persistence 9.8413
  across 1,626 windows. This is offline fixture evidence, not ROS T03 acceptance.
- Added a predictive/reactive dispatch path to the existing crossing coordinator,
  a fresh-state crossing wait term in route cost, a dashboard marker publisher,
  an integrated launch, and a direct-upload file audit.
- Pinned the OpenCV Zoo NanoDet ONNX asset to commit
  `25f423d0e04c31a17254620e58febd7386da523b`, including its Apache-2.0 license.
  Asset SHA-256:
  `4b82da9944b88577175ee23a459dce2e26e6e4be573def65b1055dc2d9720186`.

## Verification recorded

The isolated workspace build command was:

```sh
docker run --rm --user "$(id -u):$(id -g)" -e HOME=/tmp \
  -v "$PWD:/workspace" -w /workspace smh-m4-local bash -lc \
  'source /opt/ros/jazzy/setup.bash && colcon --log-base /workspace/.cache/mandatory-log build --base-paths /workspace/src --build-base /workspace/.cache/mandatory-build --install-base /workspace/.cache/mandatory-install --symlink-install'
```

It reported eight packages finished. Some source changes occurred during the
build, so it does not certify the final committed tree.

The focused tests reported `19 passed` for prediction, perception, routing and
package quality, and `1 passed` for the package audit. They were run before the
last simulator fixture, marker publisher, and S1 runner edits. A later
`compileall` and `git diff --check` passed before those final edits; no fresh
verification of the exact committed tree has been completed.

The real-node M2 attempt is retained at
[`evidence/runs/mandatory-m2-first.json`](../evidence/runs/mandatory-m2-first.json)
and has status **FAIL** (15/18 recorded cases passed). Failures were:

- E-stop probe could not observe motion before injecting the stop.
- Missing crossing participant caused the probe's `/scenario/reset` call to
  time out.
- Physical crossing entry failed because the bus stopped before entering C.

The reset trace also records a 1.052 s elapsed sequence for seed 102, beyond the
one-second contract. Thus reset ownership is corrected in source, but its
deadline is not yet reliably met. No second M2 pass was recorded. M3 and M4
were not run on this revision.

The OpenCV-enabled container image build was cancelled during layer export to
preserve the remaining local budget. No resulting image, NanoDet ONNX
load/inference, or real video evaluation was verified.

## Acceptance still open

T01–T18 are not closed by this checkpoint. In particular, there is no
`robot_manager`; bus/robot route-replanning acceptance, S8 car scenarios,
phase-varied S9 faults, full metrics aggregation and the final fail-fast T01–T18
runner remain unimplemented. Do not mark those gates PASS. M2 repeatability
requires two complete separately recorded passes; neither repeatability nor
clean final-tree acceptance is established here.

## M2 regression work — 2026-10-25 (later)

Source changes are in commit `038695b`. Each item gives the assignment rule it
preserves.

- **E-stop verifier:** a failing trial no longer leaves a live robot candidate behind.
  That candidate caused the cascaded `robot_not_stopped` reset rejection in the first
  run. The motion precondition now waits 2.0 s, the same as the supervisor-loss case.
  The 0.20 s stop bound (A §16.3) is unchanged.
- **Missing-participant probe:** it now requires a stationary world first, and the
  rejection must name the missing participant.
- **Physical-crossing worker:** it records bus pose, speed and safety reason on
  failure. Its unowned-approach window is 20 s of wall time. Run standalone, it passed
  12/12, with the bus stopped at x=4.02 m for `crossing_not_owned`.
- **Supervisor:** it publishes the reset hold immediately and reports
  `reset_in_progress` while holding. `/hub/safety` stays 10 Hz (A §5 p7).
- **`scenario_runner`:** reset service, reset observations and the 20 Hz step each
  have their own callback group, and snapshots that arrive out of order are rejected.
  Evaluator-only truth is now published every step (20 Hz). The seeded observation
  noise is untouched.
- **Internal reset deadline:** 0.9 s, inside the 1 s client timeout (A §7.1 p10).

Package tests: `colcon test` for `smart_hub_sim`, `smart_hub_safety` and
`smart_hub_tests` gave 65 tests, 0 failures. `git diff --check` passed.

Full `scripts/verify_m2.py` on the committed tree:
[`evidence/mandatory-m2-038695b.json`](../evidence/mandatory-m2-038695b.json),
status **FAIL**, 17/18.

- `scenario_reset_acceptance` failed. Seed 99 reached `RESET_DEADLINE` at 0.951 s
  against the 0.9 s internal deadline.
- Every other case passed. Adapter stops after supervisor loss were 0.44–0.63 s
  (bound 0.65 s). E-stop latency was 0.035–0.079 s.
- Host load average was 8.3–12.8 during the run, on 18 CPUs, with a desktop session
  and IDE active after a reboot.

Six earlier full runs used intermediate uncommitted trees. They scored 15–17/18 and
are not acceptance evidence. Two of them missed the 0.65 s adapter bound by 1–9 ms
(0.651 s and 0.659 s). That bound has no margin: 0.5 s command timeout + 0.05 s step
+ truth sampling.

Next steps:
1. Rerun on a quiet host.
2. If failures persist, profile `scenario_runner` step jitter before changing any
   threshold.

M2 repeatability, M3 and M4 remain NOT RUN on this revision. See the
[compliance register](compliance.md) for every unimplemented assignment item.

## M6 robot_manager work in progress — 2026-10-25

This is on branch `feat/m6-robot-manager` and is **not accepted**.

**Added**
- `robot_manager` (`smart_hub_control/robot.py`) serves `/robot/navigate_to`, `/robot/escort` and
  `/robot/confirm_ready` (A §7.2, §14). It implements the escort state machine, readiness accepted
  only in WAIT_READY with a 20 s timeout, arrival within 0.20 m held 1 s, crossing token handling,
  replanning on a blocked or stale edge, NO_ROUTE, stale-odometry and planner-loss aborts, and
  reset hooks.
- Simulator: an `m6_mode` parameter and a test-only `publish_robot_odom` fault switch.
- `m6.launch.py`, and `robot_manager` added to the integrated launch.
- `scripts/verify_m6.py` covers T11–T14 and supports `--case NAME`.

**Changed**
- The reset workflow now runs independent participants concurrently: robot+bus prepare,
  parking+traffic, and bus+robot finish. It calls `/sim/reset_world` in-process.
- New parameter `reset_deadline_sec` ([D11](decisions.md)): 0.9 s for the M2 graph, 2.0 s with mission
  managers. Verifier reset clients now wait 3 s.

**Checks**
- `colcon test`: 92 tests, 0 failures. `check_docs` and `git diff --check` pass.
- T11 debug run PASS: 60 requests over 20 configurations, all matching the oracle, p95 0.066 s. This
  ran before the reachable-node fix.
- Every case that starts with a scenario reset fails on the dev VM. Single reset hops took
  0.11–0.57 s at load 3–11, and the bus finish-reset check timed out. T12–T14 therefore remain
  **NOT RUN**.

**Cause and next step:** this is attributed to VirtualBox-on-Hyper-V vCPU scheduling (see
[vm-host-repair](vm-host-repair.md)). The next step is a predictable host: fewer vCPUs, native
Linux or WSL2.

### Update — 8 vCPUs (2026-10-25, 17:20)

The VM was reduced from 18 to 8 vCPUs and the desktop locale was fixed. The effect:

- The full 8-participant reset completed in 0.012–0.017 s. With 18 vCPUs it took 0.9–2.1 s.
- Load average stayed below 1.1.

The cause was VirtualBox vCPU over-allocation, not the reset logic. Keep this VM at 8 vCPUs for
timing runs.

Bug found and fixed (`1218e30`): at W the robot turned north (`copysign(pi/2, 0.0)`) and timed out.
Heading is now chosen by the dominant axis. `bus.py` contains the same rule but never approaches a
turn horizontally on its route, so it was left unchanged.

`nominal_escort_01`, debug run on 8 vCPUs, **PASS**:

| Measure | Value |
|---|---|
| Final error, max over 1 s | 0.04 m |
| Final speed | 0 |
| Crossing conflicts | 0 of 614 inside-C samples |
| Feedback interval | p50 0.500 s, p95 0.503 s, max 0.522 s |
| Mission time | 97 s |

This is one run, not T13. The full `verify_m6.py` run (10 escorts, T14, T12, T11) was started; its
result lands in `.cache/m6full/run1.json` and still needs recording. T12–T14 remain **NOT RUN**
until that result is recorded.

### M6 full run PASS — 2026-10-25 17:41

`scripts/verify_m6.py` passed **18/18** at `1218e30` on 8 vCPUs, taking 1290 s
([evidence](../evidence/m6-1218e30.json)).

| Test | Result |
|---|---|
| T13 | 10/10 escorts. Final error 0.04 m, 0 crossing conflicts, feedback p95 ≤ 0.507 s. |
| T14 | Busy and duplicate goals rejected. No readiness aborts after 20.05 s without moving. Cancel reaches a zero command in 0.008 s. Unreachable goals rejected. Frozen odometry stops the robot within 1.05 s. A blocked Cs–J edge forces a detour through B. |
| T12 | NO_ROUTE aborts, and nothing restarts after the road is restored. |
| T11 | 60 requests (48 with a route) all match the oracle, p95 9.6 ms. |

This is a single run, so no repeatability claim is made.

**Added afterwards (package tests: 94 tests, 0 failures; no ROS run yet):**
- The three A §17 parameters.
- A congestion-only replan rule in the robot, which must save at least 15% and waits at least 2 s between switches.
- `hub.launch.py` with `scenario`, `seed` and `mode`, plus `scenarios/S1–S9.yaml`.
- `metrics_logger`.
- An RViz image, config and demo script (`containers/Dockerfile.rviz`, `scripts/rviz_demo.sh`). The image has not been built.

M4 and M6 need re-runs because their code changed.

### M4 regression and first S1 run — 2026-10-25 17:58

Both ran at `3da2614` on 8 vCPUs, in parallel.

**M4: PASS 9/9** ([evidence](../evidence/m4-3da2614.json)). This was the first run with the new A §17
parameters and the dispatch fallback. T07–T10 passed again.

**S1: FAIL** ([evidence](../evidence/s1-3da2614.json)).
- What worked: the reset fix let the run complete.
- The defect: the stable counts were 0 → 3 → **4** → **3**, against the expected 0 → 3 → 5 → 4. The
  detector consistently misses one of the five synthetic queue tracks. Root cause not yet found.
- Status: T01/T02 remain FAIL / NOT RUN.

### S1 counting fixed — 2026-10-25 18:07

**Cause:** synthetic passengers were drawn 0.58 m apart, which at 13.25 px/m is 7–8 px. That is
the same as the 7 px disc width, so neighbouring discs touched. The 4-connected blob finder then
merged passengers 3 and 4.

**Fix:** passengers are now drawn 0.65 m × 0.70 m apart, at least 8 px between discs, and at most
18 are drawn, all inside Q.

**Result:** `verify_s1.py` PASS twice ([run 1](../evidence/s1-fix-run1.json),
[run 2](../evidence/s1-fix-run2.json)).

| Check | Result |
|---|---|
| Stable counts | 0/3/5/4 |
| 0.3 s occlusion | no double count |
| Pedestrian in C | detected |
| Camera freeze at 30 s | invalid by 31.2 s |
| Frozen acquisition stamp | detected |

The A §8 ≥100-frame annotated video evaluation remains **BLOCKED**: there is no team video yet.

### M2 PASS twice on 8 vCPUs — 2026-10-25 18:09

`scripts/verify_m2.py` passed **18/18** in two separately recorded runs at `4867e82`
([run 1](../evidence/m2-8vcpu-run1-4867e82.json), [run 2](../evidence/m2-8vcpu-run2-4867e82.json)).
Load average stayed below 1.3.

| Measure | Result | Limit |
|---|---|---|
| E-stop to zero command | 0.010–0.011 s | 0.20 s |
| Adapter stop after supervisor kill | 0.45–0.50 s | 0.65 s |

This meets the M2 requirement of two complete, separately recorded passes. The earlier 17/18 results
came from the 18-vCPU VM configuration.
