# Acceptance runs

Each folder is one commit; each `runN` is one full pass of `scripts/run_acceptance.sh`
(M2, M3, M4, M6, S1, S2, S8, S9) with a `manifest.json` (commit, host, ROS, Python,
model hash) and `exit-codes.jsonl`. Raw traces stay in `.cache/acceptance/` (not
committed). Failures are kept with their diagnosis; nothing is deleted.

## 0e7a545 (aborted, 2026-11-14)

Stopped during S8. M2, M6 and S2 PASS. M3 and M4 never ran: the runner gave every
verifier the same output folder and they refuse an existing one (runner fault, fixed
in adc7955). S1 FAILed: simulated time drifted behind wall time on this native host
(also at the pre-change commit 8f15c4c); fixed by D22.

## adc7955 (2026-11-14, i3-1215U laptop, native Jazzy, powersave governor)

| Verifier | run1 | run2 |
|---|---|---|
| M2 | PASS 18/18 | FAIL 17/18 |
| M3 | PASS 24/24 | PASS 24/24 |
| M4 | PASS 9/9 | FAIL (setup) |
| M6 | PASS 19/19 | PASS 19/19 |
| S1 | PASS | PASS |
| S2 | PASS 16/16 | PASS 16/16 |
| S8 | FAIL 18/20 | FAIL 19/20 |
| S9 | PASS 30/30 | PASS 30/30 |

Diagnoses:

* **S8 run1 seeds 803 (reactive), 808 (predictive); run2 seed 801 (predictive):**
  "escort without terminal result". The second escort was *rejected* (an explicit
  outcome) right after the obstruction went in; the verifier wrongly counted a
  rejected goal as missing a result. Verifier fault, fixed in 681384a.
* **S8 run2 seed 801 (predictive), 600 bus–O "collisions":** the verifier inserted
  obstacle O at (7, 2) while the bus stood still at (7.56, 2.0), latched since the
  80 s pedestrian. The footprints overlapped from insertion; the bus never moved and
  the supervisor latched `swept_hazard` at once. Verifier fault, fixed in 681384a.
  No episode in either run had a collision caused by motion, an overlapping crossing
  owner, a double allocation or a duplicate dispatch.
* **M4 run2:** `clear_stop` returned `no_active_latch` 7 s in: the supervisor started
  after the probe's asserted startup E-stop and never latched. Verifier start-up race,
  fixed in 681384a.
* **M2 run2, `adapter_stops_after_supervisor_loss`:** trial 3 saw no zero within the
  0.65 s bound (trials 1–2: 0.41 s, 0.43 s; run1: 0.41–0.47 s). The simulator log for
  that run shows step callbacks starting 0.21–0.34 s late and one 0.34 s wait for the
  simulator lock: the process was not scheduled, on a 2 P-core + 4 E-core CPU in the
  powersave governor. Not a logic fault; the bound has no scheduling margin.
