# Proposed architecture

Design target; no nodes have been implemented in this repository.

## Development environment

```mermaid
flowchart TD
  W["Windows host"] --> L["WSL2 · Ubuntu 24.04"]
  L --> C["Codex CLI"]
  L --> R["ROS 2 Jazzy"]
  L --> G["Local Git checkout"]
  C --> G
  G --> B["Build and test"]
  R --> B
  B --> E["Evidence"]
```

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

## Proposed package boundaries

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

Package grouping is a proposal; node responsibilities and published contracts remain authoritative.

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
