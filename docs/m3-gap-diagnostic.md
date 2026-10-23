# M3 observation-gap diagnostic

The retained local M3 failure has a roughly 17-second gap across odometry,
safety, commands, queue, crossing and feedback. Both source and receipt clocks
advance. This establishes missing observations, not a confirmed host-suspension
cause. Accepted M3/T05–T06 results remain as recorded in [M3 status](m3.md).

## Reproduction

Run as the ordinary Docker-enabled workspace user with the existing Jazzy image:

```bash
python3 scripts/run_gap_diagnostic.py --output evidence/runs/gap-UNIQUE
```

The runner builds a fresh workspace inside Ubuntu 24.04/Jazzy, then repeats the
first nominal mission: seed 300, zero initial passengers, existing ROS nodes,
real safety supervision and unchanged watchdogs. The first attempt is an
observer-only baseline; later attempts add callback spans. All attempts retain
thread/executor heartbeats, a separate ROS observer, and independent 10 Hz host
and container samplers. Ten attempts or 1,200 seconds bound the mission campaign;
build and bounded shutdown time are outside that interval. `--runs` and
`--seconds` can reduce these limits. ROS domain 74 is reserved for this runner;
do not run simultaneous campaigns in that domain.

The host sampler runs in the VM hosting Docker, not on the physical machine.
Default Docker time namespaces share that VM's monotonic clock. Wall-backed ROS
acquisition stamps and fixed-step simulation time are distinct. Files record
wall and monotonic clocks; missing headers remain null. Process CPU ticks,
scheduling counters, memory pressure and cgroup CPU throttling counters are raw
Linux observations, not inferred causes. Callback spans also record thread CPU
time to separate CPU work from elapsed time when a callback is interrupted.

`run.json` declares each active interval, commands, seed, parameter snapshots,
terminal result and injected faults. Startup/shutdown samples remain available
but do not establish gaps. `analysis.json` reports periodic-stream gaps over
0.5 seconds on streams faster than 2 Hz, acquisition-clock jumps, slow callbacks, cadence and protective
stop events. Arrival/feedback at 2 Hz remain context only because their ordinary
period equals the gap threshold. Each `gap-NNN.jsonl` contains available five-second context on both
sides. Abruptly interrupted/truncated captures retain warnings. Missing
independent coverage stays unresolved. A correlated host-sampler delay above
0.25 seconds also prevents attributing a near-threshold gap to the container. A run without a gap is NOT_REPRODUCED.

If an instrumented attempt exhibits a gap, the next attempt bypasses image
creation/publication inside the diagnostic subprocess only. A different outcome
is evidence to investigate, not proof that rendering caused the original stall.
No runtime source, public ROS interface or default image behavior is changed.
No diagnostic variant is eligible for milestone acceptance.

## Controlled localization checks

```bash
python3 scripts/test_gap_tools.py
python3 scripts/run_gap_diagnostic.py --runs 1 --pause-node observer --output evidence/runs/gap-observer-UNIQUE
python3 scripts/run_gap_diagnostic.py --runs 1 --pause-node probe --output evidence/runs/gap-probe-UNIQUE
python3 scripts/run_gap_diagnostic.py --runs 1 --pause-node scenario_runner --output evidence/runs/gap-simulator-UNIQUE
```

The opt-in pause is an explicitly recorded 0.8-second SIGSTOP/SIGCONT of a child
process after bus motion is observed. A separate helper resumes it. Pausing the
probe also pauses its operator heartbeat; pausing the simulator interrupts its
observations and adapter callbacks. The supervisor remains independent and any
resulting stop is retained. No latch is cleared or mission restarted after the
fault. Controlled faults cannot establish spontaneous reproduction.

Compare baseline and instrumented odometry/executor cadence distributions and
instrumented callback durations before interpreting timing changes. Raw records
remain ignored under `evidence/runs`; environment/source/artifact hashes and a
small result index should be committed after verification. Unsuccessful and
interrupted runs must remain distinguishable from completed diagnostic runs.

## Observed results — 2026-10-23

The long gap is observable **outside Docker and ROS**. Independent VM-host
sampling paused with container and ROS sampling. This isolates a broader timing
or scheduling interruption; it does not distinguish physical-host scheduling,
hypervisor behavior or a guest-clock problem. Physical-host/hypervisor timing is
the next measurement boundary. No watchdog or runtime motion policy was changed.

The completed ten-attempt campaign at `727fc10` produced one successful mission
without a detected gap and nine explicit protective stops. Analysis at `bf84522`
found nine host-gap windows and five correlated near-threshold host delays.
Image generation/publication bypass did not remove the gaps.

| Variant | Attempts | Protective stops | Largest host interval in a detected window |
|---|---:|---:|---:|
| Observer-only baseline | 1 | 1 | 0.489 s; correlated delay |
| Callback instrumentation | 5 | 4 | 15.490 s |
| Instrumentation with image output bypassed | 4 | 4 | 19.102 s |

No measured callback span exceeded 0.5 seconds; image generation/publication
peaked at 21.4 ms. In instrumented attempt 01, host/container sampling gaps were
13.676/13.651 seconds. These observations do not support blaming a long image
callback for that stall. The longest image-bypassed host gap was 19.102 seconds.

Baseline probe-odometry p95 interval was 55.8 ms, compared with 56.3 ms in
instrumented attempt 01 and 64.6 ms in the successful instrumented attempt 07.
Host scheduling varied and missions had different outcomes, so these measurements
do not establish a causal instrumentation-overhead estimate.

Three controlled real-node checks at `bf84522` passed the recorded localization
criteria: an injected pause of at least 0.8 seconds, a gap in the target process,
independent host/container intervals at most 0.25 seconds, and an unaffected
peer observer/probe/supervisor. These are localization results, not mission PASS.

| Paused process | Measured pause | Localization |
|---|---:|---|
| Independent observer | 0.802 s | Observer gaps; probe continued |
| Probe/operator heartbeat | 0.801 s | Probe gaps; independent observer continued |
| Simulator | 0.801 s | Simulator heartbeat and sensor gaps; supervisor continued |

All three controlled missions ended in recorded protective stops. The observer
case's stop followed a separate later host gap. The probe case recorded
`SAFETY_INPUT_UNKNOWN:estop_stale`. The simulator case retained its safety outcome
and a separate later host gap; neither is silently counted as mission success.

The twelve tooling tests passed on both the VM host and the Jazzy container;
ament_flake8 and ament_pep257 passed for all four Python diagnostic files. Fresh
builds completed for the natural campaign and every controlled case. Existing
M3 acceptance, independent review/reproduction and other scenario statuses are
unchanged.

[Diagnostic evidence index](../evidence/m3-gap-diagnostic.json) records commands,
source and analyzer commits, environment, terminal outcomes, timing metrics,
localization criteria and artifact hashes. Raw attempts remain under
`evidence/runs/gap-*`; corrected analysis and five-second context windows are in
`evidence/runs/gap-reanalysis-20261023`. Original analysis is retained, including
the initial 2 Hz false detections and interrupted preflight. The index identifies
the corrected analyzer version rather than rewriting those captures.
