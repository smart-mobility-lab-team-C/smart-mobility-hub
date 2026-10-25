"""M2 ROS simulator, observation publisher, and independent command adapter."""

from __future__ import annotations

import json
import math
from threading import RLock
import time
from typing import Optional, Tuple
import uuid

from geometry_msgs.msg import TransformStamped, Twist
from nav_msgs.msg import Odometry
from rcl_interfaces.msg import SetParametersResult
import rclpy
from rclpy.callback_groups import MutuallyExclusiveCallbackGroup
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy
from sensor_msgs.msg import Image
from smart_hub_interfaces.msg import (
    CrossingState,
    HubEvent,
    ParkingState,
    QueueState,
    SafetyState,
    SlotObservation,
    SlotObservationArray,
    VehicleState,
    VehicleStateArray,
)
from smart_hub_interfaces.srv import ResetScenario
from std_msgs.msg import Bool, String
from std_srvs.srv import Trigger
from tf2_ros import TransformBroadcaster

from .door_evidence import DoorEvidence
from .geometry import intersects_crossing
from .passengers import PassengerQueue
from .reset_workflow import ResetWorkflow
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


class ScenarioRunner(ResetWorkflow, Node):
    """Run deterministic physics and publish ROS observations at contract rates."""

    SAFETY_TTL_SEC = 0.5
    CROSSING_TTL_SEC = 0.5

    def __init__(self) -> None:
        """Initialize simulator sources, independent adapters and validated runtime settings."""
        super().__init__('scenario_runner')
        self.declare_parameter('seed', 17)
        self.declare_parameter('m3_mode', False)
        self.declare_parameter('m4_mode', False)
        self.declare_parameter('m6_mode', False)
        # Graphs without bus_manager (S1) must not wait for bus reset participants.
        self.declare_parameter('reset_bus', True)
        self.m4_mode = bool(self.get_parameter('m4_mode').value)
        self.declare_parameter('occupied_slots', ['P1'])
        self.declare_parameter('invalid_slots', [''])
        self.declare_parameter('publish_parking', True)
        self.declare_parameter('freeze_parking', False)
        self.declare_parameter('publish_vehicles', True)
        self.declare_parameter('freeze_vehicles', False)
        self.declare_parameter('entry_vehicle_id', '')
        self.declare_parameter('passage_occupied', False)
        self.declare_parameter('publish_entrance', True)
        self.declare_parameter('publish_barrier_status', True)
        self._last_parking = None
        self._frozen_vehicles = None
        self._parking_state = None
        self._parking_received = 0.0
        self.declare_parameter('initial_passengers', 6)
        self.declare_parameter('passenger_arrivals_sec', rclpy.Parameter.Type.DOUBLE_ARRAY)
        self.set_parameters([self.get_parameter_or(
            'passenger_arrivals_sec', rclpy.Parameter(
                'passenger_arrivals_sec', rclpy.Parameter.Type.DOUBLE_ARRAY, []))])
        self.declare_parameter('pedestrian_present', False)
        self.declare_parameter('s1_counting_script', False)
        self.declare_parameter('camera_silent', False)
        self.declare_parameter('camera_frozen', False)
        self.declare_parameter('occluded_passenger_indices', [0])
        self.declare_parameter('occlude_passengers', False)
        self._frozen_image = None
        self.declare_parameter('publish_queue', True)
        self.declare_parameter('publish_bus_odom', True)
        # Test-only fault injection for the S9/T14 robot odometry gap.
        self.declare_parameter('publish_robot_odom', True)
        self.m3_mode = bool(self.get_parameter('m3_mode').value)
        self.s1_script = bool(self.get_parameter('s1_counting_script').value)
        if self.s1_script and not self.m3_mode:
            raise ValueError('S1 counting script requires passenger simulation')
        self._s1_departed = False
        initial = (0 if self.s1_script else int(self.get_parameter('initial_passengers').value))
        arrivals = ([5.0] * 3 + [10.0] * 2 if self.s1_script else
                    self.get_parameter_or('passenger_arrivals_sec', rclpy.Parameter(
                        'passenger_arrivals_sec', rclpy.Parameter.Type.DOUBLE_ARRAY, [])).value)
        self.passengers = PassengerQueue(
            int(self.get_parameter('seed').value),
            initial, arrivals)
        self.goal_id = ''
        self.add_on_set_parameters_callback(self._validate_m3_parameters)
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
        self._door_evidence = DoorEvidence()
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
        if self.m4_mode:
            self._entrance_pub = self.create_publisher(Bool, '/parking/entrance_clear', _qos(1))
            self._entry_pub = self.create_publisher(String, '/parking/entry_vehicle_id', _qos(1))
            self._bay_pub = self.create_publisher(Bool, '/sim/bay_clear', _qos(1))
            self.create_subscription(Bool, '/parking/barrier_heartbeat',
                                     self._barrier_heartbeat, _qos(1))
            self.create_subscription(ParkingState, '/parking/state',
                                     self._on_parking_state, _qos(1, True))
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
            ResetScenario, '/sim/reset_world', self._reset_scenario,
            callback_group=MutuallyExclusiveCallbackGroup(),
        )
        reset_bus = self.m3_mode and bool(self.get_parameter('reset_bus').value)
        self.configure_reset(include_bus=reset_bus,
                             include_m4=self.m4_mode,
                             include_robot=bool(self.get_parameter('m6_mode').value))
        self._queue_pub = (self.create_publisher(QueueState, '/hub/queue', _qos(10))
                           if self.m3_mode else None)
        self._boarding_pub = self.create_publisher(HubEvent, '/hub/events', _qos(100))
        self._run_pub = self.create_publisher(String, '/sim/run_id', _qos(1, True))
        self.create_subscription(String, '/sim/bus_goal_id', self._goal_id, _qos(1))
        self._run_pub.publish(String(data=self._run_id))
        if self.m3_mode:
            self.create_service(Trigger, '/sim/add_passenger', self._add_passenger)
        self._tf = TransformBroadcaster(self)
        # The 20 Hz physics and adapter watchdog must not queue behind subscriptions.
        self._timer = self.create_timer(
            DT_SEC, self._step, callback_group=MutuallyExclusiveCallbackGroup())
        self.get_logger().info(
            f'M2 simulator ready: seed={seed} run_id={self._run_id}'
        )

    def _validate_m3_parameters(self, parameters):
        """Reject malformed dynamic queue settings before reset consumes them."""
        for parameter in parameters:
            if parameter.name == 'initial_passengers' and not 0 <= parameter.value <= 1000:
                return SetParametersResult(successful=False, reason='invalid initial count')
            if parameter.name == 'passenger_arrivals_sec' and any(
                    not math.isfinite(t) or t < 0 for t in parameter.value):
                return SetParametersResult(successful=False, reason='invalid arrival schedule')
            if parameter.name in ('occupied_slots', 'invalid_slots') and not (
                    set(parameter.value) <= {'P1', 'P2', 'P3', ''}):
                return SetParametersResult(successful=False, reason='unknown parking slot')
            if parameter.name in ('m3_mode', 'm4_mode', 's1_counting_script'):
                return SetParametersResult(successful=False,
                                           reason='scenario mode is startup only')
            if parameter.name == 'occluded_passenger_indices' and (
                    any(not isinstance(index, int) or index < 0 or index >= 24
                        for index in parameter.value)):
                return SetParametersResult(successful=False,
                                           reason='invalid occlusion index')
        return SetParametersResult(successful=True)

    def _add_passenger(self, request, response):
        """Inject one labelled synthetic arrival at the current simulation time."""
        identity = f'{self.passengers.seed}-p{self.passengers.next_id:04d}'
        self.passengers.next_id += 1
        self.passengers.waiting.append((identity, self.world.tick_count * DT_SEC))
        response.success, response.message = True, identity
        return response

    def _goal_id(self, message):
        """Associate synthetic boarding with the active bus action only."""
        records = []
        with self._lock:
            if message.data == self.goal_id:
                return
            if self.goal_id:
                records.append(self._capture_door('goal_end', lambda: None))
            self.goal_id = message.data
            if self.goal_id:
                records.append(self._capture_door('goal_start', lambda: None))
        for record in records:
            self._publish_door_evidence(record)

    def _capture_door(self, operation, mutate):
        """Capture a World operation under the caller's existing simulator lock."""
        return self._door_evidence.capture(
            self.world, self._run_id, self.goal_id, operation, mutate)

    def _publish_door_evidence(self, record):
        """Publish evaluator evidence after releasing the simulator lock."""
        if record is None:
            return
        event = HubEvent()
        event.header.stamp = self._stamp()
        event.header.frame_id = 'map'
        event.run_id, event.scenario_id = record['run_id'], 'sim_evaluator'
        event.entity_id, event.event = 'bus', 'DOOR_MEASURED'
        event.correlation_id = record['goal_id']
        event.reason = json.dumps(record, sort_keys=True)
        self._boarding_pub.publish(event)

    def _passenger_tick(self, stamp):
        """Advance synthetic arrivals/boarding without exposing future schedules to control."""
        if not self.m3_mode:
            return
        elapsed = self.world.tick_count * DT_SEC
        if self.s1_script and elapsed >= 15.0 and not self._s1_departed:
            if self.passengers.waiting:
                self.passengers.waiting.pop(0)
            self._s1_departed = True
        safe = (self.world.bus.linear_x == 0 and self.world.bus.angular_z == 0 and
                self.world.door_open)
        for record in self.passengers.tick(elapsed, self.world.door_open, safe, self.goal_id):
            event = HubEvent()
            event.header.stamp = stamp
            event.header.frame_id = 'map'
            event.run_id, event.scenario_id = self._run_id, 'm3_baseline'
            event.entity_id = record['passenger_id']
            event.event = 'PASSENGER_BOARDED'
            event.reason = json.dumps(record, sort_keys=True)
            event.correlation_id = record['goal_id']
            self._boarding_pub.publish(event)
        if self._tick % 4 == 0 and self.get_parameter('publish_queue').value:
            queue = QueueState()
            queue.header.stamp = stamp
            queue.header.frame_id = 'map'
            queue.zone_id = 'Q'
            queue.count = len(self.passengers.waiting)
            queue.confidence, queue.valid = 1.0, True
            queue.crossing_occupied = self._pedestrian_visible()
            self._queue_pub.publish(queue)

    def _pedestrian_visible(self):
        """Return physical crossing occupancy from the scripted or manual fixture."""
        elapsed = self.world.tick_count * DT_SEC
        return (bool(self.get_parameter('pedestrian_present').value) or
                self.s1_script and 20.0 <= elapsed < 24.0)

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
            if self._older_than(message, self._safety):
                return
            self._safety = message
            self._safety_received = time.monotonic()

    def _crossing_state(self, message: CrossingState) -> None:
        """Track the crossing owner and validity with local receipt age."""
        with self._lock:
            if self._older_than(message, self._crossing):
                return
            self._crossing = message
            self._crossing_received = time.monotonic()

    @staticmethod
    def _older_than(message, current) -> bool:
        """Ignore a duplicate delivery that predates the stored sample."""
        if current is None:
            return False
        stamp, held = message.header.stamp, current.header.stamp
        return (stamp.sec, stamp.nanosec) < (held.sec, held.nanosec)

    def _door_request(self, message: Bool) -> None:
        """Apply the bus door request; measured opening remains interlocked in World."""
        with self._lock:
            record = self._capture_door(
                'request', lambda: setattr(self.world, 'door_request', bool(message.data)))
        self._publish_door_evidence(record)

    def _on_parking_state(self, message):
        """Receive owner-bearing state independently from unstamped barrier commands."""
        self._parking_state = message
        self._parking_received = time.monotonic()

    def _barrier_request(self, message: Bool) -> None:
        """Record a short actuator lease; opening still needs independent interlocks."""
        with self._lock:
            self.world.barrier_request = bool(message.data)

    def _barrier_heartbeat(self, message):
        """Renew the actuator lease only when on-change intent also requests opening."""
        with self._lock:
            self.world.barrier.command(bool(message.data and self.world.barrier_request),
                                       time.monotonic())

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
        if self.m4_mode and self.get_parameter('freeze_vehicles').value:
            if self._frozen_vehicles is None:
                self._frozen_vehicles = observations
            observations = self._frozen_vehicles
        else:
            self._frozen_vehicles = None
        if not self.m4_mode or self.get_parameter('publish_vehicles').value:
            self._vehicles_pub.publish(observations)
        self._truth_pub.publish(truth)

    def _publish_truth(self, stamp) -> None:
        """Publish noise-free evaluator ground truth without perception records."""
        truth = VehicleStateArray()
        truth.header.stamp = stamp
        truth.header.frame_id = 'map'
        for vehicle_id, kind, state in self.world.ground_truth():
            truth.vehicles.append(
                self._vehicle_record(vehicle_id, kind, state, noisy=False)
            )
        self._truth_pub.publish(truth)

    def _publish_parking(self, stamp) -> None:
        """Publish synthetic slot observations using the observation-only RNG."""
        if self.m4_mode and not self.get_parameter('publish_parking').value:
            return
        if (self.m4_mode and self.get_parameter('freeze_parking').value
                and self._last_parking is not None):
            self._parking_pub.publish(self._last_parking)
            return
        message = SlotObservationArray()
        message.header.stamp = stamp
        message.header.frame_id = 'map'
        for slot_id in ('P1', 'P2', 'P3'):
            observation = SlotObservation()
            observation.slot_id = slot_id
            observation.occupied = (self.m4_mode and
                                    slot_id in self.get_parameter('occupied_slots').value)
            observation.confidence = max(
                0.0, min(1.0, self.world.observation_rng.gauss(0.97, 0.01))
            )
            observation.valid = not (self.m4_mode and
                                     slot_id in self.get_parameter('invalid_slots').value)
            message.slots.append(observation)
        self._last_parking = message
        self._parking_pub.publish(message)

    def _publish_image(self, stamp) -> None:
        """Render visible pedestrians; preserve acquisition data under freeze faults."""
        if self.get_parameter('camera_silent').value:
            return
        elapsed = self.world.tick_count * DT_SEC
        frozen = self.get_parameter('camera_frozen').value or (
            self.s1_script and elapsed >= 30.0)
        if frozen and self._frozen_image is not None:
            self._image_pub.publish(self._frozen_image)
            return
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
        hidden = (set(self.get_parameter('occluded_passenger_indices').value)
                  if self.get_parameter('occlude_passengers').value else set())
        if self.s1_script and 12.0 <= elapsed < 12.3:
            hidden.add(0)
        for index, _passenger in enumerate(self.passengers.waiting[:24]):
            if index in hidden:
                continue
            x = 2.25 + 0.58 * (index % 6)
            y = 5.4 + 0.42 * (index // 6)
            self._draw_agent(pixels, width, height, AgentState(x=x, y=y, yaw=0.0),
                             (220, 40, 220))
        if self._pedestrian_visible():
            self._draw_agent(pixels, width, height, AgentState(x=5.0, y=3.0, yaw=0.0),
                             (220, 40, 220))
        image = Image()
        image.header.stamp = stamp
        image.header.frame_id = 'camera_link'
        image.height = height
        image.width = width
        image.encoding = 'bgr8'
        image.is_bigendian = 0
        image.step = width * 3
        image.data = bytes(pixels)
        self._frozen_image = image
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
        if self.get_parameter('publish_robot_odom').value:
            self._odom_pub.publish(robot_odom)
        if self.get_parameter('publish_bus_odom').value:
            self._bus_odom_pub.publish(bus_odom)
        self._tf.sendTransform([*robot_transforms, *bus_transforms])

    def _publish_interlocks(self) -> None:
        """Publish measured door and barrier actuator states."""
        door = Bool()
        door.data = self.world.door_open
        self._door_pub.publish(door)
        if self.m4_mode:
            now = time.monotonic()
            clear = not self.get_parameter('passage_occupied').value
            identity = self.get_parameter('entry_vehicle_id').value
            if self.get_parameter('publish_entrance').value:
                self._entrance_pub.publish(Bool(data=clear))
                self._entry_pub.publish(String(data=identity))
            self._bay_pub.publish(Bool(data=math.hypot(
                self.world.robot.x - 8, self.world.robot.y - 4) > .8))
            state = self._parking_state
            live = bool(state and self._header_is_fresh(state.header, 1.0)
                        and now - self._parking_received <= 1.0)
            ros_now = self.get_clock().now().nanoseconds * 1e-9
            owner = live and any(
                slot.vehicle_id == identity and identity and slot.reservation_id
                and slot.state in ('RESERVED', 'OCCUPIED')
                and slot.expires_at.sec + slot.expires_at.nanosec * 1e-9 > ros_now
                for slot in state.slots)
            safe = bool(self._safety and now - self._safety_received <= .5
                        and self._header_is_fresh(self._safety.header, .5)
                        and not self._safety.stop_latched
                        and self._safety.reason != 'reset_in_progress')
            self.world.barrier.update(now, clear, owner, safe)
        barrier = Bool()
        barrier.data = self.world.barrier_open
        if not self.m4_mode or self.get_parameter('publish_barrier_status').value:
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
            record = self._capture_door(
                'physics', lambda: self.world.step(bus_command, robot_command, DT_SEC))
            self._tick += 1
            stamp = self._stamp()
            tick = self._tick
        self._publish_door_evidence(record)
        self._passenger_tick(stamp)
        self._publish_odom_and_tf(stamp)
        if tick % 2 == 0:
            self._publish_vehicles(stamp)
            self._publish_image(stamp)
            self._publish_interlocks()
        else:
            # Evaluator-only truth at the 20 Hz step rate; observation noise RNG untouched.
            self._publish_truth(stamp)
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
                and not (self.m4_mode and self.get_parameter('passage_occupied').value)
            )
            if not allowed:
                response.success = False
                response.run_id = self._run_id
                response.reason = (
                    'reset requires m2_baseline, fresh clear crossing and safety, '
                    'zero motion, and no stop latch'
                )
                return response
            record = self._capture_door('reset', lambda: self.world.reset(int(request.seed)))
            initial = (0 if self.s1_script else
                       int(self.get_parameter('initial_passengers').value))
            arrivals = ([5.0] * 3 + [10.0] * 2 if self.s1_script else
                        self.get_parameter_or('passenger_arrivals_sec', rclpy.Parameter(
                            'passenger_arrivals_sec', rclpy.Parameter.Type.DOUBLE_ARRAY,
                            [])).value)
            self.passengers = PassengerQueue(int(request.seed), initial, arrivals)
            self._s1_departed = False
            self.goal_id = ''
            self._parking_state = None
            self._parking_received = 0.0
            self._last_parking = self._frozen_vehicles = None
            self._frozen_image = None
            self._commands = {
                'bus': ((0.0, 0.0), now),
                'robot': ((0.0, 0.0), now),
            }
            self._run_id = str(uuid.uuid4())
            self._tick = 0
            response.success = True
            response.run_id = self._run_id
            response.reason = 'seeded m2_baseline reset complete; command leases flushed'
        self._publish_door_evidence(record)
        self._run_pub.publish(String(data=response.run_id))
        return response


def main(args=None) -> None:
    """Run the M2 scenario node until interrupted."""
    rclpy.init(args=args)
    node = ScenarioRunner()
    executor = MultiThreadedExecutor(num_threads=4)
    executor.add_node(node)
    try:
        executor.spin()
    except (KeyboardInterrupt, rclpy.executors.ExternalShutdownException):
        pass
    finally:
        executor.shutdown()
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()
