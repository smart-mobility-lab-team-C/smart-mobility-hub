# M3 handoff — 2026-10-23 (KST)

This note captures the active M3 implementation and verification state so work
can resume without reconstructing the run history. M3 policy choices and design
details are in [M3 status](m3.md).

## Current work

- Branch: `feat/m3-bus-mission`, based on merged M2 closure `d58e8f5`.
- Implementation head: `8a3bf7817961d5c19fe270c3ee35342c33e315f9`.
- [Draft PR #7](https://github.com/smart-mobility-lab-team-C/smart-mobility-hub/pull/7)
  is open. It contains route planning, bus docking, passenger boarding, reset
  coordination, fault probes and the CI harness.
- The selected retry, final speed, ETA, edge freshness and boarding policies
  are written in [M3 status](m3.md#authority-and-runtime-policies).
- The current local edit to `docs/m3.md` records that passenger entry/boarding
  timestamps use fixed-step simulation time while door dwell uses monotonic wall
  time. Preserve this clarification.

## Verification state at handoff

**Automated M3 acceptance is unresolved. Do not mark T05/T06 PASS yet.**

- Latest PR checks: tooling, ROS container, M1 and M2 workflows are PASS.
- M3 run [39815691216, attempt 2](https://github.com/smart-mobility-lab-team-C/smart-mobility-hub/actions/runs/39815691216)
  was still `in_progress` when checked at 2026-10-23 01:55 KST. Its combined
  clean Jazzy build, M2 regression and M3 mission step was running. It had not
  uploaded an artifact, so no result from this attempt is established yet.
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

The host VM showed multi-second heartbeat gaps. Their cause is unconfirmed and
watchdog limits were not weakened. Debug runs are not acceptance evidence; raw
traces stay under ignored `evidence/runs/` directories.

## Resume steps

1. Check run 39815691216 attempt 2 and its job steps. If it completed, download
   the attempt's `m3-results` artifact and inspect its commit, source hashes,
   M2 regression report, M3 case summary, parameters and trace hashes. Do not
   use the attempt-1 artifact as a substitute.
2. If attempt 2 failed or remains stuck, preserve the exact result and diagnose
   the first failing case. Distinguish another M2 reset readiness failure from
   any actual M3 mission failure before editing code.
3. Only after current-head hosted evidence completes successfully, add a
   separate hosted evidence record. Preserve the existing local failure and
   hosted attempt-1 failure. Then update M3, plan, test matrix, requirements,
   README and evidence index consistently. Keep the human gate BLOCKED and all
   unexecuted scenario rows NOT RUN.
4. Run `python3 scripts/check_docs.py` and `git diff --check`, review the
   evidence links and status claims, commit the scoped update, and push it to
   PR #7. Do not merge without an explicit instruction.

