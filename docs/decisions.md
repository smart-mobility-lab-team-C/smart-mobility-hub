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
