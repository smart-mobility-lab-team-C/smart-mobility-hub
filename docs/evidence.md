# Evidence and reproducibility

Every automated run creates a unique directory; reuse is forbidden.

Proposed layout: evidence/runs/<run_id>/ containing metadata.json, parameters.yaml, metrics.csv, events.jsonl, test_results.json, logs/, and references to included representative recordings/rosbags.

Metadata: scenario ID, seed, commit hash and dirty-worktree state, config hash, model ID/hash, dataset/split ID, start/end timestamps with zone, OS/ROS/Python/dependency versions, machine specification, accepted/rejected goals and reasons, failures, and evidence checksums.

## Measurement

- Count collisions by footprint overlap against evaluator-only ground truth.
- Count crossing conflicts by physical incompatible occupancy and overlapping ownership.
- Queue wait is entry to boarding; report people still waiting at run end separately.
- Distinguish supervisor receipt-to-zero-command latency from physical stop time.
- Use acquisition timestamps for sensor latency; use monotonic clocks for same-host timing.
- Report individual observations, N, mean/std, and p50/p95 where appropriate.
- Keep training, validation and test episodes separated by seed/episode; prevent window overlap across splits.
- Compare predictive/reactive dispatch on identical rush-hour seeds.
- Repeat fault cases five times at different mission phases, retaining individual results.

## Status schema

Each test record includes ID, status (NOT RUN/BLOCKED/FAIL/PASS), threshold, observed value, sample count, command, commit, run IDs, evidence paths and failure reason. Missing evidence prevents PASS. An exit code alone cannot prove the metric.

Large bags/videos stay out of normal Git history. Keep a small evidence index and summaries in Git; include required raw assets directly in final delivery. Never make an external download mandatory for the submitted project.

## Clean reproduction

A different member starts a fresh checkout on the target environment, follows setup, builds, launches representative scenarios, runs verification and checks included model/data. Record deviations and rerun after fixes.

M1 commands, versions, outcomes and log hashes are recorded in
[evidence/m1-local.txt](../evidence/m1-local.txt). Raw local logs stay ignored under
`evidence/m1-local/`; hosted M1 CI uploads its full results as an artifact.
See [M1 status](m1.md) for acceptance and independent review gates.

M2 local clean-run commands, source commit, versions, per-case outcomes and hashes
are in [m2-local.txt](../evidence/m2-local.txt); the small
[JSON record](../evidence/m2-local.json) retains observed metrics and live parameter
dumps. Full raw logs remain ignored under `evidence/runs/m2-20261022T145000Z/`.
Earlier failed runs retain FAIL status. See [M2](m2.md) for scope and independent
review gates; no complete T01–T18 scenario acceptance is implied.

## M2 implementation closure (2026-10-23)

Implementation and automated acceptance: **PASS**.
[PR #5](https://github.com/smart-mobility-lab-team-C/smart-mobility-hub/pull/5)
merged on 2026-10-22 at `6c25993525bf083214c14fdbb8abab224a5a75bd`.
The original local records above remain unchanged: source
`5a7e44082dea408d6ffacfc87aec6ec3936aee9d`, run `m2-20261022T145000Z`,
30 colcon tests with zero errors/failures/skips, and 18 passing real-process cases.
Subsequent PR commits contain evidence/documentation only.

Hosted workflows inspected on 2026-10-23 all report completed/success:

| Revision | M0 checks | M1 contracts and packages | M2 simulator and safety |
|---|---|---|---|
| PR head `e3dd60623952f6ae92cb3a454ff79c91444f6ad2` | [PASS](https://github.com/smart-mobility-lab-team-C/smart-mobility-hub/actions/runs/39799053591) | [PASS](https://github.com/smart-mobility-lab-team-C/smart-mobility-hub/actions/runs/39799053648) | [PASS](https://github.com/smart-mobility-lab-team-C/smart-mobility-hub/actions/runs/39799053751) |
| Merge `6c25993525bf083214c14fdbb8abab224a5a75bd` | [PASS](https://github.com/smart-mobility-lab-team-C/smart-mobility-hub/actions/runs/39799706032) | [PASS](https://github.com/smart-mobility-lab-team-C/smart-mobility-hub/actions/runs/39799706131) | [PASS](https://github.com/smart-mobility-lab-team-C/smart-mobility-hub/actions/runs/39799706128) |

Independent source review and teammate clean-checkout reproduction: **BLOCKED**.
The GitHub contributors endpoint currently lists one contributor, `qrtman`;
a different human reviewer/member is required. The historical local records retain
their capture-time NOT RUN status. Neither agent review nor CI closes this gate.
Full T01–T18 scenario acceptance remains **NOT RUN**. M3 is next and remains NOT RUN.

Closure verification commands (2026-10-23):

```bash
gh pr view 5 --json state,mergedAt,mergeCommit
gh pr checks 5
gh api 'repos/smart-mobility-lab-team-C/smart-mobility-hub/actions/runs?head_sha=6c25993525bf083214c14fdbb8abab224a5a75bd'
gh api repos/smart-mobility-lab-team-C/smart-mobility-hub/contributors
python3 scripts/check_docs.py
git diff --check
```

Observed: PR merged at the recorded SHA; all four PR jobs passed across three
workflows; all three merge workflows completed successfully; one contributor;
local Markdown links PASS; whitespace check exited 0. Runtime evidence was inspected,
not rerun. This closure changes only M2 status, the milestone plan and this index.

## M3 verification in progress

The [M3 handoff](m3-handoff.md) records the active hosted rerun, the earlier
pre-M3 regression failure, and the steps to resume reviewing evidence.

[PR #7](https://github.com/smart-mobility-lab-team-C/smart-mobility-hub/pull/7)
contains the scoped M3 implementation. The [local index](../evidence/m3-local.json)
and [command/result record](../evidence/m3-local.txt) preserve the failed clean run
`m3-20261022T162059Z` at source `28e7c38de77d26e70aa5b23964a8d352eac6b725`.
Build, quality, 23 interface inspections, 39 colcon tests and all 18 M2 real-node
regression cases passed. M3 then failed in the initial reset with `queue_stale`,
before a nominal goal. Full local M3/T05/T06 acceptance is not established.

The source uses the existing watchdog bounds; traces show multi-second host timing
gaps, with the underlying cause unconfirmed. Raw logs/traces remain ignored; hashes
are retained in the index. Earlier development failures remain FAIL and cannot be
combined into acceptance for a different source revision. Hosted checks are pending.
Independent human review/reproduction remain BLOCKED.
