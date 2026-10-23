# M4 implementation handoff (in progress)

Branch: `feat/m4-parking-traffic`. M4 is not complete. T07–T10 remain NOT RUN
at the ROS scenario layer. M5–M7 have not started, following AGENTS.md's one
milestone at a time rule.

Implemented: lock-protected parking allocation, operation-scoped idempotency,
vehicle exclusivity, TTL validation, ownership release, sensor debounce, and
sensing-preserving expiry. ROS adapters provide the public parking services and
state, and the traffic topic. Traffic validates reported corridors, uses a
five-second median speed window, derives capacities with floor(length / 0.80 m),
and distinguishes normal/congested/blocked/unknown internally. Free-flow design
speed is 0.35 m/s. Obstructions use observed vehicle kind `obstacle`.

Source reviewed directly: local Assignment PDF §§11–12, printed pp17–18.
Stable occupancy debounce is 0.5 s; input freshness is 1.0 s, with 2 Hz traffic
publication. Median is the declared robust speed estimator. Preferred parking
falls back in slot-ID order; geometry-based nearest allocation remains open.

New internal input `/parking/entrance_clear`: Bool, reliable volatile depth 1,
sensor/bridge owned, local receipt timeout 0.5 s. No producer is supplied yet;
absence denies opening. Barrier status has a separate 0.5 s receipt watchdog;
request never means acknowledgment. The existing simulator still holds barrier
closed, so end-to-end actuator interlock is not established.

Remaining before M4 acceptance: simulator entrance/owner interlocks and measured
barrier acknowledgment; reset acknowledgments; integrated launch replacing road
fixtures; events/labels and source-loss diagnostics; per-vehicle frozen-source
handling (public array has a shared acquisition stamp); bounded idempotency
retention; nearest-slot policy; real-node T07–T10 and timing/bag evidence.
No M4 launch was added because these integration gaps remain.

Environment: host has no ros2 executable. Docker socket access was denied for
`docker images --format '{{.Repository}}:{{.Tag}}'`. No permission changes or
privileged workarounds attempted. Unit dependencies use an isolated /tmp venv.
Pure tests cannot establish service response latency or ROS acceptance.

Local verification: four pytest tests PASS (20 concurrent reservation pairs,
ten free-flow repetitions, ownership/TTL/stale/geometry/obstruction cases),
flake8 PASS with repository 99-column limit, `bash scripts/check_fast.sh` PASS.
Commands and scope are retained in `evidence/m4-local.json`. The commit containing
that file identifies the tested implementation slice; no scenario PASS is claimed.
