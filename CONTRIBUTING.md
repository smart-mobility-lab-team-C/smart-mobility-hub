# Team workflow

All five members contribute code/evidence and explain their work. Actual names and capacity remain unassigned.

| Role | Primary scope | Reviewer |
|---|---|---|
| Perception | S1/S2, annotations, model and held-out evaluation | Integration |
| Bus/coordinator | S3/S8, dispatch and crossing ownership | Safety |
| Parking/traffic | S4/S5, atomicity, expiry, observations | Routing |
| Routing/robot | S6/S7, oracle, navigation and escort | Bus |
| Integration/safety | Simulator, launch, S9, logs and reproduction | Perception |

## Daily workflow

1. Read current issues, docs and AGENTS.md.
2. Use a personal branch such as feat/parking-reservations or docs/setup.
3. One bounded task per Codex session; separate worktrees for concurrent sessions.
4. Run relevant checks, save evidence, inspect diff.
5. Open PR with requirement IDs, actual commands/results, limitations and evidence.
6. Reviewer checks contracts and integration; integration owner merges.
7. Update status and contributions.

Avoid concurrent edits to interface definitions; review contract changes with all affected owners before implementation. Never force-push shared branches or overwrite uncommitted work.

## Definition of done

Code reviewed, required checks pass, failure paths exercised, documentation current, evidence points to the tested commit, and a teammate can reproduce it. If a check cannot run, document BLOCKED and the cause; do not call the requirement verified.

## Proposed repository settings

Owner configures protected main with PR review and required checks once workflows exist. Grant developers Write, reserve Admin for maintainers. These settings are recommendations and have not been changed.

## Contribution record

For each member record date, issue/PR/commit, implementation responsibility, tests executed, evidence reviewed, report sections and video segment. Commit counts alone do not measure contribution.
