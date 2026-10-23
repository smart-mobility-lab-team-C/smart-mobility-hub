# M3 handoff — 2026-10-23 (KST)

This note captures the active M3 implementation and verification state so work
can resume without reconstructing the run history. M3 policy choices and design
details are in [M3 status](m3.md).

## Current work

- Branch: `feat/m3-bus-mission`, based on merged M2 closure `d58e8f5`.
- Checkout head at this handoff update: `7e51a0ff4fc72b95a9a18af59cec0eb05962a4b6`,
  with a local edit to `scripts/verify_m3.py` adding the bounded readiness wait.
- [Draft PR #7](https://github.com/smart-mobility-lab-team-C/smart-mobility-hub/pull/7)
  is open. It contains route planning, bus docking, passenger boarding, reset
  coordination, fault probes and the CI harness.
- The selected retry, final speed, ETA, edge freshness and boarding policies
  are written in [M3 status](m3.md#authority-and-runtime-policies).
- The current local edit to `docs/m3.md` records that passenger entry/boarding
  timestamps use fixed-step simulation time while door dwell uses monotonic wall
  time. Preserve this clarification.

## Verification state

**Automated M3 acceptance is unresolved. Do not mark T05/T06 PASS yet.**

- Latest PR checks before the verification edit: tooling, ROS container, M1 and
  M2 workflows are PASS.
- M3 run [39815691216, attempt 2](https://github.com/smart-mobility-lab-team-C/smart-mobility-hub/actions/runs/39815691216)
  completed FAIL. The clean build, quality checks, 23 interface inspections,
  40 colcon tests, 18 M2 real-node cases and ten nominal docking runs passed.
  `arrival_during_boarding_and_interruption` failed because the next goal was
  rejected before the probe observed the separate supervisor-clearance update.
  Its trace shows the measured door closing at monotonic 928.882 s and the
  supervisor publishing `motion_permitted=true`, `stop_latched=false` at 928.928 s.
  Artifact and trace hashes are recorded in
  [the M3 verification index](../evidence/m3-verification-attempts.json).
- Attempt 1 of that same run failed before M3 missions: the unchanged M2
  `reset_missing_participant` regression did not observe restored participants
  in time, and a subsequent adapter supervisor-loss trial consequently ran
  while safety remained in reset. The M3 source did not change M2 runtime or
  `scripts/verify_m2.py`.
- That failed attempt still built all packages and passed 40 colcon tests.
  Retain the failure in the record even if the rerun passes.
- A later local development probe on current source `8a3bf78` also rejected a
  nominal goal before motion. Its host-input cause is unresolved; this run is
  diagnostic only and is not in the concise local acceptance index. Ten focused
  routing/passenger tests passed, including the new ETA-region check.
- The clean local run at source `28e7c38` passed build, lint, 23 interface
  inspections, 39 colcon tests and all 18 M2 real-process regressions. It failed
  at initial reset (`queue_stale`) before sending an M3 goal. The complete local
  M3/T05/T06 acceptance therefore remains unestablished. See
  [local result](../evidence/m3-local.txt) and
  [local index](../evidence/m3-local.json).
- Earlier hosted source `1a5fdb5` passed 24 M3 cases including ten nominal
  runs, but predates the current ETA/crossing ownership correction. It is useful
  diagnostic evidence only, not acceptance for the current source.
- Independent source review and teammate reproduction remain BLOCKED because
  there is one contributor. Full T01–T18 acceptance remains NOT RUN apart from
  any specific milestone probes explicitly recorded as complete.

- Local clean run `m3-readiness-20261023-rerun1` passed build, quality,
  23 interface inspections, 40 colcon tests and all 18 M2 real-node regression
  cases, then failed its first M3 reset with `PARTICIPANT_UNAVAILABLE`, before
  any docking goal. It ran against base commit `7e51a0f` with the local readiness
  probe edit. The result, trace and transcript hashes are indexed in
  [the M3 verification index](../evidence/m3-verification-attempts.json).
- Clean run `m3-0588216-20261023-rerun` on commit `05882166ca9a8cda9b8929f3ed2286cb5a330fcd`
  passed build, quality, 23 interface inspections, 40 colcon tests and all 18
  M2 cases. Its first nominal M3 goal ended with `SAFETY_STOP` after a 17.0 s
  local observation gap; the trace records `vehicles_stale` followed by
  `crossing_unknown`. This is a FAIL for that attempted mission and does not
  establish the readiness-probe case. The trace and result hashes are indexed.
- The probe now waits up to 2 s for fresh door, bus-truth and supervisor samples
  before the boarding-interruption goal. It records the last observed state and
  age on timeout. The runtime remains unchanged, so an immediate goal in an
  inhibited supervisor state is still rejected.

The host VM showed multi-second heartbeat gaps. Their cause is unconfirmed and
watchdog limits were not weakened. Debug runs are not acceptance evidence; raw
traces stay under ignored `evidence/runs/` directories.

## Resume steps

1. Push the scoped readiness-probe commit to PR #7 and inspect the hosted clean
   Jazzy run. The two latest local failures occurred at reset and during a
   nominal mission, before the boarding-interruption probe ran.
2. Only after all 24 cases pass, add a successful evidence record with source
   commit, environment, parameters, metrics and artifact hashes. Preserve every
   earlier failure. Then update M3, plan, test matrix, requirements, README and
   evidence index consistently; keep the human gate BLOCKED and unexecuted
   scenario rows NOT RUN.
3. Run `python3 scripts/check_docs.py` and `git diff --check`, review status
   claims and artifact links, commit the scoped update, and push it to PR #7.
   Mark PR #7 ready for review after successful verification; do not merge.

