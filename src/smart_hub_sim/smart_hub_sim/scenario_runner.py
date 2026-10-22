"""M2 ROS simulator, observation publisher, and independent command adapter."""

from __future__ import annotations

import math
from threading import RLock
import time
from typing import Optional, Tuple
import uuid

from geometry_msgs.msg import TransformStamped, Twist
from nav_msgs.msg import Odometry
import rclpy
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy
from sensor_msgs.msg import Image
from smart_hub_interfaces.msg import (
    CrossingState,
    SafetyState,
    SlotObservation,
    SlotObservationArray,
    VehicleState,
    VehicleStateArray,
)
from smart_hub_interfaces.srv import ResetScenario
from std_msgs.msg import Bool
from tf2_ros import TransformBroadcaster

from .geometry import intersects_crossing
from .world import (
    AgentState,
    BUS_RADIUS,
    BUS_SPEED_CAP,
    DT_SEC,
    ROBOT_RADIUS,
    ROBOT_SPEED_CAP,
    World,
)


def _qos(depth: int, transient_local: bool = False) -> QoSProfile:
    """Create reliable QoS, optionally transient-local for state topics."""
    return QoSProfile(
        history=HistoryPolicy.KEEP_LAST,
        depth=depth,
        reliability=ReliabilityPolicy.RELIABLE,
        durability=(
            DurabilityPolicy.TRANSIENT_LOCAL
            if transient_local
            else DurabilityPolicy.VOLATILE
        ),
    )


class ScenarioRunner(Node):
    """Run deterministic physics and publish ROS observations at contract rates."""

    SAFETY_TTL_SEC = 0.5
    CROSSING_TTL_SEC = 0.5

    def __init__(self) -> None:
        super().__init__('scenario_runner')
        self.declare_parameter('seed', 17)
        self.declare_parameter('obstacle_enabled', False)
        self.declare_parameter('command_timeout_sec', 0.5)
        self.declare_parameter('robot_speed_limit', 0.25)
        self.declare_parameter('bus_speed_limit', 0.4)
        self.declare_parameter('angular_speed_limit', 1.0)
        self.declare_parameter('future_tolerance_sec', 0.0)
        self._command_timeout_sec = self._validated_parameter(
            'command_timeout_sec', 0.0, 0.5, lower_inclusive=False
        )
        self._robot_speed_limit = self._validated_parameter(
            'robot_speed_limit', 0.0, ROBOT_SPEED_CAP, lower_inclusive=False
        )
        self._bus_speed_limit = self._validated_parameter(
            'bus_speed_limit', 0.0, BUS_SPEED_CAP, lower_inclusive=False
        )
        self._angular_speed_limit = self._validated_parameter(
            'angular_speed_limit', 0.0, 1.0, lower_inclusive=False
        )
        self._future_tolerance_sec = self._validated_parameter(
            'future_tolerance_sec', 0.0, 0.0
        )
        seed = int(self.get_parameter('seed').value)
        obstacle_enabled = bool(self.get_parameter('obstacle_enabled').value)
        if obstacle_enabled:
            raise ValueError('M2 baseline has no obstacle observation contract; keep disabled')
        self.world = World(seed=seed, obstacle_enabled=obstacle_enabled)
        self._lock = RLock()
        self._run_id = str(uuid.uuid4())
        self._tick = 0
        self._commands = {
            'bus': ((0.0, 0.0), time.monotonic()),
            'robot': ((0.0, 0.0), time.monotonic()),
        }
        self._safety: Optional[SafetyState] = None
        self._safety_received = 0.0
        self._crossing: Optional[CrossingState] = None
        self._crossing_received = 0.0

        self._vehicles_pub = self.create_publisher(
            VehicleStateArray, '/hub/vehicles', _qos(10)
        )
        self._truth_pub = self.create_publisher(
            VehicleStateArray, '/sim/evaluator/ground_truth', _qos(10)
        )
        self._parking_pub = self.create_publisher(
            SlotObservationArray, '/parking/observed', _qos(10)
        )
        self._odom_pub = self.create_publisher(Odometry, '/robot/odom', _qos(10))
        self._bus_odom_pub = self.create_publisher(
            Odometry, '/bus/odom', _qos(10)
        )
        self._image_pub = self.create_publisher(
            Image, '/camera/image_raw', rclpy.qos.qos_profile_sensor_data
        )
        self._door_pub = self.create_publisher(Bool, '/bus/door_open', _qos(1))
        self._barrier_pub = self.create_publisher(
            Bool, '/parking/barrier_open', _qos(1)
        )
        self._bus_cmd_sub = self.create_subscription(
            Twist, '/bus/cmd_vel', self._bus_command, _qos(1)
        )
        self._robot_cmd_sub = self.create_subscription(
            Twist, '/robot/cmd_vel', self._robot_command, _qos(1)
        )
        self._safety_sub = self.create_subscription(
            SafetyState, '/hub/safety', self._safety_state, _qos(1, True)
        )
        self._crossing_sub = self.create_subscription(
            CrossingState, '/crossing/state', self._crossing_state, _qos(1, True)
        )
        self._door_request_sub = self.create_subscription(
            Bool, '/bus/door_request', self._door_request, _qos(1)
        )
        self._barrier_request_sub = self.create_subscription(
            Bool, '/parking/barrier_request', self._barrier_request, _qos(1)
        )
        self._reset_srv = self.create_service(
            ResetScenario, '/sim/reset_world', self._reset_scenario
        )
        self._tf = TransformBroadcaster(self)
        self._timer = self.create_timer(DT_SEC, self._step)
        self.get_logger().info(
            f'M2 simulator ready: seed={seed} run_id={self._run_id}'
        )

    def _validated_parameter(
        self,
        name: str,
        minimum: float,
        maximum: float,
        lower_inclusive: bool = True,
    ) -> float:
        """Read a numeric runtime setting and enforce its approved range."""
        value = float(self.get_parameter(name).value)
        lower_ok = value >= minimum if lower_inclusive else value > minimum
        if not math.isfinite(value) or not lower_ok or value > maximum:
            left = '[' if lower_inclusive else '('
            raise ValueError(f'{name} must be {left}{minimum}, {maximum}]')
        return value

    @staticmethod
    def _twist_values(message: Twist) -> Optional[Tuple[float, float]]:
        """Validate a planar unicycle Twist and return (forward, yaw) command."""
        values = (
            message.linear.x,
            message.linear.y,
            message.linear.z,
            message.angular.x,
            message.angular.y,
            message.angular.z,
        )
        if not all(math.isfinite(value) for value in values):
            return None
        if any(value != 0.0 for value in values[1:5]):
            return None
        return message.linear.x, message.angular.z

    def _accept_command(self, agent: str, message: Twist) -> None:
        """Record a final command and its monotonic receipt time, or reject it."""
        values = self._twist_values(message)
        with self._lock:
            if values is None:
                self._commands[agent] = ((0.0, 0.0), time.monotonic())
                return
            speed_cap = (
                self._bus_speed_limit
                if agent == 'bus'
                else self._robot_speed_limit
            )
            linear = max(-speed_cap, min(speed_cap, values[0]))
            angular = max(
                -self._angular_speed_limit,
                min(self._angular_speed_limit, values[1]),
            )
            self._commands[agent] = ((linear, angular), time.monotonic())

    def _bus_command(self, message: Twist) -> None:
        """Receive the safety-supervised bus command."""
        self._accept_command('bus', message)

    def _robot_command(self, message: Twist) -> None:
        """Receive the safety-supervised robot command."""
        self._accept_command('robot', message)

    def _safety_state(self, message: SafetyState) -> None:
        """Track the supervisor heartbeat independently of its aggregate permission."""
        with self._lock:
            self._safety = message
            self._safety_received = time.monotonic()

    def _crossing_state(self, message: CrossingState) -> None:
        """Track the crossing owner and validity with local receipt age."""
        with self._lock:
            self._crossing = message
            self._crossing_received = time.monotonic()

    def _door_request(self, message: Bool) -> None:
        """Apply the bus door request; measured opening remains interlocked in World."""
        with self._lock:
            self.world.door_request = bool(message.data)

    def _barrier_request(self, message: Bool) -> None:
        """Remember barrier requests while the ownerless M2 barrier stays closed."""
        with self._lock:
            self.world.barrier_request = bool(message.data)

    @staticmethod
    def _path_needs_crossing(
        start: AgentState, end: AgentState, radius: float
    ) -> bool:
        """Return true when the small-step swept footprint touches the crossing."""
        return intersects_crossing(end.x, end.y, radius) or intersects_crossing(
            start.x, start.y, radius
        )

    def _crossing_allows(self, agent: str, now: float) -> bool:
        """Require a recent valid exclusive owner and clear pedestrian measurement."""
        state = self._crossing
        other = self.world.robot if agent == 'bus' else self.world.bus
        other_radius = ROBOT_RADIUS if agent == 'bus' else BUS_RADIUS
        # An independent physical interlock prevents entry even if observations err.
        if intersects_crossing(other.x, other.y, other_radius):
            return False
        return bool(
            state is not None
            and now - self._crossing_received <= self.CROSSING_TTL_SEC
            and state.header.frame_id == 'map'
            and self._header_is_fresh(state.header, self.CROSSING_TTL_SEC)
            and state.valid
            and state.state == 'OWNED'
            and bool(state.token)
            and state.owner_id == agent
            and not state.pedestrian_present
        )

    def _header_is_fresh(self, header, max_age_sec: float) -> bool:
        """Check source-stamp age in ROS time, including bounded future tolerance."""
        stamp_ns = header.stamp.sec * 1_000_000_000 + header.stamp.nanosec
        now_ns = self.get_clock().now().nanoseconds
        age_sec = (now_ns - stamp_ns) / 1_000_000_000.0
        return -self._future_tolerance_sec <= age_sec <= max_age_sec

    def _active_command(self, agent: str, now: float) -> Tuple[float, float]:
        """Apply independent command and supervisor watchdogs before physics."""
        command, received = self._commands[agent]
        if now - received > self._command_timeout_sec:
            return 0.0, 0.0
        if (
            self._safety is None
            or now - self._safety_received > self.SAFETY_TTL_SEC
            or self._safety.header.frame_id != 'map'
            or not self._header_is_fresh(self._safety.header, self.SAFETY_TTL_SEC)
        ):
            return 0.0, 0.0
        if self._safety.stop_latched:
            return 0.0, 0.0
        if agent == 'bus' and self.world.door_open and command != (0.0, 0.0):
            return 0.0, 0.0
        return command

    def _stamp(self):
        """Return current ROS time for acquisition or publication stamps."""
        return self.get_clock().now().to_msg()

    def _vehicle_record(
        self, vehicle_id: str, kind: str, state: AgentState, noisy: bool
    ) -> VehicleState:
        """Build one map-frame vehicle record from truth or noisy observation."""
        record = VehicleState()
        record.vehicle_id = vehicle_id
        record.kind = kind
        if noisy:
            x, y, yaw = self.world.noisy_pose(state)
        else:
            x, y, yaw = state.x, state.y, state.yaw
        record.pose.x = x
        record.pose.y = y
        record.pose.theta = yaw
        record.speed_mps = state.speed
        record.edge_id = self.world.nearest_edge_id(kind, x, y)
        record.valid = True
        return record

    def _publish_vehicles(self, stamp) -> None:
        """Publish noisy perception records and isolated evaluator ground truth."""
        observations = VehicleStateArray()
        observations.header.stamp = stamp
        observations.header.frame_id = 'map'
        truth = VehicleStateArray()
        truth.header.stamp = stamp
        truth.header.frame_id = 'map'
        for vehicle_id, kind, state in self.world.ground_truth():
            observations.vehicles.append(
                self._vehicle_record(vehicle_id, kind, state, noisy=True)
            )
            truth.vehicles.append(
                self._vehicle_record(vehicle_id, kind, state, noisy=False)
            )
        self._vehicles_pub.publish(observations)
        self._truth_pub.publish(truth)

    def _publish_parking(self, stamp) -> None:
        """Publish synthetic slot observations using the observation-only RNG."""
        message = SlotObservationArray()
        message.header.stamp = stamp
        message.header.frame_id = 'map'
        for slot_id in ('P1', 'P2', 'P3'):
            observation = SlotObservation()
            observation.slot_id = slot_id
            observation.occupied = False
            observation.confidence = max(
                0.0, min(1.0, self.world.observation_rng.gauss(0.97, 0.01))
            )
            observation.valid = True
            message.slots.append(observation)
        self._parking_pub.publish(message)

    def _publish_image(self, stamp) -> None:
        """Publish a compact synthetic scene image without detector annotations."""
        width, height = 160, 96
        pixels = bytearray([238] * (width * height * 3))
        # Draw a neutral crossing band and simple colored scene blobs only.
        for y in range(30, 57):
            for x in range(58, 73):
                offset = (y * width + x) * 3
                pixels[offset:offset + 3] = bytes((178, 178, 178))
        for x in range(59, 73, 5):
            for y in range(31, 56):
                if (x // 5) % 2 == 0:
                    offset = (y * width + x) * 3
                    pixels[offset:offset + 3] = bytes((245, 245, 245))
        self._draw_agent(pixels, width, height, self.world.bus, (35, 35, 220))
        self._draw_agent(pixels, width, height, self.world.robot, (220, 90, 35))
        image = Image()
        image.header.stamp = stamp
        image.header.frame_id = 'camera_link'
        image.height = height
        image.width = width
        image.encoding = 'bgr8'
        image.is_bigendian = 0
        image.step = width * 3
        image.data = bytes(pixels)
        self._image_pub.publish(image)

    @staticmethod
    def _draw_agent(
        pixels: bytearray,
        width: int,
        height: int,
        agent: AgentState,
        color: Tuple[int, int, int],
    ) -> None:
        """Draw a small filled circle in the synthetic top-down image."""
        center_x = int(agent.x / 12.0 * (width - 1))
        center_y = int((8.0 - agent.y) / 8.0 * (height - 1))
        for dy in range(-3, 4):
            for dx in range(-3, 4):
                if dx * dx + dy * dy > 9:
                    continue
                x = center_x + dx
                y = center_y + dy
                if 0 <= x < width and 0 <= y < height:
                    offset = (y * width + x) * 3
                    pixels[offset:offset + 3] = bytes(color)

    @staticmethod
    def _agent_odometry_and_transforms(
        state: AgentState,
        agent: str,
        origin: Tuple[float, float],
        stamp,
    ) -> Tuple[Odometry, Tuple[TransformStamped, TransformStamped]]:
        """Build odometry and map-to-odom-to-base transforms for one agent."""
        odom_frame = f'{agent}/odom'
        base_frame = f'{agent}/base_link'
        odom_x = state.x - origin[0]
        odom_y = state.y - origin[1]
        odom = Odometry()
        odom.header.stamp = stamp
        odom.header.frame_id = odom_frame
        odom.child_frame_id = base_frame
        odom.pose.pose.position.x = odom_x
        odom.pose.pose.position.y = odom_y
        odom.pose.pose.orientation.z = math.sin(state.yaw / 2.0)
        odom.pose.pose.orientation.w = math.cos(state.yaw / 2.0)
        odom.twist.twist.linear.x = state.linear_x
        odom.twist.twist.angular.z = state.angular_z

        map_to_odom = TransformStamped()
        map_to_odom.header.stamp = stamp
        map_to_odom.header.frame_id = 'map'
        map_to_odom.child_frame_id = odom_frame
        map_to_odom.transform.translation.x = origin[0]
        map_to_odom.transform.translation.y = origin[1]
        map_to_odom.transform.rotation.w = 1.0
        odom_to_base = TransformStamped()
        odom_to_base.header.stamp = stamp
        odom_to_base.header.frame_id = odom_frame
        odom_to_base.child_frame_id = base_frame
        odom_to_base.transform.translation.x = odom_x
        odom_to_base.transform.translation.y = odom_y
        odom_to_base.transform.rotation.z = math.sin(state.yaw / 2.0)
        odom_to_base.transform.rotation.w = math.cos(state.yaw / 2.0)
        return odom, (map_to_odom, odom_to_base)

    def _publish_odom_and_tf(self, stamp) -> None:
        """Publish both measured odometry streams and their single TF authority."""
        robot_odom, robot_transforms = self._agent_odometry_and_transforms(
            self.world.robot, 'robot', (3.0, 6.0), stamp
        )
        bus_odom, bus_transforms = self._agent_odometry_and_transforms(
            self.world.bus, 'bus', (1.0, 2.0), stamp
        )
        self._odom_pub.publish(robot_odom)
        self._bus_odom_pub.publish(bus_odom)
        self._tf.sendTransform([*robot_transforms, *bus_transforms])

    def _publish_interlocks(self) -> None:
        """Publish measured door and barrier actuator states."""
        door = Bool()
        door.data = self.world.door_open
        self._door_pub.publish(door)
        barrier = Bool()
        barrier.data = self.world.barrier_open
        self._barrier_pub.publish(barrier)

    def _step(self) -> None:
        """Advance physics and emit each configured topic at its target rate."""
        now = time.monotonic()
        with self._lock:
            bus_command = self._active_command('bus', now)
            robot_command = self._active_command('robot', now)
            next_bus = self.world._pose_after(
                self.world.bus, bus_command[0], bus_command[1], DT_SEC
            )
            next_robot = self.world._pose_after(
                self.world.robot, robot_command[0], robot_command[1], DT_SEC
            )
            if self._path_needs_crossing(self.world.bus, next_bus, BUS_RADIUS):
                if not self._crossing_allows('bus', now):
                    bus_command = (0.0, 0.0)
            if self._path_needs_crossing(self.world.robot, next_robot, ROBOT_RADIUS):
                if not self._crossing_allows('robot', now):
                    robot_command = (0.0, 0.0)
            self.world.step(bus_command, robot_command, DT_SEC)
            self._tick += 1
            stamp = self._stamp()
            tick = self._tick
        self._publish_odom_and_tf(stamp)
        if tick % 2 == 0:
            self._publish_vehicles(stamp)
            self._publish_image(stamp)
            self._publish_interlocks()
        if tick % 4 == 0:
            self._publish_parking(stamp)

    def _reset_scenario(self, request, response):
        """Reset only the declared baseline when safety heartbeat and zero hold."""
        with self._lock:
            now = time.monotonic()
            safety_fresh = (
                self._safety is not None
                and now - self._safety_received <= self.SAFETY_TTL_SEC
                and self._header_is_fresh(
                    self._safety.header, self.SAFETY_TTL_SEC
                )
            )
            crossing_fresh_and_clear = (
                self._crossing is not None
                and now - self._crossing_received <= self.CROSSING_TTL_SEC
                and self._crossing.header.frame_id == 'map'
                and self._header_is_fresh(
                    self._crossing.header, self.CROSSING_TTL_SEC
                )
                and self._crossing.valid
                and not self._crossing.owner_id
                and not self._crossing.pedestrian_present
            )
            zero_measured = (
                self.world.bus.linear_x == 0.0
                and self.world.bus.angular_z == 0.0
                and self.world.robot.linear_x == 0.0
                and self.world.robot.angular_z == 0.0
            )
            allowed = (
                request.scenario_id == 'm2_baseline'
                and safety_fresh
                and self._safety.header.frame_id == 'map'
                and self._safety.reason == 'reset_in_progress'
                and crossing_fresh_and_clear
                and not self._safety.stop_latched
                and zero_measured
            )
            if not allowed:
                response.success = False
                response.run_id = self._run_id
                response.reason = (
                    'reset requires m2_baseline, fresh clear crossing and safety, '
                    'zero motion, and no stop latch'
                )
                return response
            self.world.reset(int(request.seed))
            self._commands = {
                'bus': ((0.0, 0.0), now),
                'robot': ((0.0, 0.0), now),
            }
            self._run_id = str(uuid.uuid4())
            self._tick = 0
            response.success = True
            response.run_id = self._run_id
            response.reason = 'seeded m2_baseline reset complete; command leases flushed'
            return response


def main(args=None) -> None:
    """Run the M2 scenario node until interrupted."""
    rclpy.init(args=args)
    node = ScenarioRunner()
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, rclpy.executors.ExternalShutdownException):
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()
