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
