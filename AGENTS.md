# Instructions for coding agents

## Authority and scope

Read docs/requirements.md, docs/interfaces.md, docs/test-matrix.md, and docs/plan.md before changes. The assignment defines technical contracts. The newer instructor announcement overrides submission video duration to 20–30 minutes. The implementation handbook is reference guidance, not completed ROS code.

Implement one requested milestone at a time. Preserve teammates' work. Do not replace unknown requirements with assumptions; record conflicts and source locations. No optional hardware, Gazebo, or Nav2 until the mandatory simulator passes.

## Engineering rules

- Use Ubuntu 24.04, ROS 2 Jazzy, Python rclpy consistently; record versions.
- All bus and robot motion passes through independent safety_supervisor.
- Actuator adapters independently stop on command expiry or supervisor loss.
- Separate noisy observations from evaluator-only ground truth.
- Keep interface names, fields, rates, QoS, timestamps, frames, and action semantics exact.
- Use asynchronous services, bounded retries, explicit deadlines, short callbacks, and synchronized shared state.
- Invalid or stale input is UNKNOWN, never a fabricated clear/zero state.
- Cancellation, timeout, rejection, no-route, and reset require explicit outcomes.
- Zero motion at startup and after protective stop. Clearing a latch never restarts a mission.
- Use monotonic time for same-host latency and document simulation versus wall time.
- Never invent measurements or mark unexecuted tests PASS.
- Keep NOT RUN, BLOCKED, FAIL, and PASS distinct; record evidence and commit.
- Mocks and pure Python tests do not establish ROS integration.
- Do not commit secrets, personal footage without permission, generated caches, or large raw evidence.
- Do not bypass approvals or run Codex as root. Humans handle passwords and sign-in.

## Delivery

Inspect → state acceptance criteria → implement → build/test → fix → update evidence/status → summarize. Commit scoped changes on a branch. Do not merge or alter repository permissions unless explicitly requested. Report exact commands, observed results, and blockers. Scripts planned in docs do not exist until implemented and verified.
