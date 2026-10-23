# Windows host test for VM observation gaps

Status: **UNRESOLVED**. The local VBS flag is now 0 according to the user's
post-reboot query, but Windows still reports VBS running and the fresh VM log
uses NEM. All three post-change diagnostic attempts failed. A Windows System
event independently confirms a real OS restart. The next boot-level VSM launch
experiment below is NOT RUN; no repair or native-backend acceptance is claimed.
The human performs Windows administrator steps outside this Linux guest.

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
The user subsequently supplied the stored `Off` setting and confirmed a full
Windows Restart. Nevertheless the new VM session uses NEM and Windows reports
VBS running. Native-backend verification is FAIL. A bounded post-restart NEM
diagnostic has also reproduced the gaps; native-backend acceptance is NOT RUN.

## Follow-up: observed local VBS enable flag

The user-supplied Windows query reports `VirtualizationBasedSecurityStatus=2`,
`SecurityServicesConfigured={0}` and `SecurityServicesRunning={0}`: VBS itself is
running, but no security services are listed as configured/running. This is not
evidence of active Credential Guard or Memory Integrity.

The observed local DeviceGuard key contains
`EnableVirtualizationBasedSecurity=1`. The policy-key query returned not found.
`Locked` was not shown, which does not establish absence of firmware locking.
Microsoft documents the [local VBS enable key](https://learn.microsoft.com/en-us/windows/security/hardware-security/enable-virtualization-based-protection-of-code-integrity)
and [0 as disabled for the corresponding VBS policy](https://learn.microsoft.com/en-us/windows/client-management/mdm/policy-csp-deviceguard).
The controlled next test changes only the observed local enable DWORD, without
creating policy keys or changing LSA, HVCI or firmware settings.

This temporarily disables VBS protections until rolled back. The BitLocker key
and host-impact cautions above still apply. Do not alter
`RequireMicrosoftSignedBootChain`, `HyperVVirtualizationBasedSecurityOptout`,
`tscsyncpolicy`, `useplatformclock` or `disabledynamictick` alongside this test.
Their existing values are retained in the evidence index.

After saving work and shutting down Ubuntu normally, in **Windows administrator
PowerShell** run:

```powershell
reg add "HKLM\SYSTEM\CurrentControlSet\Control\DeviceGuard" /v EnableVirtualizationBasedSecurity /t REG_DWORD /d 0 /f
reg query "HKLM\SYSTEM\CurrentControlSet\Control\DeviceGuard" /v EnableVirtualizationBasedSecurity
```

Require a successful write and a query showing `0x0`. If blocked or ineffective,
retain the error instead of changing permissions, disabling Secure Boot or trying
to bypass a firmware/policy lock. Then **Restart Windows**, start Ubuntu and
supply the fresh VBox.log. Verify VBS and hypervisor state on Windows as well:

```powershell
Get-CimInstance Win32_ComputerSystem | Format-List HypervisorPresent
Get-CimInstance -ClassName Win32_DeviceGuard -Namespace root\Microsoft\Windows\DeviceGuard | Format-List VirtualizationBasedSecurityStatus,SecurityServicesConfigured,SecurityServicesRunning
```

A successful configuration comparison requires native VT-x in the fresh VM log;
if VBS remains running or the backend is still NEM, retain the failure and inspect
that configuration before further settings changes. The registry edit/restart
above is **NOT RUN** by the agent; a written procedure is not a repaired host.

Restore this specific VBS flag to its observed original value after the experiment
when returning to the previous security configuration. In administrator PowerShell:

```powershell
reg add "HKLM\SYSTEM\CurrentControlSet\Control\DeviceGuard" /v EnableVirtualizationBasedSecurity /t REG_DWORD /d 1 /f
```

Restart Windows for the restored VBS configuration to take effect. Restoring the
Windows hypervisor launch setting is a separate rollback documented below; the
host setting and VBS flag must each be tracked independently.

## Follow-up: explicit VSM launch control

The local-registry experiment failed runtime verification: the flag persisted
at 0, yet Win32_DeviceGuard still reported VBS running (2). A Windows
Kernel-General event 12 records an OS start at `2026-10-23T18:11:24.500000000Z`,
corroborating the user's physical-host restart. The complete boot-entry output
still contains `hypervisorlaunchtype Off` and has no explicit `vsmlaunchtype`.
The read-only Device Guard log query returned no events; no firmware-lock or
policy conclusion is drawn from that absence.

Microsoft documents [`vsmlaunchtype Off|Auto`](https://learn.microsoft.com/en-us/windows-hardware/drivers/devtest/bcdedit--set)
as a separate control for Virtual Secure Mode startup. It does not document this
as a guarantee of disabling Hyper-V. The next single-variable experiment is an
explicit VSM launch setting, followed by verification. This can disable VSM/VBS
protections for the test boot configuration. Keep the previously noted recovery
key and host-impact precautions in mind.

After saving work and shutting down Ubuntu normally, in **Windows administrator
PowerShell** run:

```powershell
bcdedit /set "{current}" vsmlaunchtype Off
bcdedit /enum "{current}"
```

Require a successful set and an explicit `vsmlaunchtype Off` in the output.
If denied by a policy or other error, retain the error and stop. This procedure
does not remove firmware variables, disable Secure Boot, change permissions or
uninstall Windows features. Leave other boot/timer options and registry values
unchanged while testing this one control. Then **Restart Windows**, start Ubuntu,
and provide the fresh current-session VBox.log for backend and runtime checks.

The setting was absent in the verified prior output, so restore its prior absence
in administrator PowerShell when rolling back:

```powershell
bcdedit /deletevalue "{current}" vsmlaunchtype
```

Restart Windows after rollback. Track this independently from the local VBS-flag
and hypervisor-launch rollbacks already documented. Execution of this new VSM
launch command and all subsequent native-backend acceptance remain **NOT RUN**.

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
