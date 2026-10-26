# Decisions and open items

| ID | Decision | Reason | Status |
|---|---|---|---|
| D01 | Codex and ROS inside WSL2 Ubuntu 24.04 | Shared Linux runtime on Windows | Superseded for the development host by the M0 update below (VirtualBox Ubuntu 22.04 + Ubuntu 24.04/Jazzy container); WSL remains the documented teammate path |
| D02 | ROS 2 Jazzy + rclpy | Assignment preferred distribution | Planned |
| D03 | Deterministic 2D baseline before optional extensions | Required scope and reproducibility | Planned |
| D04 | Safety supervisor and adapter watchdog from early integration | Independent stop paths | Required |
| D05 | Newer 20–30-minute video rule (N) overrides the 8-minute demo in A §24.1 p33 and H §7.3 p16 | Instructor announcement | Documented |
| D06 | Development links allowed in Git; separate link-free submission staging | Direct-upload submission rule | Planned |
| D07 | Branch + PR for documentation and code changes | Reviewable change to team repository | Adopted; merges remain a human decision |
| D08 | Course PDFs kept as local ignored copies, not tracked | A/H are course material in a public repository | Untracked 2026-10-25; still present in pushed history of `be224bb` until an approved rewrite |
| D09 | Public reset uses an internal 0.9 s deadline | A §7.1 p10 sets a 1 s client timeout; a failure must reach the client before it | Adopted 2026-10-25 (`038695b`); M2 still FAIL |
| D10 | Evaluator-only ground truth published every 20 Hz simulator step | Finer stop-time measurement; topic has no assignment rate; `/hub/vehicles` stays 10 Hz | Adopted 2026-10-25 (`038695b`) |
| D11 | `reset_deadline_sec` parameter: 0.9 s for the M2 graph, 2.0 s when bus/robot mission managers participate (max 2.0 s) | A sets no reset deadline; 0.9 s derived from the generic 1 s client timeout (A §7.1 p10). The 8-participant M6 handshake measured 0.83 s through four of six stages on the dev VM (prepare 0.38, safety 0.24, crossing 0.11, world 0.09 s) | User decision 2026-10-25; verifier reset clients wait 3 s |
| D12 | Retrain the S2 forecaster on the A §9.2 feature vector with no elapsed-time input; episodes randomise arrival rates, rushes and boardings; 50 episodes split 30/10/10 | The previous model used time since episode start, and every episode shared a fixed timetable. That let it learn the schedule, which A §9.2 p15 forbids as an online input | User decision 2026-10-27 (retrain to spec); held-out MAE 2.46 vs persistence 2.80 |
| D13 | `demand_predictor` parameter `forecast_model` (`ridge` default, `persistence`) | A §9.4 p15: a worse model must stay visible and the baseline must be selectable safely | Adopted 2026-10-27 |
| D14 | The coordinator queues every received forecast and counts each one once, in order, on its 1 Hz dispatch tick | The 1 Hz timer and 1 Hz forecasts drift, so counting ticks could double-count a forecast or drop the low value in a 7, 7, 5, 7 sequence. A §9.3 requires three consecutive valid predictions | Adopted 2026-10-27; T04 verified with probe-published forecasts |

## Needed before implementation freeze

Still open on 2026-10-25 unless noted. Assignment gaps are tracked in the [compliance register](compliance.md).

- Submission date/time/timezone.
- Final TEAMNAME and members' GitHub handles.
- Teammate machine resources (development host is recorded in [M0 status](m0-status.md)).
- Available hours and confirmed owner/reviewer per role.
- Authorized real video and annotation responsibility.
- Independent (human) source interface/map review; agent transcription is done in [M1](m1.md).

No performance measurements, test passes, installation success or calendar commitments are established by this documentation.


## M0 execution update

D01 is superseded for the current machine: user selected the existing Oracle VirtualBox Ubuntu 22.04 host. Run Jazzy in an Ubuntu 24.04 container; preserve host OS. M0 only is authorized now. Scoped PRs may merge after actual checks and independent review pass. See [M0 workflow](m0.md) and [status](m0-status.md). No repository permissions are changed.

## M1 decisions (2026-10-22)

M1 is authorized by the current implementation request, superseding the earlier
M0-only scope statement. Adopt the user's approved derived coordinates, no team
namespace, YAML map, Python package boundaries, and synchronized nested headers.
Preserve assignment service direction for readiness despite handbook wording.
Use geometric intersection for all crossing edges, including W–Cn. Runtime
parameters absent from the sources remain unresolved. See [source review](m1.md)
for exact provenance and outstanding acceptance/delivery blockers. No merge is
authorized by this milestone implementation.

## M2 decisions (2026-10-22)

M2 is authorized by the coordinated Luna implementation request. M1 PR #4 is
merged with successful tooling, m1 and ros-container checks; no submitted reviews
or independent reproduction record were found. Those human gates remain open.
Use the lead plus up to three `gpt-6-luna` medium workers with disjoint ownership;
centralize Git and combined ROS execution. The standard workflow is recorded in
[codex-workflow.md](codex-workflow.md).

The user explicitly approved angular cap 1 rad/s, zero future-stamp tolerance,
1 s crossing lease/renewal timeout and exact-zero simulated measured-stop policy;
car motion/headway remain M4. The fixed 0.05 s step follows the required 20 Hz
simulator. M2 uses wall-backed ROS acquisition stamps and monotonic watchdogs,
no `/clock`. Runtime details, internal reset services and limits are in [M2](m2.md).
Do not enable unobserved obstacles in this baseline; that startup configuration
is rejected. Independent source review/reproduction and later scenario/mission
acceptance cannot be inferred from worker reviews or pure tests.

## M3 decisions (2026-10-23)

The user authorized the M3 plan and selected the recommended runtime defaults:
planner retries/backoff, final-approach speed, ETA smoothing/wait validity, edge
freshness and FIFO boarding cadence. [M3](m3.md) records numeric values, source
requirements versus design choices, internal interfaces, synthetic dependencies,
reset and explicit goal recovery. M3 implementation and evidence are scoped to a
branch/PR from merged main after PR #6 (`d58e8f5`). No merge is authorized.
Independent human review and teammate reproduction remain BLOCKED; later gates
cannot inherit PASS from M3 prerequisites.
