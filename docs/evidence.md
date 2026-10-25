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
At M2 closure, full T01–T18 scenario acceptance was **NOT RUN** and M3 was the
next milestone. Subsequent M3 and M4 results are recorded below; unexecuted
scenario rows retain NOT RUN.

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

## M3 implementation closure (2026-10-23)

M3 implementation and automated acceptance: **PASS**. T05 and T06: **PASS**.
The successful [hosted M3 workflow](https://github.com/smart-mobility-lab-team-C/smart-mobility-hub/actions/runs/39962241472)
tested PR head `15220d9f7110a93a8229b180ed8f0349d053701a` and passed all 24 M3
real-node cases, ten nominal docking runs, 18 M2 real-node regressions, 40 colcon
tests, 23 interface inspections, build and quality checks. Maximum docking
position error was 0.05 m, maximum yaw error was below 1e-9 rad, maximum ETA error
at 5 m was 0.600 s, and both cancellation checks completed in 0.026 s or less.
Independent source review and teammate clean-checkout reproduction remain
**BLOCKED** because the project currently has one contributor. All other T01–T18
scenario rows remain **NOT RUN**.

The [M3 attempt index](../evidence/m3-verification-attempts.json) records the
successful run's source revisions, environment, parameters, metrics, artifact
IDs and hashes. The downloaded artifact remains under the ignored
`evidence/runs/m3-hosted-39962241472/` directory. Earlier failed hosted and local
attempts remain indexed with their original FAIL results.

[PR #7](https://github.com/smart-mobility-lab-team-C/smart-mobility-hub/pull/7)
contains the scoped M3 implementation. The [local index](../evidence/m3-local.json)
and [command/result record](../evidence/m3-local.txt) preserve the earlier failed clean run
`m3-20261022T162059Z` at source `28e7c38de77d26e70aa5b23964a8d352eac6b725`.
Build, quality, 23 interface inspections, 39 colcon tests and all 18 M2 real-node
regression cases passed. M3 then failed in the initial reset with `queue_stale`,
before a nominal goal. A later local clean run with the readiness-probe edit
passed build, quality, 23 interface inspections, 40 colcon tests and all 18 M2
real-node regression cases, then failed its first M3 reset with
`PARTICIPANT_UNAVAILABLE`. A second clean local run passed the same build and
regression gates, then ended its first nominal mission with `SAFETY_STOP` after
a 17.0 s local observation gap (`vehicles_stale`, then `crossing_unknown`). The
hosted attempt passed ten nominal docking runs and failed the boarding-interruption
case before the readiness wait was added. Each attempt and trace hash is listed
in the M3 attempt index. These historical attempts remain FAIL; they are kept
separate from the later full hosted PASS and are not combined across revisions.

The source uses the existing watchdog bounds; failed local traces show long host
observation gaps, with the underlying cause unconfirmed. Raw logs/traces remain
ignored; hashes are retained in the index. Earlier development failures remain
FAIL and cannot be combined into acceptance for a different source revision.
Independent human review/reproduction remain BLOCKED.


## M3 observation-gap isolation — 2026-10-23

The separate [gap diagnostic](m3-gap-diagnostic.md) reproduced stalls in an
independent sampler outside Docker, including a 19.102-second interval with image
output bypassed. Three controlled real-node pauses passed localization checks;
all mission failures and earlier interrupted captures remain explicit in the
[diagnostic index](../evidence/m3-gap-diagnostic.json). Exact VM/hypervisor cause
remains unconfirmed. This investigation changes no milestone acceptance or
independent human review/reproduction status.

## Faster hosted verification (2026-10-24 KST / 2026-10-23 UTC)

The scoped CI implementation is `f4e80356ff48457d3ad66a5bd5f00c1a6f9c956f`
on `ci/faster-hosted-verification`, retaining the diagnostic branch at
`007292d9ef075899030800b9362d83aea6ca5de1`. The
[verification index](../evidence/ci-hosted-verification.json) records commands,
versions, actual results, run/artifact references and hashes. See
[automation](automation.md#optional-hosted-verification) for workflow/gate names
and local commands. Runtime source and M2/M3 evaluators are unchanged.

`/usr/bin/time -p bash scripts/check_fast.sh` passed on the PC (Ubuntu 22.04.5,
Python 3.10.12): 10 tooling/policy tests, 12 diagnostic tests, tracked shell/Python
syntax, source contracts and local Markdown links. One observed wall-time sample
was 1.98 s; it is not ROS acceptance or a performance benchmark. Workflow syntax
also passed `/tmp/smh-actionlint/actionlint -shellcheck= -color` (1.7.12).

Hosted routing was exercised, not inferred solely from mocks:

| Case | Observed result |
|---|---|
| [Draft PR](https://github.com/smart-mobility-lab-team-C/smart-mobility-hub/actions/runs/39986924841) | Quick checks/classification/gate PASS; integration skipped, ROS NOT RUN |
| [Ready implementation PR](https://github.com/smart-mobility-lab-team-C/smart-mobility-hub/actions/runs/39987092612) | Quick checks/classification PASS; integration selected |
| [Documentation-only PR](https://github.com/smart-mobility-lab-team-C/smart-mobility-hub/actions/runs/39987354788) | Quick checks/classification/gate PASS; integration skipped, ROS NOT RUN |
| [Invalid contract / failed quick check](https://github.com/smart-mobility-lab-team-C/smart-mobility-hub/actions/runs/39987518475) | Classification required integration; quick checks FAIL, integration skipped, final gate FAIL as required |

The intentionally invalid contract existed only on temporary
[PR #9](https://github.com/smart-mobility-lab-team-C/smart-mobility-hub/pull/9),
now closed without merging; its local/remote fixture branches were deleted.
Cumulative-diff/contract-rename, unknown-path and manual-run decisions are also
covered by local policy tests. Policy skips never count as executed acceptance.

The [ready hosted suite](https://github.com/smart-mobility-lab-team-C/smart-mobility-hub/actions/runs/39987092612)
completed **PASS** at implementation head `f4e8035` (tested PR merge commit
`0206b495ba5cd319769b33b2d8213e0265170e8f`). Its artifact
[hosted-verification-39987092612-1](https://github.com/smart-mobility-lab-team-C/smart-mobility-hub/actions/runs/39987092612/artifacts/12516234142)
contains the fresh Ubuntu 24.04.5/Jazzy/Python 3.12.3 run: M0 real talker/listener,
M1 source/lint/hash checks, 23 generated interfaces, eight-package build,
40 colcon tests (zero errors/failures/skips), 18/18 M2 regression cases and
24/24 M3 cases including 10/10 nominal docks. Every individual M2/M3 outcome is
indexed; full measurements, traces and package versions remain in the artifact.
Image ID is
`sha256:51d97cc70ee7bb42189b55b160524caab61f05839851f3f7dc0202fae5536528`.

Observed UTC wall durations: workflow 1,285 s (21m25s), acceptance step 1,121 s
(18m41s), image build/load 116 s. The Buildx logs explicitly show successful
GitHub cache export (`sending cache export 52.5s done`, then `DONE 52.5s`);
no cached build-step markers appeared in this first run. Cross-run reuse timing
is **NOT RUN**, reserved for the next normal integration run; no extra long
mission suite was scheduled solely for benchmarking. Evaluator latency clocks
remain monotonic; these workflow durations are wall time, not safety latencies.

[PR #8](https://github.com/smart-mobility-lab-team-C/smart-mobility-hub/pull/8)
returns to draft for this evidence-only follow-up, so its quick-only status does
not claim a new ROS execution at the evidence commit. The accepted implementation
revision above remains explicit. M0–M3 legacy workflows are manual-only. VM
investigation is parked; no M4 implementation, merge, repository-permission or
branch-protection change is included. Independent human review/reproduction
remain BLOCKED; other scenario rows retain their prior NOT RUN status.

## Observation-gap investigation reopened (2026-10-24)

The user reopened the VM investigation after CI delivery. The
[new diagnostic record](../evidence/vm-gap-reopened.json) retains an idle
per-CPU capture and a fresh three-attempt ROS campaign: all three missions
**FAIL** with protective stops, all three analyses observe gaps, and independent
samplers pinned across all four CPUs also stall. A user-supplied earlier kernel
excerpt reports guest soft lockup and unrelated system-service watchdog timeouts.
These observations do not establish a specific fix. See the
[diagnostic update](m3-gap-diagnostic.md#investigation-reopened--2026-10-24) for
commands, scope, the missing physical-host log and before/after acceptance.
Hosted acceptance is unchanged; local repair and post-fix acceptance are NOT RUN.

The supplied current-session VirtualBox host log subsequently confirmed an active
Windows Hyper-V/NEM backend and severe virtual timer backlog. Sanitized findings,
source line references and raw-log hashes are now in the same diagnostic index;
raw host logs are not committed. The [Windows host experiment](vm-host-repair.md)
provides the exact next change, rollback and post-restart acceptance checks.
Execution on the physical host and post-repair ROS verification remain NOT RUN.

The first new VM session after the user returned still reports active NEM:
native VT-x backend preflight **FAIL**. Post-restart quick checks PASS and a
90-second idle capture is gap-free, which does not establish a loaded fix.
Windows boot-setting/restart verification is awaiting read-only host output;
post-restart ROS missions and M2/M3 acceptance are NOT RUN. The same diagnostic
index retains the new host-log snapshot hash and guest timing metadata.

Windows follow-up now includes a stored `hypervisorlaunchtype Off`, user-confirmed
physical-host Restart, VBS running with no listed security services, and a local
VBS enable flag of 1. A bounded post-restart NEM diagnostic still failed: two
`STALE_POSE` terminal outcomes and one reset client timeout, with a 6.369 s maximum
independent host-sampler interval. The targeted local VBS-off test and its exact
rollback are prepared in the host runbook, with execution/verification NOT RUN.
This comparison does not establish that NEM or VBS caused the observation gaps.

The local VBS flag-zero test persisted but did not stop runtime VBS: the next
three diagnostic attempts all failed with protective stops and a 6.972 s maximum
host-sampler interval. Windows event 12 confirms a real OS restart; the Device
Guard query had no matching events. A distinct, reversible boot-level VSM launch
test is prepared and NOT RUN. The same diagnostic index preserves observed
results separately from proposed commands and missing causal explanations.


## Latest restart comparison — 2026-10-24 03:57 KST

Status: **UNRESOLVED**. Fresh VBox.log (opened 2026-10-23T18:52:53Z)
still reports VT-x unavailable, a present Windows hypervisor and active NEM.
Persistence of `vsmlaunchtype Off` is UNKNOWN pending Windows boot enumeration;
this cannot yet be called a failed test of a confirmed saved VSM setting.

Executed `python3 scripts/run_gap_diagnostic.py --runs 3 --seconds 300 --output
evidence/runs/gap-vsm-off-20261024`: fresh eight-package build in 36.9 s; baseline
ERROR (goal rejected), instrumented MISSION_FAILED (SAFETY_STOP), no-image
MISSION_SUCCEEDED with no reproduced gap in that attempt. The first two attempts
recorded GAP_OBSERVED. Independent VM sampler maximum interval was 2.698103 s.
Capture exit 0 means collection completed, not acceptance PASS. Full M0–M3 suite
NOT RUN. One successful no-image attempt does not establish repair or image
publication as the cause. Raw artifacts remain local; hashes and terminal results
are indexed in `evidence/vm-gap-reopened.json`. No runtime/watchdog changes.

## M4 continuation — local checks, ROS acceptance open

The M4 implementation is on `main` and includes sensor-backed parking/traffic ROS
adapters, independent simulator barrier interlocks, reset acknowledgments, an
integrated launch and real-node acceptance/plot tooling. [M4 handoff](m4-handoff.md)
describes the scope; [local implementation checks](../evidence/m4-local.json) and
[local Jazzy runtime evidence](../evidence/m4-jazzy-runtime.json) record measured
results. Local Jazzy build, 53 package tests and 18 M2 cases passed. The M3
prerequisite failed `RESET_DEADLINE`; T07–T10 remain NOT RUN. The hosted workflow
invokes the M4 runner, but no hosted M4 result is recorded. No M4 scenario PASS is
claimed.

## Local verification policy and M4 attempt — 2026-10-24

The user selected local execution and required documentation to distinguish
assignment requirements from project workflow choices. GitHub Actions is optional;
automatic triggers are removed in the local branch and take effect remotely only
when that workflow change is pushed. No further hosted runs were launched.

The [middleware diagnostic](../evidence/m4-local-diagnostics.json) records the
same-source Cyclone/Fast DDS comparison without claiming scenario acceptance.
The [fresh local attempt](../evidence/m4-local-cyclone-attempt.json) at `d660a94`
passed eight package builds, 53 package tests and all 18 M2 cases. It passed two
M3 nominal missions, then failed mission 3 with `SAFETY_STOP`. A 0.888-second gap
in safety observations is retained alongside host timing and a trace window.
That attempt left local T05 FAIL; T06 and M4 T07–T10 were not reached. Historical
hosted results remain separate and do not replace that local result.

## Local M3 completion — 2026-10-24

Fresh local acceptance at `f6a97fd7bf98a19662055eb462c21c0ae1085f5f` passed all
24 M3 cases and ten nominal docking missions for seeds 300–309. All eight
package builds, style/interface checks, 53 package tests and 18 M2 regression
cases passed. Local **T05/T06: PASS**. Independent teammate review and
clean-checkout reproduction remain BLOCKED. At that point M4 T07–T10 were NOT RUN.

The bus now receives observations/TF through a dedicated executor in the same
process, retaining the two-thread mission executor and shared-state lock. Reset
finish waits briefly for fresh zero/hold observations, and M2 parameter capture
uses native asynchronous services while continuing probe heartbeats. Public
schemas, QoS, frames, watchdogs and the one-second reset deadline are unchanged.

The [local index](../evidence/m3-local-completion.json) records this run and all
failed attempts/diagnostics that led to it. Earlier failures remain FAIL, and
successful diagnostic collection is not scenario acceptance. It includes the
image/configuration/source identities, commands, seeds, metrics, sample counts
and artifact hashes. Raw output is retained under ignored
`evidence/runs/m3-local-20261024-dedicated-observations/` and its sibling `-host/`.
The [M3 handoff](m3.md#current-local-verification--2026-10-24) states measured
limits and remaining human gates. At the time this result was recorded, the
changes were on `fix/m3-local-completion`; they have since been merged into
local `main` and published to `origin/main`. No hosted run was performed.

## M4 independent local acceptance — 2026-10-25

Assignment-scoped S4/S5 and **T07–T10: PASS** at clean source
`b7d1df7d36b457ad7c8d416e3c9f9d9a63d51ca7`. The explicit M4-only runner passed
all eight package builds, interface/style checks, 54 package tests and all nine
real-node M4 cases. Its scope file records M2/M3 NOT RUN. This is independent
M4 functional acceptance under assignment §§11–12, not a green combined suite.
The combined `5e9757b` attempt passed M2 but failed M3 on `crossing_stale`;
that failure remains preserved for its run. The later combined result is recorded
below. The interrupted attempt and all other failures retain their original
status in the [M4 index](../evidence/m4-local-completion.json).

The final run followed a genuine M4 correction: freezing parking now repeats
the last published acquisition immediately rather than taking one extra frame
on the next 5 Hz tick. The new regression test and real-node stale deadline both
passed without changing freshness thresholds. Twenty request pairs produced
zero double allocations and 94.214 ms p95 response time. Frozen parking reached
UNKNOWN in 1.014 s; frozen/missing traffic feeds did so in 0.692/0.719 s.
There were zero false congestion events over ten six-second free-flow trials
with distinct track IDs and simulator seed 17. Per-class precision/recall was
1.0 over 15 stable checkpoints; transition times are separately recorded.

Raw output under `evidence/runs/m4-local-20261025-freeze-fix/` contains source
and configuration hashes, resolved versions, three live parameter dumps, JSONL,
a seven-topic MCAP bag with 6,286 messages, a standalone measurement plot, and
blockage timing calculated from the input and output acquisition/computation
stamps. Those source-to-publication delays were 0.200/0.369 s, within one
2 Hz publication. End-to-end probe-change receipt delays were 0.354/0.542 s and
include the source timer and delivery; they are retained as distinct metrics.

[M4 handoff](m4-handoff.md) records reproduction and remaining work. Independent
teammate review/reproduction is BLOCKED. M4 changes are merged into local `main`
from `fix/m4-local-completion` and published to `origin/main`. No hosted run was used.

## Combined M2+M3+M4 local acceptance — 2026-10-25

The official clean-workspace `m4_container.sh` pipeline passed at run commit
`58f5afee4bd53567634f022d836c6a94f5daeaa7`: M2 18/18, M3 24/24 (including
seeds 300–309), and M4 9/9. The fresh build passed all eight packages, interface
and style checks, and 54 package tests. Runtime was 21m 44.868s in the pinned
Ubuntu 24.04.5 / ROS Jazzy image; rclpy was 7.1.12 and Cyclone DDS 2.2.4.
Optional profiling and event instrumentation were disabled. No assertion failed.

The run used implementation source through `b7d1df7`; the historical M2+M3
comparison remains `f6a97fd`. The previous `5e9757b` `crossing_stale` failure is
preserved as a failure for that run. One pass does not establish reliability;
independent review remains BLOCKED. Raw logs, traces, results, package versions,
source hashes and the exact image identity are in the
[combined result index](../evidence/m234-combined-20261025.json) and its ignored
raw directory `evidence/runs/combined-m234-20261025/`.

The one authorized repeat attempt at the same commit and image terminated before
smoke checks, build or milestone tests. Docker mounted the detached worktree,
but not the host `.git/worktrees` path referenced by its `.git` file, so the
runner's initial `git rev-parse HEAD` failed with exit 128. M2/M3/M4 are **NOT
RUN** for this attempt; this does not contradict or alter the earlier PASS. The
captured package manifest hash matches the first pass. No retry was performed.
See the [repeat attempt index](../evidence/m234-repeat-20261025.json) and retained
raw files in `evidence/runs/combined-m234-repeat-20261025/`.

## Combined repeat run — 2026-10-25

The second complete pipeline invocation used the same implementation commit
`58f5afee`, pinned image, and package manifest. The in-container preflight
passed. Build and package tests passed (8 packages; 54/54); M2 passed 18/18.
M3 stopped on nominal seed 309: **9/10 nominal cases passed**, then the final
DockBus result was `SAFE_STOP` with `SAFETY_INPUT_UNKNOWN:estop_stale`. M4 was
NOT RUN. The first full run at the same source had passed seed 309 in 65.092 s,
all M3 cases (24/24), and M4 (9/9), so this is an acceptance repeatability
failure rather than the earlier Git mount issue. No root cause is inferred and
no retry was performed. The run lasted 14m 16.905s through the M3 failure.
The [repeat result index](../evidence/m234-repeat2-20261025.json) records exact
environment and artifact hashes; full transcript, trace and node logs are in
`evidence/runs/combined-m234-repeat2-20261025/`.

## Linked-worktree container preflight — 2026-10-25

The container originally saw the worktree's `.git` pointer but not its target
under the main checkout's `.git/worktrees/`; the admin directory also referred
back to the worktree's absolute `/tmp` path. The preflight now binds both paths
and the common Git directory at their original locations. From inside the same
pinned image it resolved commit `58f5afee`, confirmed the worktree was clean,
matched all 142 tracked source records to the first successful run, and matched
the full dependency manifest. The first run's full source manifest also listed
nine ignored `.pytest_cache` files; those generated cache entries were excluded
from the tracked-source comparison. The preflight passed without a build or
acceptance run. See the [preflight record](../evidence/m234-container-preflight-20261025.json)
and [preflight helper](../scripts/m234_container_preflight.sh).
