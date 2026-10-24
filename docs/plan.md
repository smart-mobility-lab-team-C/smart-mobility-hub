# Dependency-ordered execution plan

No deadline or available team hours have been confirmed. Use acceptance gates before choosing calendar dates. M0 tooling and local ROS smoke checks pass, with independent review/reproduction BLOCKED (see [status](m0-status.md)); M1 source and verification are tracked in [M1 status](m1.md); M2 implementation and automated acceptance are PASS after [PR #5](https://github.com/smart-mobility-lab-team-C/smart-mobility-hub/pull/5) merged at `6c25993525bf083214c14fdbb8abab224a5a75bd` (see [evidence index](evidence.md#m2-implementation-closure-2026-10-23)). The latest local M3 run passed 24/24 checks, including 10/10 nominal docking runs and T05–T06, after 53 package tests passed. Its completion changes are on `fix/m3-local-completion`, not merged or pushed. Earlier local M3 failures remain historical (see [local evidence index](../evidence/m3-local-completion.json)). M4 implementation remains on `main`; local M4 T07–T10 are the next acceptance gate and remain NOT RUN. Independent source review and teammate reproduction remain BLOCKED. M5–M8 and all T01–T18 rows other than T05–T06 remain NOT RUN. Proposed owners are roles, not named assignments.

| Gate | Deliverable | Acceptance | Owner role |
|---|---|---|---|
| M0 | WSL, Git authentication, Codex, ROS bootstrap | Rerun-safe installation; talker/listener; version log; branch push | Integration |
| M1 | Source review, M1 map/config, exact interface package, package skeleton | Reviewed contracts; clean colcon build; interface inspection | Integration + all |
| M2 | Seeded simulator, observations, safety, adapter watchdog, crossing arbiter | Zero startup motion; stale command stop; exclusive physical crossing; reset acknowledgement | Safety |
| M3 | Route service and first bus mission | Docking with door interlock, feedback, cancellation, timeout; T05–T06 | Bus/routing |
| M4 | Parking and congestion | T07–T10; atomicity, expiry, stale state | Parking/traffic |
| M5 | Perception and trained predictor | T01–T04; 100 annotated frames; held-out baseline comparison | Perception |
| M6 | Robot navigation and escort | T11–T14; route oracle, no-route, readiness, cancellation | Robot/routing |
| M7 | Concurrent coordination and faults | T15–T18 plus regression of earlier tests; paired seeds | All/integration |
| M8 | Evidence, report, video, clean reproduction, packaging | Submission audit; fresh checkout reproduced by another member | All/leader |

Route service starts in M3 and gains its full oracle suite in M6. Safety is required from M2; do not wait until M7 to implement it.

Local Ubuntu 24.04/Jazzy Docker verification is the default under the user's
2026-10-24 instruction; GitHub Actions is optional project tooling, not a recorded
professor requirement. See the [verification policy](automation.md#local-verification-default).
Historical hosted and failed local evidence retain their original environment
and outcomes. The earlier observation-gap investigation remains useful context;
see the [diagnostic record](m3-gap-diagnostic.md#investigation-reopened--2026-10-24).
The latest local M3 acceptance passed; M4 software and acceptance tooling are on
`main`, while the M3 completion changes remain unmerged on
`fix/m3-local-completion`. M4 T07–T10 remain NOT RUN pending the next full local
M4 run. See the [M4 handoff](m4-handoff.md).

## Work cycle

For each gate: create issue → inspect dependencies → Codex implements one bounded task → execute checks → inspect simulation/evidence → PR review → merge by integration owner → update status.

Track per day: requirements verified/total; test PASS/FAIL/BLOCKED/NOT RUN; unresolved blockers and age; evidence completeness; clean reproduction status. Generated lines and file counts are not completion metrics.

## Schedule method

After M0/M1, estimate remaining person-hours per gate. Assign an owner and reviewer, record available hours, then work backward from the confirmed deadline with a fault-fixing and packaging buffer. The earlier 14-day estimate is not a confirmed commitment.

## First three work items

1. Complete M0 on one Windows computer and preserve its installation transcript.
2. Review contracts and map against both PDFs, resolving any extraction ambiguity.
3. Build M1 and run real ROS interface/build checks before dividing node implementation.

