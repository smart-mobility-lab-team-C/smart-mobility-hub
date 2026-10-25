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
