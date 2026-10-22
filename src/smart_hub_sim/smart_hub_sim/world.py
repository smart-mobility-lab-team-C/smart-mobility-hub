"""Deterministic, fixed-step M2 world state and kinematics."""

from __future__ import annotations

from dataclasses import dataclass
import math
import random
from typing import Optional, Sequence, Tuple

from .geometry import segment_distance, swept_clear, swept_segments_clear


DT_SEC = 0.05
BUS_START = (1.0, 2.0, 0.0)
ROBOT_START = (3.0, 6.0, 0.0)
BUS_DOCK = (8.0, 4.0, 0.0)
BUS_RADIUS = 0.3
ROBOT_RADIUS = 0.2
CLEARANCE = 0.2
BUS_SPEED_CAP = 0.4
ROBOT_SPEED_CAP = 0.25
ANGULAR_SPEED_CAP = 1.0
EDGE_TOLERANCE = 1e-6

# Assignment section 3.1, printed p4; coordinates are from map_m1.yaml.
BUS_EDGES = (
    ('A-Cs', (1.0, 2.0), (5.0, 2.0)),
    ('A-N', (1.0, 2.0), (1.0, 4.0)),
    ('B-Cn', (8.0, 4.0), (5.0, 4.0)),
    ('B-U', (8.0, 4.0), (11.0, 4.0)),
    ('Cn-N', (5.0, 4.0), (1.0, 4.0)),
    ('Cs-J', (5.0, 2.0), (9.0, 2.0)),
    ('E-J', (11.0, 2.0), (9.0, 2.0)),
    ('E-U', (11.0, 2.0), (11.0, 4.0)),
)
ROBOT_EDGES = (
    ('B-Cn', (8.0, 4.0), (5.0, 4.0)),
    ('B-U', (8.0, 4.0), (11.0, 4.0)),
    ('Cn-Cs', (5.0, 4.0), (5.0, 2.0)),
    ('Cn-W', (5.0, 4.0), (5.0, 6.0)),
    ('Cs-J', (5.0, 2.0), (9.0, 2.0)),
    ('D-J', (9.0, 1.0), (9.0, 2.0)),
    ('E-J', (11.0, 2.0), (9.0, 2.0)),
    ('E-U', (11.0, 2.0), (11.0, 4.0)),
    ('R-W', (3.0, 6.0), (5.0, 6.0)),
)


@dataclass
class AgentState:
    """Ground-truth pose and measured planar velocity for one simulated agent."""

    x: float
    y: float
    yaw: float
    linear_x: float = 0.0
    angular_z: float = 0.0

    @property
    def speed(self) -> float:
        """Return the absolute measured forward speed in metres per second."""
        return abs(self.linear_x)


class World:
    """Seeded world with deterministic physics and a separate observation RNG."""

    def __init__(self, seed: int = 1, obstacle_enabled: bool = False) -> None:
        self.obstacle_enabled = obstacle_enabled
        self.reset(seed)

    def reset(self, seed: int) -> None:
        """Reset to the exact baseline and seed independent random streams."""
        self.seed = int(seed)
        self.physics_rng = random.Random(self.seed)
        self.observation_rng = random.Random(self.seed ^ 0x5A17C9E3)
        self.bus = AgentState(*BUS_START)
        self.robot = AgentState(*ROBOT_START)
        self.tick_count = 0
        self.door_request = False
        self.barrier_request = False

    @property
    def obstacles(self) -> Tuple[Tuple[float, float, float], ...]:
        """Return configured static obstacle circles."""
        if self.obstacle_enabled:
            return ((7.0, 2.0, 0.35),)
        return ()

    @staticmethod
    def _pose_after(
        agent: AgentState, linear_x: float, angular_z: float, dt: float
    ) -> AgentState:
        """Integrate one unicycle command, using the exact constant-turn arc."""
        yaw_end = agent.yaw + angular_z * dt
        if abs(angular_z) < 1e-9:
            x_end = agent.x + linear_x * dt * math.cos(agent.yaw)
            y_end = agent.y + linear_x * dt * math.sin(agent.yaw)
        else:
            radius = linear_x / angular_z
            x_end = agent.x + radius * (math.sin(yaw_end) - math.sin(agent.yaw))
            y_end = agent.y - radius * (math.cos(yaw_end) - math.cos(agent.yaw))
        yaw_end = math.atan2(math.sin(yaw_end), math.cos(yaw_end))
        return AgentState(x_end, y_end, yaw_end, linear_x, angular_z)

    @staticmethod
    def _bounded_command(
        command: Optional[Tuple[float, float]], speed_cap: float
    ) -> Tuple[float, float]:
        """Clamp supported planar command components to configured caps."""
        if command is None:
            return 0.0, 0.0
        linear, angular = command
        if not math.isfinite(linear) or not math.isfinite(angular):
            return 0.0, 0.0
        linear = max(-speed_cap, min(speed_cap, linear))
        angular = max(-ANGULAR_SPEED_CAP, min(ANGULAR_SPEED_CAP, angular))
        return linear, angular

    @staticmethod
    def _allowed_edges(agent: str):
        """Return map centerline segments permitted for the requested agent."""
        if agent == 'bus':
            return BUS_EDGES
        if agent == 'robot':
            return ROBOT_EDGES
        return ()

    @classmethod
    def _motion_on_allowed_edge(
        cls, agent: str, start: Tuple[float, float], end: Tuple[float, float]
    ) -> bool:
        """Allow translation only when both endpoints share a permitted edge."""
        if math.hypot(end[0] - start[0], end[1] - start[1]) <= EDGE_TOLERANCE:
            return True
        for _edge_id, edge_start, edge_end in cls._allowed_edges(agent):
            if (
                segment_distance(
                    start[0], start[1], edge_start[0], edge_start[1],
                    edge_end[0], edge_end[1],
                ) <= EDGE_TOLERANCE
                and segment_distance(
                    end[0], end[1], edge_start[0], edge_start[1],
                    edge_end[0], edge_end[1],
                ) <= EDGE_TOLERANCE
            ):
                return True
        return False

    @classmethod
    def nearest_edge_id(cls, agent: str, x: float, y: float) -> str:
        """Return the closest permitted edge ID for an observed map position."""
        edges = cls._allowed_edges(agent)
        if not edges or not math.isfinite(x) or not math.isfinite(y):
            return ''
        edge_id, _ = min(
            (
                (
                    candidate_id,
                    segment_distance(
                        x, y, edge_start[0], edge_start[1],
                        edge_end[0], edge_end[1],
                    ),
                )
                for candidate_id, edge_start, edge_end in edges
            ),
            key=lambda item: (item[1], item[0]),
        )
        return edge_id

    def step(
        self,
        bus_command: Optional[Tuple[float, float]] = None,
        robot_command: Optional[Tuple[float, float]] = None,
        dt: float = DT_SEC,
    ) -> None:
        """Advance one fixed physics step, rejecting unsafe swept trajectories."""
        if not math.isfinite(dt) or dt <= 0.0:
            raise ValueError('dt must be a positive finite duration')
        bus_v, bus_w = self._bounded_command(bus_command, BUS_SPEED_CAP)
        robot_v, robot_w = self._bounded_command(robot_command, ROBOT_SPEED_CAP)
        bus_next = self._pose_after(self.bus, bus_v, bus_w, dt)
        robot_next = self._pose_after(self.robot, robot_v, robot_w, dt)
        if not self._motion_on_allowed_edge(
            'bus', (self.bus.x, self.bus.y), (bus_next.x, bus_next.y)
        ):
            bus_next = AgentState(self.bus.x, self.bus.y, self.bus.yaw)
        if not self._motion_on_allowed_edge(
            'robot', (self.robot.x, self.robot.y), (robot_next.x, robot_next.y)
        ):
            robot_next = AgentState(self.robot.x, self.robot.y, self.robot.yaw)

        bus_clear = swept_clear(
            (self.bus.x, self.bus.y), (bus_next.x, bus_next.y), BUS_RADIUS,
            self.obstacles, (), CLEARANCE,
        )
        robot_clear = swept_clear(
            (self.robot.x, self.robot.y), (robot_next.x, robot_next.y), ROBOT_RADIUS,
            self.obstacles, (), CLEARANCE,
        )
        agents_clear = swept_segments_clear(
            (self.bus.x, self.bus.y), (bus_next.x, bus_next.y), BUS_RADIUS,
            (self.robot.x, self.robot.y), (robot_next.x, robot_next.y), ROBOT_RADIUS,
            CLEARANCE,
        )

        if not bus_clear or not agents_clear:
            bus_next = AgentState(self.bus.x, self.bus.y, self.bus.yaw)
        if not robot_clear or not agents_clear:
            robot_next = AgentState(self.robot.x, self.robot.y, self.robot.yaw)
        self.bus = bus_next
        self.robot = robot_next
        self.tick_count += 1

    @property
    def door_open(self) -> bool:
        """Return measured door state under the independent stopped-at-B interlock."""
        distance = math.hypot(self.bus.x - BUS_DOCK[0], self.bus.y - BUS_DOCK[1])
        yaw_error = abs(math.atan2(
            math.sin(self.bus.yaw - BUS_DOCK[2]),
            math.cos(self.bus.yaw - BUS_DOCK[2]),
        ))
        return bool(
            self.door_request
            and distance <= 0.2
            and yaw_error <= 0.17
            and self.bus.speed < 0.02
        )

    @property
    def barrier_open(self) -> bool:
        """Return barrier state; M2 has no owner-bearing open authorization."""
        return False

    def noisy_pose(self, agent: AgentState) -> Tuple[float, float, float]:
        """Return a noisy perception sample from the isolated observation RNG."""
        rng = self.observation_rng
        return (
            agent.x + rng.gauss(0.0, 0.02),
            agent.y + rng.gauss(0.0, 0.02),
            agent.yaw + rng.gauss(0.0, 0.01),
        )

    def ground_truth(self) -> Sequence[Tuple[str, str, AgentState]]:
        """Return evaluator-only truth records, in stable identifier order."""
        return (('bus', 'bus', self.bus), ('robot', 'robot', self.robot))
