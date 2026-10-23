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

## Investigation reopened — 2026-10-24

User requested fixing the observation gaps after hosted CI consolidation. The
investigation is active again on `fix/vm-observation-gaps`. **No fix has been
applied or verified.** Runtime source, public interfaces and watchdog bounds
remain unchanged. The [new evidence index](../evidence/vm-gap-reopened.json)
records the following independent local observations.

A 90-second idle capture pinned one existing `gap_tools.py sample` process to
each virtual CPU using `taskset -c N`. No sampler interval exceeded 0.5 s; maxima
were 0.114, 0.121, 0.119 and 0.136 s for CPUs 0–3 respectively. This is an idle
NOT_REPRODUCED observation, not proof of a fix or ROS acceptance.

The next fresh diagnostic build completed eight packages in 41.9 s. Command:

```bash
python3 scripts/run_gap_diagnostic.py --runs 3 --seconds 300 --output evidence/runs/gap-reopen-20261024
```

Baseline, instrumented and image-bypassed attempts all ended **MISSION_FAILED**
with `SAFE_STOP` / `SAFETY_STOP`; all three analyses report **GAP_OBSERVED**.
Independent samplers pinned to all four virtual CPUs stalled during the loaded
capture. Whole-capture maximum intervals were 7.789, 7.800, 7.799 and 7.804 s.
The index retains mission-interval metrics separately from whole-capture metrics.
The runner exit code was zero because diagnostic collection completed, not
because missions passed. Raw evidence and the exact sampler commands remain
under ignored `evidence/runs/cpu-gap-20261024` and
`evidence/runs/gap-reopen-20261024`; final hashes are in the new index.

A user-supplied kernel-log excerpt also reports an earlier event at 01:13:39 KST:
CPU 0 stuck for 1,069 s in `swapper/0`, a stack through `pv_native_safe_halt` and
CPU idle functions, a long clocksource readout interval, and watchdog timeouts
in systemd-oomd, systemd-timesyncd, snapd and journald. The agent could not read
this permission-restricted log; the user ran the read-only command themselves.
That event is not temporally correlated with the new campaign. These messages
support investigation of guest-wide timing/scheduling disruption but do not
identify whether the physical host paused, the clock jumped, or virtualization
failed.

The missing next evidence is the physical host's `VBox.log`, requested from the
user. Oracle's [official troubleshooting guide](https://www.virtualbox.org/manual/ch12.html)
identifies this log as containing the host OS, VirtualBox build, VM configuration,
virtualization details and state transitions. Open VirtualBox Manager outside
Ubuntu, select the VM and open Logs / Show Log. Inspect its header and HM/NEM,
CPU execution-cap and pause/resume entries before choosing an environment change.
Keep the raw log local: it can contain host paths and other machine details.
No physical-host settings, guest clocksource, kernel boot parameters or security
features have been changed on an unverified hypothesis.

Fix acceptance requires a recorded, specific before/after environment change,
repeating the same reproduction without half-second gaps in critical fast
streams/independent samplers, and then a fresh unchanged M2/M3 suite (18 M2 cases,
24 M3 cases and ten nominal docks). Until then the local fault is unresolved;
hosted M3 acceptance and all earlier failed attempts retain their own statuses.

## Host log supplied — 2026-10-24

The current-session log matches four guest CPUs and confirms Windows 11,
VirtualBox 7.2.22 r175245, CPU execution cap 100%, unavailable native VT-x and an
active Windows Hyper-V/NEM backend. Its timer manager reports 71 abandoned
catch-up attempts, with a largest reported virtual timer backlog of
1,154.351354180 s. The earlier two-CPU log is retained separately. These are
observed backend/timer facts, not proof that NEM caused each ROS gap.

The [evidence index](../evidence/vm-gap-reopened.json) now includes both log
hashes, line references and sanitized findings. Raw logs remain in the user's
Downloads directory. The missing host identification is resolved. The next
step is the [reversible Windows host test](vm-host-repair.md): temporarily boot
without the Windows hypervisor, verify native VT-x in a fresh log, then repeat
the unchanged reproduction and full M2/M3 acceptance. The human must perform the
Windows administrator step/restart outside Ubuntu; host repair and post-repair
verification remain **NOT RUN**. No ROS or watchdog change has been made.

## First post-restart preflight — 2026-10-24

The user returned after shutting down/restarting. A new guest boot is observed;
raw metadata records boot ID, OS/kernel, CPU configuration, source and image.
Local quick checks pass again (10 tooling/policy and 12 diagnostic tests).
A fresh 90-second per-CPU idle capture has no >0.5 s intervals; maxima range from
0.155 to 0.172 s. The pre-change idle test was also gap-free, so this does not
establish repair.

The new supplied host log opens at `2026-10-23T17:45:44.042919800Z` and matches
four CPUs with cap 100%. Lines 605, 620 and 918 still report unavailable VT-x,
a present Windows hypervisor and active NEM execution respectively. **Native
VT-x backend preflight: FAIL.** Its short startup capture has no abandoned
catch-up events; that is insufficient evidence of a repaired loaded system.
An immutable local snapshot and hashes are retained under ignored
`evidence/runs/vm-postrestart-20261024`, indexed in the
[diagnostic evidence](../evidence/vm-gap-reopened.json).

Windows command execution and Windows' own restart have not been verified.
Read-only outputs requested from administrator PowerShell on the physical host:

```powershell
bcdedit /enum "{current}"
Get-CimInstance Win32_ComputerSystem | Select-Object HypervisorPresent
Get-CimInstance Win32_OperatingSystem | Select-Object LastBootUpTime
```

These distinguish an unapplied launch setting or missing physical-host restart
from a host configuration that still launches the hypervisor. Further loaded
ROS reproduction and M2/M3 acceptance are **NOT RUN** after this restart, held
at the backend gate. No further Windows security feature changes are prescribed
without those results. Runtime source, image and watchdogs are unchanged.

## Windows settings and post-restart NEM reproduction

The user supplied `hypervisorlaunchtype Off` from the current Windows boot entry
and explicitly confirmed Start → Power → Restart on the physical host.
HypervisorPresent is reported true. LastBootUpTime was blank without an error
and remains unavailable; no timestamp is fabricated. The `(1)` host-log copy is
byte-for-byte identical to the retained post-restart snapshot.

Win32_DeviceGuard subsequently reported VBS enabled/running (2), with configured
and running service arrays both `{0}`. The user-supplied local DeviceGuard query
reports `EnableVirtualizationBasedSecurity=1`; the policy-key query returned
not found. Other observed values and explicit host boot-timer options are retained
in the [index](../evidence/vm-gap-reopened.json) without modification. No running
Credential Guard or Memory Integrity service is inferred from this output.

To test actual behavior after the confirmed restart despite the unchanged NEM
backend, a separate diagnostic comparison was run:

```bash
python3 scripts/run_gap_diagnostic.py --runs 3 --seconds 300 --output evidence/runs/gap-postrestart-nem-20261024
```

This is **not native-backend acceptance**. Fresh build: eight packages in 61 s.
Baseline and image-bypassed attempts ended `MISSION_FAILED` / `STALE_POSE`;
the instrumented attempt ended `ERROR` with a reset client deadline exceeded.
The independent VM-host capture peaked at 6.369472156 s between samples.
Capture completed with exit zero; no attempt is counted as mission PASS.
Per-attempt statuses, errors, analyses and hashes are indexed; raw captures remain
ignored under `evidence/runs/gap-postrestart-nem-20261024`.

The [follow-up host experiment](vm-host-repair.md#follow-up-observed-local-vbs-enable-flag)
is now one reversible change: the observed local VBS enable DWORD from 1 to 0,
with rollback to 1. Host execution, subsequent native-backend verification and
full M2/M3 acceptance are **NOT RUN**. This is a security configuration experiment,
not an established cause/fix; no other Windows protections, timer settings or ROS
watchdogs are changed by the agent.

## Persisted flag-zero result and next boot-level comparison

The user confirmed that the local VBS enable DWORD remained 0 after the latest
Windows restart, while runtime VBS was still 2 and service arrays were `{0}`.
The supplied fresh host log still uses NEM. The three-attempt post-change capture:

```bash
python3 scripts/run_gap_diagnostic.py --runs 3 --seconds 300 --output evidence/runs/gap-vbs-off-20261024
```

Fresh build completed eight packages in 72 s. All three attempts ended
`MISSION_FAILED` / `SAFE_STOP` / `SAFETY_STOP`, with GAP_OBSERVED analyses. The
independent host capture peaked at 6.971586242 s between samples. Exit zero
records completed diagnostic collection only. Raw captures, preflight metadata,
new host-log snapshot and hashes are indexed; full M2/M3 acceptance is NOT RUN.

The user also supplied a Windows Kernel-General OS-start event at
`2026-10-23T18:11:24.500000000Z`, corroborating a genuine Windows restart.
Current boot-entry enumeration still shows `hypervisorlaunchtype Off` and no
explicit `vsmlaunchtype`. Device Guard queries returned no events; this neither
proves nor disproves a firmware lock. No further registry changes are justified
by that absence alone.

The [next documented experiment](vm-host-repair.md#follow-up-explicit-vsm-launch-control)
is an explicit boot-level `vsmlaunchtype Off`, controlling Virtual Secure Mode
startup, with rollback deleting the previously absent value. This is a supported
control to test, not proof of what forced VBS to run and not a guaranteed native
VT-x switch. The host command/restart, backend verification and post-experiment
ROS tests are NOT RUN. No firmware bypass or unrelated security-feature removal
is prescribed. Runtime source and watchdog thresholds remain unchanged.
