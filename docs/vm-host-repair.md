# Windows host test for VM observation gaps

Status: **FAIL at post-restart backend preflight**. The supplied new-session
log still reports active NEM. Windows boot-setting output and physical-host
LastBootUpTime are requested; the guest reboot alone is confirmed. Successful
repair is not established yet. The Linux guest cannot change or restart its physical
Windows host. The human performs the host steps below, then the agent verifies
results after reconnecting. Save work and shut down Ubuntu normally before
restarting the physical computer.

## Evidence and target

The supplied current-session VirtualBox log opened at
`2026-10-23T12:58:26.271840400Z`. It matches four guest CPUs and 4 GiB RAM, with
CPU execution cap 100%. Host: Windows 11 `10.0.26200.9168`; VirtualBox
`7.2.22 r175245`. It explicitly reports unavailable VT-x, fallback to NEM,
a present Windows hypervisor and active NEM execution. It contains 71 abandoned
virtual timer catch-up attempts; the largest reported backlog is
1,154.351354180 s. A timer backlog is not an independently measured physical
CPU stall duration.

The earlier supplied log has two CPUs and is kept separate. Raw host logs stay
in Downloads because they contain host paths and machine details. The
[evidence index](../evidence/vm-gap-reopened.json) records hashes, line references,
sanitized observations and the unresolved before/after status.

Native VT-x is the next controlled comparison. Oracle lists
[poor performance with VirtualBox and Hyper-V on the same host](https://www.virtualbox.org/manual/ch14.html).
The current log confirms that configuration and severe timer lag, but an A/B
reproduction is still needed to establish whether changing the backend resolves
this project's gaps. Keep VM CPUs, RAM, ROS source, seeds and watchdog thresholds
unchanged during that comparison.

## Human steps on the physical Windows computer

This temporarily changes a Windows boot setting until it is restored below.
Hyper-V-dependent tools and protections will not operate in the test boot;
WSL 2 also depends on the Windows virtualization platform. See
[Microsoft's virtualization guidance](https://learn.microsoft.com/en-us/troubleshoot/windows-client/application-management/virtualization-apps-not-work-with-hyper-v)
and [WSL requirements](https://learn.microsoft.com/en-us/windows/wsl/faq).
Use the rollback before returning to work that requires those features.

If Windows device encryption/BitLocker is active, have its recovery key available
privately before changing boot configuration. Do not share the key. Microsoft
notes that [BCDEdit options can interact with BitLocker/Secure Boot](https://learn.microsoft.com/en-us/windows-hardware/drivers/devtest/bcdedit--set).
If a policy blocks this setting, retain the error and stop; this procedure does
not instruct disabling BitLocker, Secure Boot or other security settings.
The supplied log already reports Memory Integrity disabled, so do not change it
as an additional variable.

1. Save work and shut down Ubuntu normally. Exit its VirtualBox window.
2. On **Windows**, open Terminal or PowerShell using **Run as administrator**.
   Run:

   ```powershell
   bcdedit /enum "{current}"
   bcdedit /set "{current}" hypervisorlaunchtype Off
   ```

   Check that the set command succeeds. The first command retains the prior boot
   setting for comparison. If it was explicitly `Auto`, use `Auto` for rollback;
   if absent, remove the added element during rollback as described below.
3. Choose **Restart** in Windows. A setting change requires a restart; restarting
   Ubuntu alone does not apply it. No automatic restart is performed by a script.
4. Start the same Ubuntu VM. Save a **new current-session** VBox.log from
   VirtualBox Manager and reconnect to this workspace.

The quoted `{current}` identifier is intentional for PowerShell. Microsoft
[documents `hypervisorlaunchtype Off` / `Auto` and identifier syntax](https://learn.microsoft.com/en-us/windows-hardware/drivers/devtest/bcdedit--set).
The host command result has not been supplied, so execution of the intended
Windows boot change remains unverified. The new VM session still uses NEM;
backend verification is FAIL and post-change missions remain NOT RUN.

## Agent checks after reconnecting

Inspect the fresh host log before running missions. Require positive evidence
of native VT-x initialization and no active NEM fallback. A configuration section
mentioning NEM is not, by itself, an active NEM backend. If the new log still
shows fallback or a present Windows hypervisor, record that outcome and investigate
the actual policy instead of claiming the host change succeeded.

Check guest versions, CPU/RAM configuration and source commit, then repeat:

```bash
python3 scripts/run_gap_diagnostic.py --runs 3 --seconds 300 --output evidence/runs/gap-native-vtx-UNIQUE
```

Use a new output path. Retain independent host/container observations and all
mission terminal results. The capture command's zero exit code does not establish
mission success. Require three completed nominal missions with no >=0.5 s gaps
in critical fast streams or independently sampled host/container timing.
Compare the loaded traces with the retained failures; a single gap-free idle
sample does not establish repair.

If that comparison succeeds, execute the existing fresh Jazzy M0–M3 runner
(`scripts/m3_container.sh`) with image identity and a unique evidence directory:
eight-package build, generated interfaces, colcon tests, 18 M2 regression cases
and all 24 M3 cases including ten nominal docks. Retain every failure and do not
change watchdog thresholds. Only then update local repair/acceptance status.

## Rollback on Windows

Save work and shut down the guest before changing the host boot setting again.
In **administrator PowerShell**, restore the prior explicit `Auto` setting:

```powershell
bcdedit /set "{current}" hypervisorlaunchtype Auto
```

If the option was absent in the initial enumeration, restore that absence instead:

```powershell
bcdedit /deletevalue "{current}" hypervisorlaunchtype
```

Use the rollback matching the initial output, then **Restart Windows**. If the
initial setting was another explicit value, retain it and restore that exact
value rather than assuming `Auto`. Keep the before/after command output local.
