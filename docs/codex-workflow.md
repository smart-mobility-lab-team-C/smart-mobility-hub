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
