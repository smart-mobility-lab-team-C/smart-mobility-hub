"""Independent 20 Hz final command gate for bus and robot motion."""

import math
import time

from geometry_msgs.msg import Twist, TwistStamped
from nav_msgs.msg import Odometry
import rclpy
from rclpy.node import Node
from rclpy.qos import (
    DurabilityPolicy,
    HistoryPolicy,
    QoSProfile,
    ReliabilityPolicy,
)
from smart_hub_interfaces.msg import (
    CrossingState,
    HubEvent,
    QueueState,
    SafetyState,
    VehicleStateArray,
)
from smart_hub_interfaces.srv import ClearSafetyStop, ResetScenario
from smart_hub_sim.geometry import (
    intersects_crossing,
    swept_clear,
    swept_segments_clear,
)
from std_msgs.msg import Bool

from .validation import (
    finite_vehicle,
    observation_fresh,
    stamp_seconds,
    validate_candidate,
    zero_twist,
)


def _qos(depth, transient=False):
    """Build reliable volatile or reliable transient-local QoS."""
    return QoSProfile(
        history=HistoryPolicy.KEEP_LAST, depth=depth,
        reliability=ReliabilityPolicy.RELIABLE,
        durability=(DurabilityPolicy.TRANSIENT_LOCAL if transient
                    else DurabilityPolicy.VOLATILE))


class SafetySupervisor(Node):
    """Apply freshness, interlock, geometry and latch checks to candidates."""

    def __init__(self):
        """Create the final command gate, watchdog inputs and recovery services."""
        super().__init__('safety_supervisor')
        self.declare_parameter('queue_confidence_min', 0.5)
        self.declare_parameter('command_timeout_sec', 0.5)
        self.declare_parameter('robot_speed_limit', 0.25)
        self.declare_parameter('bus_speed_limit', 0.4)
        self.declare_parameter('angular_speed_limit', 1.0)
        self.declare_parameter('future_tolerance_sec', 0.0)
        self._queue_confidence_min = self._validated_parameter(
            'queue_confidence_min', 0.0, 1.0)
        self._command_timeout_sec = self._validated_parameter(
            'command_timeout_sec', 0.0, 0.5, lower_inclusive=False)
        self._robot_speed_limit = self._validated_parameter(
            'robot_speed_limit', 0.0, 0.25, lower_inclusive=False)
        self._bus_speed_limit = self._validated_parameter(
            'bus_speed_limit', 0.0, 0.4, lower_inclusive=False)
        self._angular_speed_limit = self._validated_parameter(
            'angular_speed_limit', 0.0, 1.0, lower_inclusive=False)
        self._future_tolerance_sec = self._validated_parameter(
            'future_tolerance_sec', 0.0, 0.0)

        self._data = {}
        self._candidate = {'robot': None, 'bus': None}
        self._candidate_stamp_floor = None
        self._reset_hold = False
        self._latched = False
        self._latch_reason = ''
        self._last_state = None
        self._tick_count = 0

        self._robot_pub = self.create_publisher(Twist, '/robot/cmd_vel', _qos(1))
        self._bus_pub = self.create_publisher(Twist, '/bus/cmd_vel', _qos(1))
        self._safety_pub = self.create_publisher(SafetyState, '/hub/safety',
                                                 _qos(1, transient=True))
        self._event_pub = self.create_publisher(HubEvent, '/hub/events', _qos(100))

        self.create_subscription(
            TwistStamped, '/robot/cmd_vel_candidate',
            lambda msg: self._candidate_cb('robot', msg), _qos(1))
        self.create_subscription(
            TwistStamped, '/bus/cmd_vel_candidate',
            lambda msg: self._candidate_cb('bus', msg), _qos(1))
        self.create_subscription(VehicleStateArray, '/hub/vehicles',
                                 lambda msg: self._record('vehicles', msg), _qos(10))
        self.create_subscription(Odometry, '/robot/odom',
                                 lambda msg: self._record('odom', msg), _qos(10))
        self.create_subscription(Odometry, '/bus/odom',
                                 lambda msg: self._record('bus_odom', msg),
                                 _qos(10))
        self.create_subscription(QueueState, '/hub/queue',
                                 lambda msg: self._record('queue', msg), _qos(10))
        self.create_subscription(CrossingState, '/crossing/state',
                                 lambda msg: self._record('crossing', msg),
                                 _qos(1, transient=True))
        self.create_subscription(Bool, '/bus/door_open',
                                 lambda msg: self._record('door', msg), _qos(1))
        self.create_subscription(Bool, '/hub/estop',
                                 self._estop_cb, _qos(1, transient=True))

        self.create_service(ClearSafetyStop, '/safety/clear_stop', self._clear_cb)
        self.create_service(ResetScenario, '/safety/reset_state', self._reset_cb)
        self.create_service(ResetScenario, '/safety/finish_reset',
                            self._finish_reset_cb)
        self.create_timer(0.05, self._tick)

    def _now_ros(self):
        """Return this node's ROS clock in seconds."""
        return self.get_clock().now().nanoseconds * 1.0e-9

    def _validated_parameter(self, name, minimum, maximum,
                             lower_inclusive=True):
        """Read and range-check one exposed numeric safety parameter."""
        value = float(self.get_parameter(name).value)
        lower_ok = value >= minimum if lower_inclusive else value > minimum
        if not math.isfinite(value) or not lower_ok or value > maximum:
            left = '[' if lower_inclusive else '('
            raise ValueError(f'{name} must be {left}{minimum}, {maximum}]')
        return value

    def _record(self, key, message):
        """Store a short callback snapshot with local monotonic receipt time."""
        self._data[key] = (message, time.monotonic())

    def _candidate_cb(self, agent, message):
        """Replace one candidate and remember when it arrived locally."""
        if self._reset_hold:
            return
        if self._candidate_stamp_floor is not None:
            try:
                if stamp_seconds(message.header.stamp) <= self._candidate_stamp_floor:
                    return
            except (AttributeError, TypeError, ValueError, OverflowError):
                pass
        self._candidate[agent] = (message, time.monotonic())

    def _estop_cb(self, message):
        """Record estop and latch immediately on a fresh asserted message."""
        self._record('estop', message)
        if message.data:
            self._set_latch('estop_asserted')

    def _fresh_record(self, key, limit, stamped=True):
        """Return fresh data or a stable missing/stale reason code."""
        record = self._data.get(key)
        if record is None:
            return None, key + '_missing'
        message, received = record
        if time.monotonic() - received > limit:
            return None, key + '_stale'
        if stamped and not observation_fresh(
                message.header.stamp, received, self._now_ros(),
                time.monotonic(), limit, limit, self._future_tolerance_sec):
            return None, key + '_stale'
        return message, ''

    def _critical(self):
        """Validate all shared safety inputs and return reason plus samples."""
        vehicles, reason = self._fresh_record('vehicles', 1.0)
        if reason:
            return reason, None
        if vehicles.header.frame_id != 'map':
            return 'vehicles_bad_frame', None
        by_id = {}
        for item in vehicles.vehicles:
            if (not item.vehicle_id or item.vehicle_id in by_id or
                    item.kind not in ('robot', 'bus', 'car') or
                    not finite_vehicle(item)):
                return 'vehicles_invalid', None
            by_id[item.vehicle_id] = item
        if set(by_id) != {'robot', 'bus'}:
            return 'vehicles_unsupported_in_m2', None
        if any(agent not in by_id or by_id[agent].kind != agent
               for agent in ('robot', 'bus')):
            return 'vehicles_invalid', None
        for agent, radius in (('robot', 0.2), ('bus', 0.3)):
            pose = by_id[agent].pose
            position = (float(pose.x), float(pose.y))
            if not swept_clear(position, position, radius, (), ()):
                return 'swept_hazard', None
        robot_pose, bus_pose = by_id['robot'].pose, by_id['bus'].pose
        if not swept_segments_clear(
                (float(robot_pose.x), float(robot_pose.y)),
                (float(robot_pose.x), float(robot_pose.y)), 0.2,
                (float(bus_pose.x), float(bus_pose.y)),
                (float(bus_pose.x), float(bus_pose.y)), 0.3, clearance=0.2):
            return 'swept_hazard', None

        odom, reason = self._fresh_record('odom', 1.0)
        if reason:
            return reason, None
        if (odom.header.frame_id != 'robot/odom' or
                odom.child_frame_id != 'robot/base_link'):
            return 'odom_bad_frame', None
        orientation = odom.pose.pose.orientation
        linear = odom.twist.twist.linear
        angular = odom.twist.twist.angular
        odom_values = (
            odom.pose.pose.position.x, odom.pose.pose.position.y, odom.pose.pose.position.z,
            orientation.x, orientation.y, orientation.z, orientation.w,
            linear.x, linear.y, linear.z, angular.x, angular.y, angular.z)
        if not all(math.isfinite(float(value)) for value in odom_values):
            return 'odom_nonfinite', None
        norm = math.hypot(orientation.x, orientation.y, orientation.z, orientation.w)
        if not math.isclose(norm, 1.0, rel_tol=1e-3, abs_tol=1e-3):
            return 'odom_invalid_quaternion', None

        bus_odom, reason = self._fresh_record('bus_odom', 1.0)
        if reason:
            return reason, None
        if (bus_odom.header.frame_id != 'bus/odom' or
                bus_odom.child_frame_id != 'bus/base_link'):
            return 'bus_odom_bad_frame', None
        bus_orientation = bus_odom.pose.pose.orientation
        bus_linear = bus_odom.twist.twist.linear
        bus_angular = bus_odom.twist.twist.angular
        bus_odom_values = (
            bus_odom.pose.pose.position.x,
            bus_odom.pose.pose.position.y,
            bus_odom.pose.pose.position.z,
            bus_orientation.x, bus_orientation.y,
            bus_orientation.z, bus_orientation.w,
            bus_linear.x, bus_linear.y, bus_linear.z,
            bus_angular.x, bus_angular.y, bus_angular.z)
        if not all(math.isfinite(float(value)) for value in bus_odom_values):
            return 'bus_odom_nonfinite', None
        quaternion_norm = math.hypot(
            bus_orientation.x, bus_orientation.y, bus_orientation.z, bus_orientation.w)
        if not math.isclose(quaternion_norm, 1.0, rel_tol=1e-3, abs_tol=1e-3):
            return 'bus_odom_invalid_quaternion', None

        queue, reason = self._fresh_record('queue', 1.0)
        if reason:
            return reason, None
        if queue.header.frame_id != 'map' or queue.zone_id != 'Q':
            return 'queue_bad_frame', None
        if (not queue.valid or not math.isfinite(float(queue.confidence)) or
                not 0.0 <= queue.confidence <= 1.0 or
                queue.confidence < self._queue_confidence_min):
            return 'queue_unknown', None

        crossing, reason = self._fresh_record('crossing', 0.5)
        if reason:
            return reason, None
        if crossing.header.frame_id != 'map':
            return 'crossing_bad_frame', None
        if crossing.state not in ('UNKNOWN', 'CLEAR', 'OCCUPIED', 'OWNED',
                                  'HOLD'):
            return 'crossing_bad_state', None
        if not crossing.valid or crossing.state == 'UNKNOWN':
            return 'crossing_unknown', None
        if crossing.pedestrian_present or queue.crossing_occupied:
            return 'crossing_occupied', None

        door, reason = self._fresh_record('door', 0.5, stamped=False)
        if reason:
            return reason, None
        estop, reason = self._fresh_record('estop', 0.5, stamped=False)
        if reason:
            return reason, None
        if estop.data:
            return 'estop_asserted', None

        return '', (by_id, odom, bus_odom, crossing, bool(door.data))

    def _crossing_clear(self, agent, start, end, radius, crossing):
        """Require ownership before approaching C within the 0.2 m safety margin."""
        x0, y0 = start
        x1, y1 = end
        dx, dy = x1 - x0, y1 - y0
        mid = (x0 + dx * 0.5, y0 + dy * 0.5)
        if not any(intersects_crossing(x, y, radius + 0.2)
                   for x, y in (start, mid, end)):
            return True
        return (crossing.state == 'OWNED' and crossing.owner_id == agent and
                bool(crossing.token) and not crossing.pedestrian_present)

    @staticmethod
    def _project(state, twist):
        """Project one planar Twist for the configured 0.05 s safety horizon."""
        x, y, yaw = (float(state.pose.x), float(state.pose.y),
                     float(state.pose.theta))
        linear = float(twist.linear.x)
        angular = float(twist.angular.z)
        dt = 0.05
        if abs(angular) < 1.0e-9:
            return (x + linear * math.cos(yaw) * dt,
                    y + linear * math.sin(yaw) * dt)
        next_yaw = yaw + angular * dt
        return (x + linear / angular * (math.sin(next_yaw) - math.sin(yaw)),
                y - linear / angular * (math.cos(next_yaw) - math.cos(yaw)))

    def _predict(self, agent, candidate, vehicles, crossing):
        """Check candidate freshness, limits, swept footprint and crossing."""
        message, received = candidate
        reason = validate_candidate(
            message, agent, self._now_ros(), received, time.monotonic(),
            max_source_age=self._command_timeout_sec,
            max_receipt_age=self._command_timeout_sec,
            linear_limit=(self._robot_speed_limit if agent == 'robot' else
                          self._bus_speed_limit),
            angular_limit=self._angular_speed_limit,
            future_tolerance=self._future_tolerance_sec)
        if reason:
            return None, reason
        state = vehicles[agent]
        x, y = float(state.pose.x), float(state.pose.y)
        start = (x, y)
        end = self._project(state, message.twist)
        radius = 0.2 if agent == 'robot' else 0.3
        other_id = 'bus' if agent == 'robot' else 'robot'
        other = vehicles[other_id]
        other_radius = 0.3 if other_id == 'bus' else 0.2
        other_start = (float(other.pose.x), float(other.pose.y))
        other_end = other_start
        other_candidate = self._candidate[other_id]
        if other_candidate is not None:
            other_message, other_received = other_candidate
            other_reason = validate_candidate(
                other_message, other_id, self._now_ros(), other_received,
                time.monotonic(),
                max_source_age=self._command_timeout_sec,
                max_receipt_age=self._command_timeout_sec,
                linear_limit=(self._robot_speed_limit if other_id == 'robot'
                              else self._bus_speed_limit),
                angular_limit=self._angular_speed_limit,
                future_tolerance=self._future_tolerance_sec)
            if other_reason is None:
                other_end = self._project(other, other_message.twist)
        other_midpoint = ((other_start[0] + other_end[0]) * 0.5,
                          (other_start[1] + other_end[1]) * 0.5)
        other_point = (*other_midpoint, other_radius)
        if not swept_clear((x, y), end, radius, (), (other_point,), clearance=0.2):
            return None, 'swept_hazard'
        if not swept_segments_clear(start, end, radius, other_start, other_end,
                                    other_radius, clearance=0.2):
            return None, 'swept_hazard'
        if not self._crossing_clear(agent, (x, y), end, radius, crossing):
            return None, 'crossing_not_owned'
        return message.twist, ''

    def _set_latch(self, reason):
        """Latch a protective hazard and discard both pending candidates."""
        changed = not self._latched or self._latch_reason != reason
        self._latched = True
        self._latch_reason = reason
        self._candidate = {'robot': None, 'bus': None}
        if changed:
            self._publish_event('protective_stop', reason)

    def _publish_event(self, event, reason):
        """Publish a transition event with the current ROS timestamp."""
        message = HubEvent()
        message.header.stamp = self.get_clock().now().to_msg()
        message.header.frame_id = 'map'
        message.entity_id = 'safety_supervisor'
        message.event = event
        message.reason = reason
        self._event_pub.publish(message)

    def _tick(self):
        """Run one bounded watchdog and geometry decision cycle."""
        self._tick_count += 1
        reason, critical = self._critical()
        commands = {'robot': None, 'bus': None}
        if reason in ('crossing_occupied', 'swept_hazard'):
            self._set_latch(reason)
        elif reason == '' and critical and not self._reset_hold:
            vehicles, _, _, crossing, door_open = critical
            for agent in ('robot', 'bus'):
                candidate = self._candidate[agent]
                if candidate is None:
                    continue
                command, agent_reason = self._predict(
                    agent, candidate, vehicles, crossing)
                if agent_reason == 'swept_hazard':
                    self._set_latch(agent_reason)
                elif agent_reason:
                    reason = agent_reason
                elif agent == 'bus' and door_open:
                    reason = 'bus_door_open'
                else:
                    commands[agent] = command

        if self._latched or reason and reason not in (
                'candidate_stale', 'candidate_bad_frame', 'candidate_nonfinite',
                'candidate_unsupported_component', 'candidate_speed_limit',
                'candidate_angular_limit', 'crossing_not_owned', 'bus_door_open'):
            commands = {'robot': None, 'bus': None}
        self._robot_pub.publish(commands['robot'] or Twist())
        self._bus_pub.publish(commands['bus'] or Twist())

        motion = commands['robot'] is not None or commands['bus'] is not None
        # The reset hold already forces zero output, so report it ahead of input reasons.
        reported_reason = (self._latch_reason if self._latched else
                           'reset_in_progress' if self._reset_hold else
                           reason or 'clear')
        state_signature = (self._latched, motion, reported_reason)
        if self._tick_count % 2 == 0:
            self._publish_state(motion, reported_reason)
        if state_signature != self._last_state:
            if self._last_state is not None:
                self._publish_event('safety_state_changed', reported_reason)
            self._last_state = state_signature

    def _publish_state(self, motion, reason):
        """Publish one SafetyState sample with the current ROS timestamp."""
        state = SafetyState()
        state.header.stamp = self.get_clock().now().to_msg()
        state.header.frame_id = 'map'
        state.stop_latched = self._latched
        state.motion_permitted = motion and not self._latched
        state.reason = reason
        self._safety_pub.publish(state)

    def _safe_for_recovery(self):
        """Require fresh affirmative inputs and exact measured zero motion."""
        reason, critical = self._critical()
        if reason:
            return reason
        vehicles, odom, bus_odom, _, door_open = critical
        if door_open:
            return 'bus_door_open'
        if not zero_twist(odom.twist.twist):
            return 'robot_not_stopped'
        if not zero_twist(bus_odom.twist.twist):
            return 'bus_not_stopped'
        if any(float(vehicles[name].speed_mps) != 0.0
               for name in ('robot', 'bus')):
            return 'vehicles_not_stopped'
        return ''

    def _clear_cb(self, request, response):
        """Clear a stop only after explicit acknowledgement and safe feedback."""
        if not request.operator_id.strip() or not request.acknowledgement.strip():
            response.success = False
            response.reason = 'operator_acknowledgement_required'
            return response
        if not self._latched:
            response.success = False
            response.reason = 'no_active_latch'
            return response
        reason = self._safe_for_recovery()
        if reason:
            response.success = False
            response.reason = reason
            return response
        self._latched = False
        self._latch_reason = ''
        self._candidate = {'robot': None, 'bus': None}
        self._candidate_stamp_floor = self._now_ros()
        response.success = True
        response.reason = 'cleared_waiting_for_new_candidates'
        self._publish_event('protective_stop_cleared', response.reason)
        return response

    def _reset_cb(self, request, response):
        """Acknowledge a scenario reset only in an already safe, unlatched state."""
        if request.scenario_id != 'm2_baseline':
            response.success = False
            response.run_id = ''
            response.reason = 'unsupported_scenario'
            return response
        if self._latched:
            response.success = False
            response.run_id = ''
            response.reason = 'active_safety_latch'
            return response
        reason = self._safe_for_recovery()
        response.success = not bool(reason)
        response.run_id = ''
        response.reason = reason or 'safe_state_acknowledged'
        if response.success:
            self._candidate = {'robot': None, 'bus': None}
            self._reset_hold = True
            self._robot_pub.publish(Twist())
            self._bus_pub.publish(Twist())
            self._publish_state(False, 'reset_in_progress')
        return response

    def _finish_reset_cb(self, request, response):
        """Release the reset hold after all peers have acknowledged reset."""
        if request.scenario_id != 'm2_baseline':
            response.success = False
            response.run_id = ''
            response.reason = 'unsupported_scenario'
            return response
        if not self._reset_hold:
            response.success = False
            response.run_id = ''
            response.reason = 'reset_not_in_progress'
            return response
        if self._latched:
            response.success = False
            response.run_id = ''
            response.reason = 'active_safety_latch'
            return response
        reason = self._safe_for_recovery()
        response.success = not bool(reason)
        response.run_id = ''
        response.reason = reason or 'reset_complete_waiting_for_new_candidates'
        if response.success:
            self._candidate = {'robot': None, 'bus': None}
            self._candidate_stamp_floor = self._now_ros()
            self._reset_hold = False
        return response


def main(args=None):
    """Run the safety supervisor with a single-threaded executor."""
    rclpy.init(args=args)
    node = SafetySupervisor()
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, rclpy.executors.ExternalShutdownException):
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
