# Decisions and open items

| ID | Decision | Reason | Status |
|---|---|---|---|
| D01 | Codex and ROS inside WSL2 Ubuntu 24.04 | Shared Linux runtime on Windows | User selected; installation NOT RUN |
| D02 | ROS 2 Jazzy + rclpy | Assignment preferred distribution | Planned |
| D03 | Deterministic 2D baseline before optional extensions | Required scope and reproducibility | Planned |
| D04 | Safety supervisor and adapter watchdog from early integration | Independent stop paths | Required |
| D05 | Newer 20–30-minute video rule overrides shorter handbook demo | Instructor announcement | Documented |
| D06 | Development links allowed in Git; separate link-free submission staging | Direct-upload submission rule | Planned |
| D07 | Branch + PR for this documentation | Reviewable change to team repository | In progress |

## Needed before implementation freeze

- Submission date/time/timezone.
- Final TEAMNAME and members' GitHub handles.
- Actual Windows/WSL state and machine resources.
- Available hours and confirmed owner/reviewer per role.
- Authorized real video and annotation responsibility.
- Source interface/map review, especially ambiguities caused by PDF text extraction.
- Current official ROS installation retrieval before bootstrap coding.

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
