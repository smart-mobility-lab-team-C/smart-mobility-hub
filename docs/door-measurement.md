# Door measurement validation — 2026-10-25

Latest resume: **FAIL at incremental build** after verified mounts, pinned
package manifest, native interface imports and prerequisite source checks passed.
Cached simulator package metadata is root-owned and cannot be replaced by the
non-root build user. All later gates are NOT RUN. See the
[resume result](../evidence/door-measurement-resume-20261025.json) and details below.

Previous attempt: **BLOCKED before controls**. The incremental build failed because the
reused workspace's generated interface setup references
`/cache/install/smart_hub_interfaces`, but the attempted container invocation
mounted the repository only at `/workspace`. No control tests, comparison
mission, measurement adoption, or official acceptance ran. No retry followed.
The pinned image and package manifest matched the historical environment.
See the [machine-readable result](../evidence/door-measurement-20261025.json).

The user's plan requires positive and negative controls before one seed-304
comparison, followed conditionally by adoption and one clean M2+M3+M4 pipeline.
Its stop-on-first-failed-or-blocked-gate rule governs this attempt. This is a
build/setup failure, not evidence that the new duration calculation passes or
fails. The provisional implementation remains unvalidated and the official
duration gate remains `closed - opened >= 8.0` using receipt timestamps.

## Provisional implementation

`DoorEvidence.capture` brackets the actual `World` mutation using integer
`time.monotonic_ns()` readings. `ScenarioRunner` invokes it around door requests,
physics, and reset while holding the existing lock. It compares measured
`World.door_open` before and after the operation; a rejected opening request
cannot generate an opening. Publication occurs after lock release. Reset emits
an invalidating record even when the door remains closed and retains the old
run and goal identities. Goal boundaries provide closed-state anchors.

Records use the existing reliable volatile depth-100 `/hub/events` stream and
unchanged `HubEvent` schema: `scenario_id=sim_evaluator`, `entity_id=bus`,
`event=DOOR_MEASURED`, run/goal correlation, and JSON in `reason` with schema,
sequence, operation, previous/measured state, and before/after nanoseconds.
The sequence is monotonic across resets for one simulator process. No bus or
safety logic subscribes to this evaluator evidence. Public schemas, QoS,
deadlines, dwell, and interruption behavior are unchanged.

The independent `scripts/door_duration.py` evaluator requires matching identity,
closed mission boundaries, adjacent sequence numbers, consistent measured
states, and exactly one open/close interval. Reset, missing events, mixed
missions, multiple intervals, malformed bounds, or interrupted actions block
nominal acceptance. Duration arithmetic is entirely integer:

- Minimum = close-before minus open-after.
- Maximum = close-after minus open-before.
- Minimum at least 8,000,000,000 ns: source PASS.
- Maximum less than 8,000,000,000 ns: duration FAIL.
- Bounds overlapping the threshold: BLOCKED.

An interrupted action cannot be nominal success even if its duration passes;
the duration assessment is retained separately. Receipt duration and its
original threshold result are also retained, with an explicit disagreement
field. Receipt callback timing includes transport, heartbeat sampling, and
executor delay, so it is not direct evidence of physical duration. This
observation does not establish the physical cause of a historical failure.

`test_m3_door_evidence.py` scripts mutations through the actual simulator
callbacks and real `World` with an injected clock, checks the lock/publication
boundary, and compares against independently scheduled times. Its proposed
controls cover exact eight-second and one-nanosecond boundaries, 7.9/8.1-second
receipt disagreements, interlock rejection, physics transitions, reset,
cancellation/protective interruption, and damaged/missing evidence. These tests
were **NOT RUN** because the prerequisite build failed.

`verify_m3.py --door-comparison` is prepared to run only nominal index 4
(seed 304, matching the original zero-passenger fixture). It retains the receipt
assertion result separately, evaluates all other existing nominal requirements,
and requires source PASS. It explicitly disclaims full milestone acceptance.
`door_measurement_container.sh` runs it under `timeout --signal=INT
--kill-after=20s 240s`, only after a successful controls marker and unchanged
source manifest. This command was **NOT RUN**.

## Attempt and next review

The single attempted command was:

```sh
docker run --rm --user 1000:1000 -e HOME=/tmp \
  -v /home/vboxuser/smart-mobility-hub:/workspace -w /workspace \
  sha256:f1c8db36f4874670d2125e3e40be69491da12273b28d4effb4f4d3c8b98a839b \
  bash scripts/door_measurement_container.sh \
  /workspace/evidence/runs/door-measurement-20261025 controls
```

It copied the affected simulator/control sources into the reused workspace,
confirmed unchanged prerequisite sources and the package manifest, then failed
at `colcon build --packages-select smart_hub_sim smart_hub_control
--event-handlers console_direct+`. Zero packages completed; the second package
was not processed. Style checks and the controls command were never reached.
Python compilation and `git diff --check` had passed before this attempt;
neither establishes runtime correctness. Total wall runtime was not captured;
the colcon summary reported 0.43 s. Raw logs, the attempted source manifest,
inherited patch, and hashes are preserved under
`evidence/runs/door-measurement-20261025/` (ignored raw evidence).

A separately reviewed follow-up must restore the original `/cache` mount alias
for the pinned workspace and use a fresh evidence directory. No follow-up is
authorized by this stopped attempt. Controls, comparison, adoption, and clean
acceptance remain pending in that order. The current commits preserve work;
they are not the plan's validated acceptance candidate.

## Historical interpretation

The 7.973234 s result remains **FAIL** under its original receipt method. Its
physical cause is unproven. The prior recommendation to start the dwell clock
earlier and add a control-period margin is withdrawn; no such change was made.
The original evidence JSON remains unchanged as a historical record; this
document supersedes its causal recommendation, not its status or measurement.
The inherited crossing correction is preserved in a separate commit.

Passing the proposed controls would validate only their tested cases. One
comparison cannot explain every historical failure, and one combined PASS
cannot establish repeatability. All historical outcomes remain independently
recorded.

## Authorized resume with verified mounts

The current user plan authorizes a fresh attempt from `98cbfb2`; the earlier
BLOCKED attempt and its artifacts remain unchanged. The fresh attempt at clean
revision `2c9ad87bdda3509954a0021773356a8e076280d4` stopped at its first new
failed gate. No retry or permission modification followed.

The host launcher is `python3 scripts/door_measurement.py
ABSOLUTE_FRESH_RESULTS_DIRECTORY controls`. It pins the image by immutable ID,
mounts the repository at `/workspace` and its cached workspace at `/cache`, and
checks the package manifest, native interface imports, and unchanged prerequisite
sources before incrementally building only `smart_hub_sim` and
`smart_hub_control`. Each gate records its command, start/end times, elapsed time,
exit status and artifact hashes. The run records the revision, worktree state,
source manifest and patch. Failed and blocked stages retain their evidence;
downstream stages stay NOT RUN.

Only after every control passes may the same launcher run `comparison` against
the same results directory and unchanged sources. It runs nominal index 4
(seed 304, zero passengers) once, preserving the receipt assertion separately.
The host gives the container 220 seconds to execute, reserves the final 20 seconds
for cleanup inside a 240-second total bound, and never retries. M3 child cleanup
uses shared deadlines; the case harness stops at the first FAIL or BLOCKED and
lists all remaining cases as NOT RUN. The official duration gate is still the
original receipt assertion until a passing comparison authorizes adoption.

The new harness controls exercise BLOCKED propagation through the actual verifier
wrapper, immediate stopping, failed-stage provenance, process-group timeout
cleanup, and a shared child-cleanup deadline. Existing producer controls retain
exact integer nanosecond boundaries, interlock rejection, physics/reset capture,
and capture-under-lock/publication-afterward checks; added cases cover overlapping
operation bounds and an interruption whose duration would otherwise pass.

### Resume outcome

Executed once:

```sh
python3 scripts/door_measurement.py \
  /home/vboxuser/smart-mobility-hub/evidence/runs/door-measurement-resume-20261025 \
  controls
```

| Gate | Observed outcome |
|---|---|
| Pinned image, `/workspace` and `/cache` mounts | PASS |
| Package manifest, native interface imports, unchanged prerequisites | PASS |
| Incremental `smart_hub_sim` / `smart_hub_control` build | FAIL; zero completed, control package not processed |
| Style, producer/evaluator controls, harness controls, world/routing regressions | NOT RUN |
| Seed-304 comparison | NOT RUN |
| Source gate adoption and clean M2+M3+M4 acceptance | NOT RUN |

The build failed while replacing
`/cache/install/smart_hub_sim/lib/python3.12/site-packages/smart_hub_sim-0.1.0-py3.12.egg-info/PKG-INFO`.
Read-only inspection found its metadata directory owned by `root:root` with
mode 0755 and its file owned by `root:root` with mode 0644. The container ran
as `1000:1000`. The build copied Python files before failing, so the reused
installation must be treated as partially updated and unvalidated.

The attempt's timestamp span was **21.217213 s**; the host execution interval was
21.149186 s, including 18.484518 s for the container. The build command lasted
4.232619 s; colcon reported 3.53 s. Its exit code was 1. Commands, stage-specific
UTC timestamps, source revision/hashes, exact dependencies, logs, colcon output,
permission observations, and artifact hashes are retained in the
[resume result index](../evidence/door-measurement-resume-20261025.json) and ignored
raw directory `evidence/runs/door-measurement-resume-20261025/`. No container
remained running after the attempt.

The launcher and M3 harness changes are committed but their style and runtime
controls remain unvalidated because the build prerequisite failed. The original
receipt duration gate is unchanged; no official pipeline adoption occurred.
A future attempt requires separate authorization and a user-writable cached
installation (or an approved ownership repair), with the same ordered gates and
fresh evidence. This stopped attempt supplies no duration, milestone acceptance,
repeatability, or historical causal conclusion.
