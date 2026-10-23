# M3 handoff — 2026-10-23 (KST)

M3 implementation and automated acceptance are **PASS**. T05 and T06 are
**PASS** after the hosted real-node run. M4 is the next implementation milestone.
The policies and evidence are in [M3 status](m3.md) and the
[M3 attempt index](../evidence/m3-verification-attempts.json).

## Accepted hosted run

- [PR #7](https://github.com/smart-mobility-lab-team-C/smart-mobility-hub/pull/7)
- [Hosted M3 run](https://github.com/smart-mobility-lab-team-C/smart-mobility-hub/actions/runs/39962241472)
- Tested PR head: `15220d9f7110a93a8229b180ed8f0349d053701a`; workflow checkout commit:
  `c30d131c438ccaa255ed4c254e452912e223ca5f`; clean worktree.
- Environment: Ubuntu 24.04.5, ROS Jazzy, Python 3.12.3, container image
  `sha256:9be9a18be6e76159908731cf386651eee0c917d060de5abf37036e5624e3871b`.
- All five PR workflows passed: tooling, ROS container, M1, M2 and M3.
- Clean pipeline: build and quality PASS; 23 interface inspections PASS; 40
  colcon tests PASS with zero errors/failures/skips; 18 M2 real-node regressions
  PASS; all 24 M3 cases PASS.
- Ten nominal docking runs passed at seeds 300–309. Maximum position error was
  0.05 m, maximum yaw error below 1e-9 rad, and maximum ETA error at 5 m was
  0.600 s. Measured door-open duration was 8.096–8.207 s. Boarding-interruption
  cancellation completed in 0.0252 s; approach cancellation completed in
  0.0208 s. Both are below the 0.5 s limit.
- The artifact `m3-results` (ID `12506307537`) contains the trace, case report,
  seven parameter dumps, package versions and build/test logs. The attempt index
  records artifact hashes and the selected parameter values.

## Readiness probe and retained failures

The boarding-interruption probe now waits up to 2 s for fresh closed-door,
stopped-bus and supervisor-clearance observations before sending the next goal.
It records each value and receipt age; a timeout includes the last observed
state. Bus runtime rejection behavior and all watchdog limits are unchanged.

Earlier failed attempts remain indexed with their original results: the hosted
attempt before this change passed ten nominal runs but failed the interruption
goal; the first local rerun failed its initial M3 reset with
`PARTICIPANT_UNAVAILABLE`; the second local rerun stopped at `SAFETY_STOP` after
a 17.0 s observation gap. A separate older local failure at `queue_stale` and
the first attempt of hosted run 39815691216 are also preserved. That attempt
failed M2 cases `reset_missing_participant` and
`adapter_stops_after_supervisor_loss` before M3 ran. These failures were not
combined into the successful hosted result.

Independent assignment/source review and a different member's clean-checkout
reproduction remain **BLOCKED** because there is one contributor. These human
gates are separate from hosted automated acceptance. T01–T04 and T07–T18 remain
**NOT RUN**; M3 probes do not close those scenario rows.

## Next work

Start M4 parking and congestion work according to [the dependency plan](plan.md).
Keep PR #7 unmerged until an explicit merge instruction. Preserve all prior run
artifacts and update the evidence index with any new reproduction or review.
