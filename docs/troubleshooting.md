# Troubleshooting

| Symptom | First checks | Corrective direction |
|---|---|---|
| WSL install fails | Windows version, virtualization, WSL status | Follow Microsoft troubleshooting; preserve existing distro |
| Wrong Ubuntu release | cat /etc/os-release | Use a separate supported 24.04 distro; do not mix ROS distributions |
| codex not found | New terminal; PATH; installer log | Follow official installer output; do not use root as workaround |
| ROS commands missing | Source /opt/ros/jazzy/setup.bash | Verify installation before building |
| Listener gets nothing | Both terminals sourced; domain ID; DDS/network settings | Diagnose local same-distro talker/listener first |
| Python cannot import rclpy | Python interpreter and ROS environment | Use ROS-compatible system Python; avoid unrelated venv/Conda |
| RViz display fails | WSL graphics support and display | Headless build/tests first; display troubleshooting separately |
| Git push denied | Git identity, remote, accepted invite, Write access | Authenticate inside WSL; public read does not grant push |
| Scripts fail with CRLF | File line endings | Keep shell scripts LF via .gitattributes |
| Build fails | First build error, dependency resolution, logs | Fix earliest cause; preserve evidence |
| Watchdog timing differs | Wall/sim clock, source/receipt times, host load | Measure both; retain thresholds and report failures |

Never delete the workspace or clear evidence as a first diagnostic step. Record the exact failed command, environment and log path.
