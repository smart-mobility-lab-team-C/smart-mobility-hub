# Team handoff (2026-10-25)

Concise status for teammates picking up the project. Facts come from the
verification runs listed below; anything not run is marked NOT RUN.

## Current state

- `main` is at `befb826`, which merges `feat/m6-robot-manager`.
- Course PDFs are untracked and ignored (local only). They were removed from
  GitHub history; do not re-add them.
- New since the last review:
  - `robot_manager` services `/robot/navigate_to`, `/robot/escort`,
    `/robot/confirm_ready`; A9.3 observed-queue fallback dispatch.
  - Staged reset with `reset_deadline_sec` (0.9 s M2, 2.0 s with mission
    managers; D11). A17 parameters `reservation_ttl_sec`,
    `congestion_density_threshold`, `replan_improvement_ratio`.
  - `hub.launch.py scenario:=S1..S9 seed:= mode:=` (hardware mode refuses);
    scenarios in `src/smart_hub_bringup/scenarios/S1-S9.yaml`.
  - `metrics_logger` writes `events.jsonl`, `metrics.csv`, `summary.json`.
  - RViz demo launcher and scenario driver.

## How to run

**Machine prerequisites.** Use the 8 vCPU dev VM. On the old 18 vCPU VM, ROS
service calls took 0.13–0.6 s and resets failed. Before any timing run:

```bash
nproc      # must print 8
uptime     # load should be low
```

Close Firefox and VS Code before acceptance runs.

**Build and test.** Docker image `smh-m4-local`; workspace under
`.cache/m2fix-*`. The exact commands are in the README section "Build and test".

**Demo / RViz.**

```bash
docker build -t smh-rviz -f containers/Dockerfile.rviz .   # once
ROS_DOMAIN_ID=42 bash scripts/rviz_demo.sh                  # terminal 1
bash scripts/demo_scenario.sh <case>                        # terminal 2
```

Cases: `nominal_escort_01`, `blocked_edge_detour`, `cancel_while_moving`,
`no_route_then_restore`, `readiness_timeout`, `frozen_robot_odometry`.

**Video footage (headless).** `scripts/record_demo.sh` records one case in two
phases. First it runs the real verifier case with a ROS bag of `/hub/markers`,
`/hub/events` and `/hub/safety`, with no rendering. Then it replays the bag
into RViz on a virtual 1920×1080 screen (Xvfb) and encodes `clip.mp4`. The left
1280 px show RViz and the right 640 px show the event log. A caption gives the
case and the verifier result. It does not need the desktop or Wayland.

```bash
docker build -t smh-record -f containers/Dockerfile.record .   # once, after smh-rviz
bash scripts/record_demo.sh <case>                              # run + render
bash scripts/record_demo.sh --render .cache/demo/<run>          # re-render only
```

Output in `.cache/demo/<time>-<case>/` (git-ignored): `result.json`, `bag/`,
`cues.csv` (event times in seconds since bag start, matching the on-screen log)
and `clip.mp4` (no audio). Members add voice and webcam footage in their own
editor. A clip shows only what that run did; check the caption before using it.

## Results

Each status reflects a single run unless noted. Nothing has been repeated yet.

| Area | Status | Evidence | Notes |
|---|---|---|---|
| M6 verifier T11–T14 (and full 18/18 run) | PASS (1 run) | `evidence/m6-1218e30.json` | Route oracle 60 req, p95 9.6 ms. T12 NO_ROUTE. T13 10/10 escorts, 0.04 m error, 0 crossing conflicts. T14 all failure cases. |
| M4 regression T07–T10 | PASS (1 run) | `evidence/m4-3da2614.json` | 9/9 at `3da2614`. |
| M2 safety/reset | PASS (2 runs) | `evidence/m2-8vcpu-run1-*.json`, `evidence/m2-8vcpu-run2-*.json` | 18/18 twice on 8 vCPUs; E-stop 0.010 s, adapter stop 0.45–0.50 s. |
| S1 passenger counting (synthetic) | PASS (2 runs) | `evidence/s1-fix-run1.json`, `evidence/s1-fix-run2.json` | Counts 0/3/5/4, occlusion, crossing, freeze invalid by 31.2 s. Earlier FAIL (0/3/4/3) was a drawing-spacing bug, fixed. |
| Congestion replan (robot) | NOT RUN | — | Not ROS-verified. Rule: at least 15% cheaper, at least 2 s, never in state C. |
| metrics_logger | NOT RUN | — | Not ROS-verified. |
| A9.3 fallback dispatch | NOT RUN | — | Not ROS-verified. |
| Demo footage, six M6 cases (2026-10-27) | 6 PASS, 1 FAIL | `.cache/demo/` (local, not committed) | Single `verify_m6.py --case` runs while recording a bag. Five cases PASS on the first try. `nominal_escort_01` FAILED once with `SAFETY_INPUT_UNKNOWN:door_stale` at 106 s (door input older than 0.5 s), then PASSED on the next run. Cause not investigated. |

## What is not verified

- No ROS integration test covers congestion replan, `metrics_logger`, or A9.3
  fallback dispatch.
- S1 video-frame evaluation (A §8) is BLOCKED until annotated video exists.
- M2 passed twice on 8 vCPUs; M3 has not been rerun on 8 vCPUs.
- S2, S8 and S9 have no ROS test results.
- No result has been repeated. Acceptance needs two clean repeat passes.
- An intermittent `door_stale` safety hold ended one `nominal_escort_01` run
  (2026-10-27, demo recording). It has not been reproduced or diagnosed, and
  bag-recording load has not been ruled out.
- The annotated S1 video (at least 100 frames) has not been produced.
- The 20–30 minute team video has not been recorded.
- The report is not committed. It is in the leader's Downloads folder
  (`SME_TEAMC_PROJECT-FINAL-revised.docx`) because it contains member names.
  The draft is `docs/report/report-draft.md`. Member names and contributions
  are still to be filled in.

## Next steps

Priority order. Owners are to be assigned by the team.

| # | Task | Owner |
|---|---|---|
| 1 | ~~Debug the S1 missing track~~ done (synthetic T01/T02 PASS ×2) | — |
| 2 | ~~Rerun M2 on 8 vCPUs~~ done (18/18 ×2); rerun M3 on 8 vCPUs | TBD |
| 3 | S2 ROS tests T03/T04, including fallback | TBD |
| 4 | S8 integration T15 (cars, timed schedule, paired predictive/reactive) | TBD |
| 5 | S9 fault suite T16–T18, five phase-varied repetitions | TBD |
| 6 | Two clean repeat passes of everything | TBD |
| 7 | Annotated S1 video, at least 100 frames (team supplies footage) | TBD |
| 8 | 20–30 minute team video with all members | TBD |
| 9 | Teammate review and fresh-checkout reproduction | TBD |
| 10 | Fill member names and contributions in the report | TBD |

Status words stay honest: PASS (1 run), FAIL, NOT RUN, BLOCKED. Do not mark an
untested item PASS.

## Pointers

- `docs/compliance.md`: requirement coverage.
- `docs/test-matrix.md`: T01–T18 definitions.
- `docs/mandatory-scenarios-progress.md`: S1–S9 progress.
- `docs/decisions.md`: decision log (D11 covers the reset deadlines).
