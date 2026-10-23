# Dependency-ordered execution plan

No deadline or available team hours have been confirmed. Use acceptance gates before choosing calendar dates. M0 tooling and local ROS smoke checks pass, with independent review/reproduction BLOCKED (see [status](m0-status.md)); M1 source and verification are tracked in [M1 status](m1.md); M2 implementation and automated acceptance are PASS after [PR #5](https://github.com/smart-mobility-lab-team-C/smart-mobility-hub/pull/5) merged at `6c25993525bf083214c14fdbb8abab224a5a75bd` (see [evidence index](evidence.md#m2-implementation-closure-2026-10-23)). Historical hosted M3/T05–T06 PASS results are recorded in [M3 status](m3.md); the current local campaign passed two nominal missions, then the third failed with `SAFETY_STOP` after a safety-observation gap. Independent source review and teammate reproduction remain BLOCKED because the project currently has one contributor. M4 implementation is pushed to `main`; the local Jazzy build, package tests and M2 real-node regression pass. The local Cyclone profile passed resets, but the full M3 campaign hit a safety-observation gap, so M4 T07–T10 remain NOT RUN (see [local result](../evidence/m4-local-cyclone-attempt.json) and [M4 handoff](m4-handoff.md)). M5–M8 and all other T01–T18 scenario rows remain NOT RUN. Proposed owners are roles, not named assignments.

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
Historical hosted evidence is retained with its original environment. The VM
observation-gap investigation remains relevant to local execution; see the
[current diagnostic](m3-gap-diagnostic.md#investigation-reopened--2026-10-24).
M4 software and acceptance tooling are on `main`. The next local run will use one
active simulation campaign, retain reset phase timings if the failure recurs,
and preserve the one-second reset deadline. The local full run passed M2 and two M3 docking missions, then stopped on a
0.888-second gap in safety-state observations. Publisher/executor delay versus
DDS delivery delay remains unresolved; M4 scenario acceptance remains NOT RUN. See the [M4 handoff](m4-handoff.md).

## Work cycle

For each gate: create issue → inspect dependencies → Codex implements one bounded task → execute checks → inspect simulation/evidence → PR review → merge by integration owner → update status.

Track per day: requirements verified/total; test PASS/FAIL/BLOCKED/NOT RUN; unresolved blockers and age; evidence completeness; clean reproduction status. Generated lines and file counts are not completion metrics.

## Schedule method

After M0/M1, estimate remaining person-hours per gate. Assign an owner and reviewer, record available hours, then work backward from the confirmed deadline with a fault-fixing and packaging buffer. The earlier 14-day estimate is not a confirmed commitment.

## First three work items

1. Complete M0 on one Windows computer and preserve its installation transcript.
2. Review contracts and map against both PDFs, resolving any extraction ambiguity.
3. Build M1 and run real ROS interface/build checks before dividing node implementation.

