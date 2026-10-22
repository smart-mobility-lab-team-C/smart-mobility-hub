# Codex CLI workflow

Launch Codex inside the Ubuntu checkout. Use normal approval controls; do not run as root or disable protections to avoid a password prompt.

## First session

Paste:

```text
Read AGENTS.md and all linked planning documents.
Implement M0 automation only: bootstrap and doctor.
Inspect the actual Windows/WSL Ubuntu environment first.
Retrieve current official ROS Jazzy Ubuntu installation instructions.
Implement rerun-safe scripts following docs/automation.md.
Run supported checks, preserve logs, and report exact versions.
Ask me to handle administrator/password/sign-in steps when necessary.
Do not implement simulator or mission nodes.
Do not claim WSL/ROS validation from a mock or this chat environment.
Update docs with actual observed results and remaining blockers.
```

## Milestone session

```text
Read AGENTS.md, requirements, interfaces, test matrix and plan.
Implement only milestone M[N].
Inspect existing code and source contracts before changing files.
State acceptance criteria, implement, run real available checks and fix failures.
Do not weaken thresholds or substitute mocks for ROS evidence.
Update status, evidence paths and decisions.
Report changed files, executed commands, observed values and blockers.
Stop after this milestone.
```

## Recovery session

Start from Git status, last milestone, last failed command, environment metadata and evidence. Preserve local work. Diagnose the earliest actual failure before changing dependencies. Resume one gate at a time.

## Session handoff record

Record current commit/branch, goal, completed work, next command, failed command/output path, unresolved contract questions and relevant run IDs. Store durable project decisions in docs/decisions.md; do not rely on chat history.

## Coordinated Luna workflow

For each requested milestone the lead owns source contracts, shared manifests,
launch/configuration, integration, evidence, Git operations and PR delivery.
Up to three independent workers use `gpt-6-luna` with medium reasoning and
`fork_turns="none"`. Brief each with source references, allowed files, internal
APIs, clocks/failure behavior, acceptance commands, dependencies and exclusions.
Workers edit only assigned files and report needed shared changes to the lead.

Inspect current main, teammate work and prerequisite CI first. Lock contracts
before dependent edits. Assign bounded implementation areas and an acceptance
worker, initially read-only while contracts settle. Review every diff; return
local defects to the owner and resolve cross-component failures centrally. Run
combined Jazzy/ROS fault checks centrally to avoid competing publishers. Preserve
PASS, FAIL, BLOCKED and NOT RUN separately. Commit scoped changes and open a PR;
do not merge. Worker review never substitutes for independent teammate reproduction.

M2 applies this workflow to simulator/watchdogs, independent safety, acceptance
faults and review, with crossing/reset/launch/integration owned by the lead. See
[M2 contracts and execution](m2.md). Do not add later mission controllers, Gazebo,
Nav2 or hardware while completing this gate.
