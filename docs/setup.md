# Current environment

Use [the M0 container workflow](m0.md) for the selected Oracle VirtualBox Ubuntu 22.04 host. The instructions below describe the earlier Windows alternative, not the current machine.

# Windows → WSL2 → Ubuntu 24.04 setup

Status: documented target, not executed on a teammate's computer.

## 1. Windows preparation

Use a supported Windows installation with virtualization enabled. In administrator PowerShell:

```powershell
wsl --list --online
wsl --install -d Ubuntu-24.04
```

Restart if requested. Open Ubuntu and create the Linux username/password. Then check in PowerShell:

```powershell
wsl --update
wsl --list --verbose
```

Ubuntu-24.04 must show VERSION 2. If it shows 1, run:

```powershell
wsl --set-version Ubuntu-24.04 2
```

Do not reinstall or unregister an existing distro containing work.

## 2. Ubuntu preparation

All following Bash commands run in Ubuntu, using a normal user:

```bash
cat /etc/os-release
uname -m
sudo apt update
sudo apt install -y git curl ca-certificates
mkdir -p ~/projects
cd ~/projects
git clone https://github.com/smart-mobility-lab-team-C/smart-mobility-hub.git
cd smart-mobility-hub
```

Keep the repository in the Linux filesystem, not /mnt/c. Record CPU, memory, disk space and architecture before installing ROS. Resource requirements are to be measured during the first simulator run; no fixed performance promise is made here.

## 3. Codex CLI

Use the official Linux installation instructions. Current standalone installer:

```bash
curl -fsSL https://chatgpt.com/codex/install.sh -o /tmp/codex-install.sh
less /tmp/codex-install.sh
sh /tmp/codex-install.sh
```

Open a new terminal if PATH changes, then:

```bash
codex --version
cd ~/projects/smart-mobility-hub
codex
```

Complete the offered sign-in flow. Do not put credentials in Git or chat. Do not use sudo for Codex. See docs/codex-workflow.md for the first task.

## 4. Git authentication

Public clone works without write authentication. Each member needs repository Write permission and their own Git authentication inside WSL. Configure their own Git author name/email. Use GitHub's supported credential manager or SSH flow; never embed a token in a remote URL.

Gate: push a personal branch and open a PR successfully. ChatGPT's GitHub connection and WSL Git credentials are separate.

## 5. ROS installation handoff

Have Codex implement the bootstrap contract in docs/automation.md using the current official ROS Jazzy Ubuntu deb instructions. The ROS documentation page was access-blocked during this documentation session, so exact apt-repository/key commands are deliberately not copied here.

The script must validate Ubuntu 24.04, architecture, UTF-8 locale, ROS apt source, and existing installations; then install Jazzy and development tools, resolve package dependencies, and log versions. Do not install Humble into this workspace.

After installation, in separate Ubuntu terminals:

```bash
source /opt/ros/jazzy/setup.bash
ros2 run demo_nodes_cpp talker
```

```bash
source /opt/ros/jazzy/setup.bash
ros2 run demo_nodes_py listener
```

Gate: listener receives messages. Stop both with Ctrl+C. Save actual output and versions. RViz is useful for display; headless tests must remain possible.

## References

Checked 2026-10-22:
- Microsoft WSL installation: https://learn.microsoft.com/en-us/windows/wsl/install
- Official Codex CLI: https://learn.chatgpt.com/docs/codex/cli
- ROS Jazzy installation (retrieve before implementing): https://docs.ros.org/en/jazzy/Installation/Ubuntu-Install-Debs.html

