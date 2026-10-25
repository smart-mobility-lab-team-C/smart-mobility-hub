# Requirements traceability

Sources inspected: Smart_Mobility_Hub_Assignment (1) (1).pdf (A); Smart_Mobility_Hub_ROS2_Implementation_Handbook (1).pdf (H); newer instructor announcement supplied in conversation (N). Page numbers below refer to printed assignment pages.

Original PDFs are not published in this public repository. Keep authorized local copies available for Codex contract review. Do not upload course material or identifiable footage publicly without permission. H supplies implementation guidance; A defines assessed technical behavior; N updates submission rules.

| ID | Source | Required behavior | Intended implementation | Verification/evidence |
|---|---|---|---|---|
| R01 | A §§1–4 pp2–6 | Integrated deterministic Python/rclpy simulator; M1 geometry and agent constraints | Simulator/config/launch | Seed replay, map and footprint checks |
| R02 | A §§5–7 pp7–13 | Exact topics/messages/services/actions, rates, QoS and frames | Interface package + nodes | Build, interface inspect, launch tests |
| S1 | A §8 p14 | Tracking, queue counting, crossing occupancy, stale feed handling; real-video evidence | passenger_detector | T01–T02; >=100 annotated video frames; exact stable synthetic counts; video MAE <=1 |
| S2 | A §9 p15 | Trained 30-second forecast, persistence comparison, safe dispatch | demand_predictor + coordinator | T03–T04; held-out episodes; MAE <= persistence; inference p95 <100 ms |
| S3 | A §10 p16 | Arrival/docking, stopped-door interlock, feedback/cancel | bus_manager | T05–T06; 10/10; <=0.20 m, <=0.17 rad, 1 s hold |
| S4 | A §11 p17 | Atomic reservations, sensing, idempotency, expiry/release | parking_manager | T07–T08; 20 pairs, zero double allocation |
| S5 | A §12 p18 | Congestion, blocked and UNKNOWN/stale states | traffic_monitor | T09–T10; labels, transition timing, recovery logs |
| S6 | A §13 p19 | Cost-aware route/replan and explicit NO_ROUTE | route_planner | T11–T12; 20 seeds, oracle within 1e-6 relative tolerance; p95 <250 ms |
| S7 | A §14 p20 | Readiness, navigation/escort, cancellation/failures | robot_manager | T13–T14; 10/10 nominal; <=0.20 m |
| S8 | A §15 p21 | Concurrent coordination, exclusive crossing and policy comparison | hub_coordinator | T15; 10 paired seeded episodes; zero conflicts/collisions |
| S9 | A §16 p22 | Latched stop, independent watchdogs, stale/service failure and deliberate recovery | safety_supervisor + adapters | T16–T18; <=0.20 s stop command; fault repetitions |
| R03 | A §17 p23 | Exposed validated scenario parameters | Config + startup validation | Saved final parameter dump |
| R04 | A §21 pp29–30 | Actual metrics, repeatable runs and independent evaluation | Test/evidence pipeline | Raw run records and aggregates |
| R05 | A §§24–25; N | Report, direct uploads, source/data ZIP and individual contributions | Submission staging | Packaging audit and member validation |
| R06 | N | 20–30-minute all-member video, full code walkthrough/results/demos | Recording plan | Duration and participation check |
| R07 | N | <=10 files; <=1 GB each; no external links; leader upload, others validate | Packaging + portal process | Size/link audit and validation record |

This is the initial traceability register. Current implementation and observed checks are recorded in [M0 status](m0-status.md), [M1 status](m1.md), [M2 status](m2.md), [M3 status](m3.md), and [M4 handoff](m4-handoff.md). The first combined local acceptance at `58f5afee` passed M2 18/18, M3 24/24 and M4 9/9, with a fresh build and 54 package tests. A repeat at the same implementation commit passed M2 but failed M3 nominal seed 309 on `SAFETY_INPUT_UNKNOWN:estop_stale`; M4 was NOT RUN. This indicates the combined result is not yet repeatable. See the [first run](../evidence/m234-combined-20261025.json), [repeat result](../evidence/m234-repeat2-20261025.json), [local M4 evidence](../evidence/m4-local-completion.json), and [local M3 evidence](../evidence/m3-local-completion.json). Independent review remains BLOCKED. The M3 completion changes from `fix/m3-local-completion` are merged into local
`main` and published to `origin/main`. M4 changes are merged into local `main` from `fix/m4-local-completion` and published to `origin/main`. Other assignment scenario rows remain NOT RUN and require their own verification.

## Mandatory source-review gate

Before M1 is frozen, transcribe M1 node coordinates, graph directionality/agent restrictions, footprints, velocities, clearance and freshness thresholds from A §§2–3; compare interface details against A §§5–7; review scenario-specific algorithms in §§8–18. This register is an implementation map, not a replacement for those contracts. Preserve source section/page next to every resulting configuration and test criterion.

Exact source details not yet represented in configuration must remain open; no guessed defaults may be promoted to requirements.

## Verification environment and source of policy

The assignment requires repeatable tests and measured evidence; the reviewed
requirement register contains no requirement to use GitHub Actions. Hosted CI was
a project tooling choice. The user's 2026-10-24 instruction makes local
Ubuntu 24.04/Jazzy Docker execution the default and requires documentation to be
updated whenever such workflow choices change. Hosted execution requires an
explicit request or a cited instructor requirement. See the [local verification
policy](automation.md#local-verification-default). Historical hosted results keep
their original provenance and do not establish local-machine acceptance.
