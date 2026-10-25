# Architecture

Implemented in part. Ten of the 13 assignment nodes (A §4 pp5–6) exist. `robot_manager`
and `metrics_logger` are missing, and the actuator-bridge role runs inside
`scenario_runner`. See the [node table in the compliance register](compliance.md#required-nodes-a-4-pp56-41-p6-h-51-p11).
The diagrams below are the design. Acceptance status lives in the [test matrix](test-matrix.md).

## Development environment

```mermaid
flowchart TD
  H["VirtualBox VM · Ubuntu 22.04 host"] --> D["Docker · Ubuntu 24.04 + ROS 2 Jazzy (smh-* images)"]
  H --> G["Local Git checkout"]
  G --> D
  D --> B["colcon build/test + real-node verifiers"]
  B --> E["Evidence (evidence/, docs/)"]
  W["Teammates: Windows → WSL2 · Ubuntu 24.04"] -.-> G
```

All local acceptance runs use the container ([M0](m0.md)). The WSL path in
[setup](setup.md) is the documented teammate alternative and has not been executed.

## Runtime control and observations

```mermaid
flowchart TD
  SIM["Seeded 2D simulator"] --> OBS["Observation streams"]
  OBS --> PER["Perception and prediction"]
  OBS --> PT["Parking and traffic"]
  PER --> HUB["Hub coordinator"]
  PT --> HUB
  PT --> ROUTE["Route planner"]
  HUB --> MGR["Bus and robot managers"]
  ROUTE --> MGR
  MGR --> SAFE["Safety supervisor"]
  OBS --> SAFE
  HUB --> SAFE
  ESTOP["Latched emergency stop"] --> SAFE
  SAFE --> ADAPT["Actuator adapters and watchdogs"]
  ADAPT --> SIM
  SIM --> TRUTH["Evaluator-only ground truth"]
```

Safety is the only final velocity publisher. Ground truth supports evaluation, never perception or planning decisions. Crossing grants are constrained by observed clearance, pedestrians, freshness, and ownership; lease expiry does not prove the crossing is empty.

## Package boundaries

| Package | Responsibility |
|---|---|
| smart_hub_interfaces | Required messages, services, actions |
| smart_hub_sim | M1 map, deterministic world, sensor streams, adapters |
| smart_hub_perception | Tracking, queue and crossing occupancy |
| smart_hub_prediction | Features, persistence, trained regression |
| smart_hub_control | Bus, robot, parking, traffic, planner, coordinator |
| smart_hub_safety | Independent safety authority |
| smart_hub_bringup | Launch, config, scenario runner, logging |
| smart_hub_tests | Unit, ROS integration, scenario and fault evaluation |

This multi-package split deviates from the single `smart_hub` package that A §19.1 p26 recommends. The node responsibilities and published contracts are what A grades.

## Mission lifecycle

```mermaid
stateDiagram-v2
  [*] --> Idle
  Idle --> Active: valid safe goal
  Active --> Holding: arrival observed
  Holding --> Succeeded: stable for one second
  Active --> Stopping: accepted cancellation
  Stopping --> Canceled: zero confirmed
  Active --> Aborted: timeout or safety fault
  Holding --> Aborted: safety fault
  Active --> Replanning: route invalidated
  Replanning --> Active: fresh route
  Replanning --> Aborted: deadline or no route
```

Safety overrides velocity independently of action callbacks. Every terminal path returns a populated result. Rejected requests never enter Active.

## Evidence pipeline

```mermaid
flowchart TD
  CONFIG["Scenario, seed, commit and model"] --> RUN["Real ROS run"]
  RUN --> RAW["Logs, events and metrics"]
  RAW --> EVAL["Independent evaluation"]
  EVAL --> STATUS{"Thresholds met?"}
  STATUS -->|Yes| PASS["PASS with evidence"]
  STATUS -->|No| FAIL["FAIL with measurements"]
  PASS --> REPORT["Report and submission"]
  FAIL --> REPORT
```

## M1 package skeletons (historical, 2026-10-22)

All eight proposed package boundaries now exist under `src/`. Interfaces use
ament_cmake/rosidl; the other seven use ament_python with declared dependencies
and resource/package installation metadata. The simulator package installs the
M1 map configuration. No console entry points or placeholder runtime nodes are
installed. The map belongs to smart_hub_sim; safety and adapters remain distinct
future runtime responsibilities. Build and review evidence is tracked in [M1](m1.md).
