"""Cancellable M6 robot navigation and passenger escort behind the independent supervisor."""

from collections import deque
import json
import math
from threading import RLock, Thread
import time

from geometry_msgs.msg import Twist, TwistStamped
from nav_msgs.msg import Odometry
from rcl_interfaces.msg import ParameterDescriptor
import rclpy
from rclpy.action import ActionServer, CancelResponse, GoalResponse
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import MultiThreadedExecutor, SingleThreadedExecutor
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile
from rclpy.task import Future
from smart_hub_interfaces.action import EscortPassenger, NavigateTo
from smart_hub_interfaces.msg import (
    CrossingState,
    EdgeStateArray,
    HubEvent,
    SafetyState,
    VehicleStateArray,
)
from smart_hub_interfaces.srv import ComputeRoute, RequestCrossing, ResetScenario
from smart_hub_sim.geometry import CROSSING, intersects_crossing, segment_distance
from std_msgs.msg import String
from std_srvs.srv import Trigger
from tf2_ros import Buffer, TransformException, TransformListener

from .bus import route_needs_crossing, route_waypoints, synchronized, wrap
from .routing import fresh, load_map, shortest_path, valid_edges

ROBOT_ODOM_FRESHNESS_SEC = 1.0
ROBOT_CONTROL_PERIOD_SEC = 0.05
# Robot radius 0.2 m plus 0.2 m clearance plus the bus formula's 0.06 m pose margin.
ROBOT_CROSSING_BASE_MARGIN_M = 0.46
MOTION_SAFETY_REASONS = ('clear', 'candidate_stale', 'crossing_not_owned', 'bus_door_open')
REQUEST_ID_MEMORY = 256


def crossing_guard_radius(speed_limit):
    """Cover one fresh-odometry window and one control step before entering C."""
    return ROBOT_CROSSING_BASE_MARGIN_M + speed_limit * (
        ROBOT_ODOM_FRESHNESS_SEC + ROBOT_CONTROL_PERIOD_SEC
    )


def crossing_exit_clear(pose, speed_limit):
    """Every robot route leaves C eastbound (Cs-J or Cn-B); release only past the guard."""
    return pose[0] > CROSSING[1] and not intersects_crossing(
        pose[0], pose[1], crossing_guard_radius(speed_limit)
    )


def axis_heading(pose, target):
    """Head along the dominant axis of an axis-aligned road segment."""
    # Choosing by the larger offset avoids copysign(pi/2, 0.0) turning north when the
    # final micrometres of a horizontal approach fall below a fixed axis tolerance.
    dx, dy = target[0] - pose[0], target[1] - pose[1]
    if abs(dx) >= abs(dy):
        return 0.0 if dx >= 0 else math.pi
    return math.copysign(math.pi / 2, dy)


def route_cost(config, observations, nodes, agent='robot'):
    """Sum A section 13.2 edge costs (no crossing wait); None if any edge is unusable."""
    cap = {'bus': 0.4, 'robot': 0.25, 'car': 0.35}[agent]
    total = 0.0
    for a, b in zip(nodes, nodes[1:]):
        state = observations.get('-'.join(sorted((a, b))))
        if state is None or not state.valid or state.blocked:
            return None
        length = math.dist(config['nodes'][a], config['nodes'][b])
        total += length / max(min(state.mean_speed_mps, cap), 0.05) * (
            1 + 2 * state.density_ratio)
    return total


def should_replace(current_cost, new_cost, ratio):
    """Congestion-only replacement needs a route at least `ratio` cheaper."""
    return current_cost is not None and new_cost is not None and \
        new_cost <= (1.0 - ratio) * current_cost


def path_length(points):
    """Sum straight segment lengths in map metres."""
    return sum(math.dist(a, b) for a, b in zip(points, points[1:]))


def mission_progress(travelled, remaining):
    """Fraction of distance done; a detour may lower it because remaining grows."""
    total = travelled + remaining
    return 1.0 if total <= 0.0 else max(0.0, min(1.0, travelled / total))


def route_uses_permitted_edges(config, ids, agent='robot'):
    """Reject routes with unknown nodes or edges the agent may not use."""
    permitted = {e['id'] for e in config['edges'] if agent in e['agents']}
    return bool(ids) and all(n in config['nodes'] for n in ids) and all(
        '-'.join(sorted((a, b))) in permitted for a, b in zip(ids, ids[1:])
    )


class RobotManager(Node):
    """Own one robot mission with locked state, timer control and async transactions."""

    def __init__(self):
        """Declare validated parameters, endpoints and the 20 Hz control timer."""
        super().__init__('robot_manager')
        self.lock = RLock()
        self.results = {}
        limits = {
            'robot_speed_limit': (0.25, 0.25),
            'final_approach_speed': (0.1, 0.25),
            'final_approach_distance': (0.5, 1.0),
            'arrival_tolerance_m': (0.20, 0.20),
            'arrival_hold_sec': (1.0, 1.0),
            'readiness_timeout_sec': (20.0, 20.0),
            'edge_freshness_sec': (1.0, 1.0),
            'service_timeout_sec': (1.0, 1.0),
            'route_backoff_sec': (0.25, 1.0),
            'crossing_backoff_sec': (0.25, 1.0),
            'crossing_backoff_max_sec': (1.0, 1.0),
            'crossing_renew_sec': (0.25, 0.5),
            'crossing_ack_timeout_sec': (0.5, 0.5),
            'replan_improvement_ratio': (0.15, 0.9),
            'replan_cooldown_sec': (2.0, 10.0),
        }
        for name, (value, _) in limits.items():
            self.declare_parameter(name, value, ParameterDescriptor(read_only=True))
        self.p = {name: float(self.get_parameter(name).value) for name in limits}
        for name, value in self.p.items():
            if not math.isfinite(value) or not 0 < value <= limits[name][1]:
                raise ValueError(f'{name} must be finite in (0,{limits[name][1]}]')
        if (
            self.p['final_approach_speed'] > self.p['robot_speed_limit']
            or self.p['crossing_renew_sec'] >= self.p['crossing_ack_timeout_sec']
        ):
            raise ValueError('invalid speed/renewal parameter relationship')
        self.config = load_map()
        self.samples = {}
        self.in_tick = False
        self.desired_command = (0.0, 0.0)
        self.goal = self.done = None
        self.kind = ''
        self.reserved = False
        self.pending_legs = []
        self.accepted_deadline = 0.0
        self.request_ids = deque(maxlen=REQUEST_ID_MEMORY)
        self.reset_hold = False
        self.reset_waiter = self.reset_finish_waiter = None
        self.reset_deadline = self.reset_finish_deadline = 0.0
        self.phase = 'IDLE'
        self.reason = ''
        self.correlation = ''
        self.run_id = ''
        self.clear_mission()
        self.token = ''
        self.pending_crossing = None
        self.crossing_next = 0.0
        self.crossing_backoff = self.p['crossing_backoff_sec']
        self.last_renewed = 0.0
        self.observations = Node(
            'robot_observations', context=self.context,
            start_parameter_services=False, enable_rosout=False)
        self.tf_buffer = Buffer()
        self.tf_listener = TransformListener(self.tf_buffer, self.observations)
        self.group = ReentrantCallbackGroup()
        transient = QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL)
        for key, message, topic, qos in (
            ('odom', Odometry, '/robot/odom', 10),
            ('vehicles', VehicleStateArray, '/hub/vehicles', 10),
            ('safety', SafetyState, '/hub/safety', transient),
            ('crossing', CrossingState, '/crossing/state', transient),
            ('edges', EdgeStateArray, '/traffic/edges', 10),
            ('final', Twist, '/robot/cmd_vel', 1),
        ):
            self.observations.create_subscription(
                message, topic, lambda msg, k=key: self.record(k, msg), qos)
        self.observations.create_subscription(String, '/sim/run_id', self.on_run, transient)
        self.commands = self.create_publisher(TwistStamped, '/robot/cmd_vel_candidate', 1)
        self.events = self.create_publisher(HubEvent, '/hub/events', 100)
        self.route_client = self.create_client(
            ComputeRoute, '/route/compute', callback_group=self.group)
        self.cross_client = self.create_client(
            RequestCrossing, '/crossing/request', callback_group=self.group)
        self.escort_server = ActionServer(
            self, EscortPassenger, '/robot/escort', self.execute,
            goal_callback=self.accept_escort, cancel_callback=self.cancel,
            handle_accepted_callback=self.accepted, callback_group=self.group)
        self.navigate_server = ActionServer(
            self, NavigateTo, '/robot/navigate_to', self.execute,
            goal_callback=self.accept_navigate, cancel_callback=self.cancel,
            handle_accepted_callback=self.accepted, callback_group=self.group)
        self.create_service(Trigger, '/robot/confirm_ready', self.confirm_ready,
                            callback_group=self.group)
        self.create_service(ResetScenario, '/robot/prepare_reset', self.prepare_reset,
                            callback_group=self.group)
        self.create_service(ResetScenario, '/robot/finish_reset', self.finish_reset,
                            callback_group=self.group)
        self.create_timer(ROBOT_CONTROL_PERIOD_SEC, self.tick)
        self.create_timer(0.5, self.publish_feedback)

    def clear_mission(self):
        """Forget per-goal progress; callers hold the state lock."""
        self.legs = []
        self.leg_goal = ''
        self.leg_phase = 'IDLE'
        self.route = []
        self.targets = []
        self.mid_edge_waypoint = False
        self.pending_route = None
        self.route_attempt = 0
        self.route_next = 0.0
        self.future_length = 0.0
        self.travelled = 0.0
        self.last_pose = None
        self.remaining = -1.0
        self.ready = False
        self.ready_since = None
        self.arrived_since = None
        self.last_replan_check = 0.0
        self.stop_reason = ''
        self.stop_started = None
        self.deadline = 0.0

    @synchronized
    def on_run(self, message):
        """Correlate events with the simulator run identifier."""
        self.run_id = message.data

    @synchronized
    def record(self, key, message):
        """Store a sample with its monotonic receipt time; never restamp it."""
        self.samples[key] = (message, time.monotonic())

    def state(self, key, ttl=ROBOT_ODOM_FRESHNESS_SEC):
        """Return a fresh sample; the header-less final command uses receipt age only."""
        sample = self.samples.get(key)
        if key == 'final':
            return sample[0] if sample and time.monotonic() - sample[1] <= ttl else None
        frame = 'robot/odom' if key == 'odom' else 'map'
        return sample[0] if fresh(self, sample, ttl, frame) else None

    def pose(self):
        """Transform fresh odometry into map; reject malformed or stale inputs."""
        odom = self.state('odom')
        if odom is None or odom.child_frame_id != 'robot/base_link':
            return None
        p, q, twist = odom.pose.pose.position, odom.pose.pose.orientation, odom.twist.twist
        values = (p.x, p.y, p.z, q.x, q.y, q.z, q.w, twist.linear.x, twist.linear.y,
                  twist.linear.z, twist.angular.x, twist.angular.y, twist.angular.z)
        if (
            not all(math.isfinite(v) for v in values)
            or abs(sum(v * v for v in (q.x, q.y, q.z, q.w)) - 1) > 1e-3
            or abs(q.x) + abs(q.y) > 1e-6
        ):
            return None
        try:
            transform = self.tf_buffer.lookup_transform('map', 'robot/odom', rclpy.time.Time())
        except TransformException:
            return None
        tr, rot = transform.transform.translation, transform.transform.rotation
        stamp = transform.header.stamp
        age = self.get_clock().now().nanoseconds * 1e-9 - (stamp.sec + stamp.nanosec * 1e-9)
        finite = all(math.isfinite(v) for v in (tr.x, tr.y, rot.z, rot.w))
        if not 0 <= age <= 1.0 or not finite:
            return None
        yaw0 = 2 * math.atan2(rot.z, rot.w)
        return (
            tr.x + p.x * math.cos(yaw0) - p.y * math.sin(yaw0),
            tr.y + p.x * math.sin(yaw0) + p.y * math.cos(yaw0),
            wrap(yaw0 + 2 * math.atan2(q.z, q.w)),
        )

    def zero_measured(self):
        """Require fresh measured zero motion, never an inferred one."""
        odom = self.state('odom')
        if not odom or not self.pose():
            return False
        t = odom.twist.twist
        return all(v == 0.0 for v in (t.linear.x, t.linear.y, t.linear.z,
                                      t.angular.x, t.angular.y, t.angular.z))

    def edge_snapshot(self):
        """Return validated fresh edge states, or an empty map when stale."""
        sample = self.samples.get('edges')
        if not fresh(self, sample, self.p['edge_freshness_sec']):
            return {}
        return valid_edges(sample[0], {e['id'] for e in self.config['edges']})

    def nearest_node(self, pose):
        """Pick the closest map node to a map pose."""
        return min(self.config['nodes'],
                   key=lambda n: math.dist(pose[:2], self.config['nodes'][n]))

    def admissible(self, request_id, nodes, duration):
        """Shared goal validation for both actions; caller holds the lock."""
        safety = self.state('safety', 0.5)
        pose = self.pose()
        if (
            self.reserved
            or self.reset_hold
            or not request_id.strip()
            or request_id in self.request_ids
            or not math.isfinite(duration)
            or duration <= 0
            or any(n not in self.config['nodes'] for n in nodes)
            or safety is None
            or safety.stop_latched
            or safety.reason not in MOTION_SAFETY_REASONS
            or pose is None
        ):
            return None
        observations = self.edge_snapshot()
        length, start = 0.0, self.nearest_node(pose)
        for node in nodes:
            path, _, reason = shortest_path(self.config, observations, start, node, 'robot')
            if not path:
                self.event('GOAL_REJECTED', reason, correlation=request_id)
                return None
            length += path_length([self.config['nodes'][n] for n in path])
            start = node
        return length

    @synchronized
    def accept_navigate(self, request):
        """Validate a NavigateTo goal and reserve the single mission slot."""
        if self.admissible(request.request_id, [request.goal_node],
                           request.max_duration_sec) is None:
            return GoalResponse.REJECT
        self.reserve('navigate', request.request_id, [request.goal_node],
                     request.max_duration_sec)
        return GoalResponse.ACCEPT

    @synchronized
    def accept_escort(self, request):
        """Validate an EscortPassenger goal; pickup and destination must be robot-reachable."""
        if not request.passenger_id.strip() or request.pickup_node == request.destination_node:
            return GoalResponse.REJECT
        if self.admissible(request.request_id, [request.pickup_node, request.destination_node],
                           request.max_duration_sec) is None:
            return GoalResponse.REJECT
        self.reserve('escort', request.request_id,
                     [request.pickup_node, request.destination_node], request.max_duration_sec)
        return GoalResponse.ACCEPT

    def reserve(self, kind, request_id, legs, duration):
        """Record the accepted mission; the deadline starts at acceptance."""
        self.reserved = True
        self.kind = kind
        self.request_ids.append(request_id)
        self.pending_legs = list(legs)
        self.accepted_deadline = time.monotonic() + duration

    @synchronized
    def accepted(self, handle):
        """Start the nonblocking mission once the action server accepts it."""
        legs = self.pending_legs
        self.clear_mission()
        self.goal = handle
        self.done = Future(executor=self.executor)
        self.results[bytes(handle.goal_id.uuid)] = self.done
        self.deadline = self.accepted_deadline
        self.correlation = bytes(handle.goal_id.uuid).hex()
        self.legs = legs
        self.start_leg('TO_PICKUP' if self.kind == 'escort' else 'MOVING')
        handle.execute()

    def start_leg(self, phase):
        """Begin planning toward the next leg goal."""
        self.leg_goal = self.legs.pop(0)
        self.leg_phase = phase
        self.route = self.targets = []
        self.route_attempt = 0
        self.route_next = 0.0
        self.arrived_since = None
        self.future_length = 0.0
        start = self.leg_goal
        for node in self.legs:
            path, _, _ = shortest_path(self.config, self.edge_snapshot(), start, node, 'robot')
            self.future_length += path_length([self.config['nodes'][n] for n in path])
            start = node
        self.set_phase(phase, 'PLANNING:' + self.leg_goal)

    async def execute(self, handle):
        """Await the timer-resolved result while cancel and subscriptions stay runnable."""
        key = bytes(handle.goal_id.uuid)
        with self.lock:
            waiter = self.results[key]
        try:
            return await waiter
        finally:
            with self.lock:
                self.results.pop(key, None)

    @synchronized
    def cancel(self, handle):
        """Accept cancellation promptly; the tick commands zero immediately."""
        if handle is not self.goal or self.stop_reason not in ('', 'CANCELED'):
            return CancelResponse.REJECT
        self.begin_stop('CANCELED')
        return CancelResponse.ACCEPT

    @synchronized
    def confirm_ready(self, request, response):
        """Accept readiness only while waiting at pickup (A section 14.1)."""
        if self.goal and self.kind == 'escort' and self.phase == 'WAIT_READY' \
                and not self.stop_reason and not self.ready:
            self.ready = True
            response.success, response.message = True, 'READY_ACCEPTED'
            self.event('READY_CONFIRMED', '')
        else:
            response.success = False
            response.message = 'NOT_WAITING_FOR_READY:' + self.phase
            self.event('READY_REJECTED', response.message)
        return response

    def event(self, name, reason, correlation=None):
        """Emit a transition or transaction event with action and run correlation."""
        message = HubEvent()
        message.header.stamp = self.get_clock().now().to_msg()
        message.header.frame_id = 'map'
        message.run_id, message.scenario_id = self.run_id, 'm6_baseline'
        message.entity_id = 'robot'
        message.event, message.reason = name, reason
        message.correlation_id = self.correlation if correlation is None else correlation
        self.events.publish(message)

    def set_phase(self, phase, reason=''):
        """Publish changes only, not one event per control tick."""
        if (phase, reason) != (self.phase, self.reason):
            self.phase, self.reason = phase, reason
            self.event(phase, reason)

    def command(self, linear=0.0, angular=0.0):
        """Send base-frame candidates only; the supervisor owns final motion."""
        if self.in_tick:
            self.desired_command = (linear, angular)
            return
        message = TwistStamped()
        message.header.stamp = self.get_clock().now().to_msg()
        message.header.frame_id = 'robot/base_link'
        message.twist.linear.x, message.twist.angular.z = float(linear), float(angular)
        self.commands.publish(message)

    def begin_stop(self, reason):
        """Command zero and drop route work; termination waits for confirmed stop."""
        if not self.stop_reason:
            self.stop_reason = reason
            self.stop_started = time.monotonic()
            self.discard_route()
            self.set_phase('SAFE_STOP', reason)
        self.command()

    def discard_route(self):
        """Detach an outstanding planner request so a late reply cannot revive it."""
        if self.pending_route:
            self.route_client.remove_pending_request(self.pending_route[0])
            self.pending_route = None

    def finish(self, success, reason, canceled=False, pose=None):
        """Populate a result on every terminal path."""
        self.command()
        final_node = self.nearest_node(pose) if pose else ''
        error = math.dist(pose[:2], self.config['nodes'][self.leg_goal]) \
            if pose and self.leg_goal else -1.0
        if self.kind == 'escort':
            result = EscortPassenger.Result(
                success=success, final_node=final_node,
                travelled_distance_m=float(self.travelled), reason=reason)
        else:
            result = NavigateTo.Result(
                success=success, final_node=final_node, final_error_m=float(error),
                reason=reason)
        if success:
            self.goal.succeed()
            self.set_phase('ARRIVED', reason)
        elif canceled:
            self.goal.canceled()
            self.set_phase('CANCELLED', reason)
        else:
            self.goal.abort()
            self.set_phase('FAILED' if reason.startswith(('NO_ROUTE', 'READINESS'))
                           else 'SAFE_STOP', reason)
        self.event('RESULT', json.dumps({
            'success': success, 'reason': reason, 'final_node': final_node,
            'final_error_m': error, 'travelled_m': self.travelled}))
        self.done.set_result(result)
        self.goal = None
        self.reserved = False
        self.discard_route()

    def remaining_distance(self, pose):
        """Distance left on the current route plus planned later legs."""
        if not self.targets:
            return -1.0 if self.leg_goal else 0.0
        return path_length([pose[:2], *self.targets]) + self.future_length

    def route_step(self, now, pose):
        """Request a route with at most two retries and bounded backoff."""
        self.command()
        if self.pending_route:
            future, sent = self.pending_route
            if future.done():
                self.pending_route = None
                try:
                    response = future.result()
                except Exception:
                    response = None
                if response is not None:
                    if not response.success:
                        self.begin_stop(response.reason or 'NO_ROUTE')
                        return
                    ids = list(response.node_ids)
                    if (
                        not ids
                        or ids[-1] != self.leg_goal
                        or len(ids) != len(response.waypoints)
                        or not route_uses_permitted_edges(self.config, ids)
                        or not math.isfinite(response.estimated_cost_sec)
                        or response.estimated_cost_sec < 0
                        or any(
                            not all(math.isfinite(v) for v in (w.x, w.y, w.z))
                            or math.dist((w.x, w.y), self.config['nodes'][n]) > 1e-6
                            for n, w in zip(ids, response.waypoints)
                        )
                    ):
                        self.begin_stop('INVALID_ROUTE')
                        return
                    self.route = ids
                    self.targets, self.mid_edge_waypoint = route_waypoints(
                        self.config, ids, pose)
                    self.event('ROUTE', json.dumps(
                        {'nodes': ids, 'cost_sec': response.estimated_cost_sec}))
                    return
            elif now - sent < self.p['service_timeout_sec']:
                return
            else:
                self.discard_route()
            if self.route_attempt >= 3:
                self.begin_stop('PLANNER_UNAVAILABLE')
            else:
                self.route_next = now + self.p['route_backoff_sec'] * self.route_attempt
            return
        if now < self.route_next:
            return
        node = self.nearest_node(pose)
        on_graph = math.dist(pose[:2], self.config['nodes'][node]) <= 0.05 or any(
            node in edge['nodes'] and 'robot' in edge['agents'] and segment_distance(
                pose[0], pose[1], *self.config['nodes'][edge['nodes'][0]],
                *self.config['nodes'][edge['nodes'][1]]) <= 1e-6
            for edge in self.config['edges'])
        if not on_graph:
            self.begin_stop('OFF_GRAPH_START')
            return
        if not self.route_client.service_is_ready():
            # Transport absence counts as a failed attempt under the same bound.
            self.route_attempt += 1
            if self.route_attempt >= 3:
                self.begin_stop('PLANNER_UNAVAILABLE')
            else:
                self.route_next = now + self.p['service_timeout_sec']
            return
        self.route_attempt += 1
        request = ComputeRoute.Request(start_node=node, goal_node=self.leg_goal,
                                       agent_type='robot')
        self.pending_route = (self.route_client.call_async(request), now)
        self.event('ROUTE_REQUEST', json.dumps(
            {'attempt': self.route_attempt, 'start': node, 'goal': self.leg_goal}))

    def route_valid(self):
        """Check every untraversed route edge against the current fresh snapshot."""
        edges = self.edge_snapshot()
        return all(
            (edge := edges.get('-'.join(sorted((a, b))))) is not None
            and edge.valid and not edge.blocked
            for a, b in zip(self.route, self.route[1:])
        )

    def owns_crossing(self, now):
        """Require a fresh renewed token that the published state confirms."""
        state = self.state('crossing', 0.5)
        return bool(
            self.token
            and now - self.last_renewed <= self.p['crossing_ack_timeout_sec']
            and state and state.valid and state.owner_id == 'robot'
            and state.token == self.token and state.state == 'OWNED')

    def crossing_step(self, now, pose):
        """Run one bounded crossing transaction; never release while inside C."""
        state = self.state('crossing', 0.5)
        inside = intersects_crossing(pose[0], pose[1], 0.45)
        guard = crossing_guard_radius(self.p['robot_speed_limit'])
        if self.pending_crossing:
            future, sent, operation = self.pending_crossing
            if future.done():
                self.pending_crossing = None
                try:
                    response = future.result()
                except Exception:
                    response = None
                if response and response.granted:
                    if operation == 'RELEASE':
                        self.token = ''
                    else:
                        self.token = response.token
                        self.last_renewed = now
                        self.crossing_backoff = self.p['crossing_backoff_sec']
                    self.event('CROSSING_' + operation, response.reason)
                else:
                    self.event('CROSSING_DENIED', operation + ':' + (
                        response.reason if response else 'TRANSPORT_FAILURE'))
                    self.crossing_next = now + self.crossing_backoff
                    self.crossing_backoff = min(
                        self.p['crossing_backoff_max_sec'], 2 * self.crossing_backoff)
            elif now - sent >= (self.p['crossing_ack_timeout_sec'] if self.token else 1.0):
                self.cross_client.remove_pending_request(future)
                self.pending_crossing = None
                self.crossing_next = now + self.crossing_backoff
            else:
                return
        if self.token:
            if (state and state.owner_id != 'robot' and not inside
                    and now - self.last_renewed > self.p['crossing_ack_timeout_sec']):
                self.token = ''
                return
            idle = self.goal is None or self.stop_reason or not route_needs_crossing(
                [pose[:2], *self.targets])
            cleared = crossing_exit_clear(pose, self.p['robot_speed_limit']) or (
                idle and not intersects_crossing(pose[0], pose[1], guard))
            operation = 'RELEASE' if cleared else 'RENEW'
            if operation == 'RENEW' and now - self.last_renewed < self.p['crossing_renew_sec']:
                return
        elif (
            self.goal and not self.stop_reason and self.targets
            and route_needs_crossing([pose[:2], *self.targets])
            and intersects_crossing(pose[0], pose[1], guard + 0.75)
        ):
            operation = 'ACQUIRE'
        else:
            return
        if now < self.crossing_next or not self.cross_client.service_is_ready():
            return
        request = RequestCrossing.Request(
            requester_id='robot', operation=operation,
            token=self.token if operation != 'ACQUIRE' else '')
        self.pending_crossing = (self.cross_client.call_async(request), now, operation)

    @synchronized
    def tick(self):
        """Publish exactly one candidate per control period, zero on every idle path."""
        self.in_tick = True
        self.desired_command = (0.0, 0.0)
        try:
            self.control_tick()
        except Exception as error:
            self.get_logger().error('control failure: ' + repr(error))
            if self.goal:
                self.begin_stop('INTERNAL_ERROR')
        finally:
            self.in_tick = False
            self.command(*self.desired_command)

    def reset_step(self, now):
        """Resolve pending reset acknowledgements from fresh measured state."""
        if self.reset_waiter and not self.reset_waiter.done():
            if self.goal is None and self.zero_measured():
                self.reset_waiter.set_result(True)
            elif now >= self.reset_deadline:
                self.reset_waiter.set_result(False)
        if self.reset_finish_waiter and not self.reset_finish_waiter.done():
            ready = self.reset_finish_ready()
            if ready or now >= self.reset_finish_deadline:
                self.reset_finish_waiter.set_result(ready)

    def fault(self, now, pose):
        """Return the first terminal fault reason, or an empty string."""
        safety = self.state('safety', 0.5)
        vehicles = self.state('vehicles')
        if self.goal.is_cancel_requested:
            return 'CANCELED'
        if now >= self.deadline:
            return 'TIMEOUT'
        if safety is None or safety.stop_latched:
            return 'SAFETY_STOP'
        if pose is None:
            return 'STALE_ODOMETRY'
        if vehicles is None or {v.vehicle_id for v in vehicles.vehicles} != {'bus', 'robot'} \
                or any(not v.valid or v.kind != v.vehicle_id or not all(
                    math.isfinite(x) for x in (v.pose.x, v.pose.y, v.pose.theta, v.speed_mps))
                    for v in vehicles.vehicles):
            return 'INVALID_VEHICLE_OBSERVATION'
        if safety.reason not in MOTION_SAFETY_REASONS + ('reset_in_progress',):
            return 'SAFETY_INPUT_UNKNOWN:' + safety.reason
        return ''

    def control_tick(self):
        """Advance one bounded state-machine step."""
        now = time.monotonic()
        pose = self.pose()
        self.command()
        if pose:
            self.crossing_step(now, pose)
        self.reset_step(now)
        if not self.goal:
            return
        if not self.stop_reason:
            reason = self.fault(now, pose)
            if reason:
                self.begin_stop(reason)
        if self.stop_reason:
            self.command()
            final = self.state('final', 0.5)
            if (
                self.zero_measured()
                and self.samples['odom'][1] > self.stop_started
                and final is not None
                and self.samples['final'][1] > self.stop_started
                and final.linear.x == 0 and final.angular.z == 0
            ):
                if self.stop_reason == 'CANCELED' and not self.goal.is_cancel_requested:
                    return
                self.finish(False, self.stop_reason, canceled=self.goal.is_cancel_requested,
                            pose=pose)
            elif now - self.stop_started >= 2.0:
                self.finish(False, self.stop_reason + ':STOP_UNCONFIRMED', pose=pose)
            return
        if self.last_pose is not None:
            self.travelled += math.dist(self.last_pose[:2], pose[:2])
        self.last_pose = pose
        self.remaining = self.remaining_distance(pose)
        if self.phase == 'WAIT_READY':
            if self.ready:
                self.start_leg('ESCORT')
            elif now - self.ready_since >= self.p['readiness_timeout_sec']:
                self.begin_stop('READINESS_TIMEOUT')
            return
        if not self.targets:
            if math.dist(pose[:2], self.config['nodes'][self.leg_goal]) <= 0.05:
                self.targets = [tuple(self.config['nodes'][self.leg_goal])]
                self.route = [self.leg_goal]
            else:
                self.route_step(now, pose)
                return
        while len(self.route) > 1:
            a, b = (self.config['nodes'][n] for n in self.route[:2])
            if sum((pose[i] - a[i]) * (b[i] - a[i]) for i in (0, 1)) \
                    < math.dist(a, b) ** 2 - 1e-7:
                break
            self.route.pop(0)
        if not self.route_valid():
            # A blocked, unknown or stale edge invalidates the route: stop and replan.
            self.event('REPLAN', 'ROUTE_INVALID_OR_STALE')
            self.route = self.targets = []
            self.route_attempt = 0
            self.set_phase('BLOCKED', 'ROUTE_INVALID_OR_STALE')
            return
        if self.congestion_replan(now, pose):
            return
        target = self.targets[0]
        distance = math.dist(pose[:2], target)
        final = len(self.targets) == 1
        if distance <= (0.05 if final or self.mid_edge_waypoint else 1e-8):
            if not final:
                self.targets.pop(0)
                self.mid_edge_waypoint = False
                return
            self.arrive(now, pose)
            return
        self.arrived_since = None
        desired = axis_heading(pose, target)
        error = wrap(desired - pose[2])
        if abs(error) > 1e-9:
            self.set_phase(self.leg_phase, self.leg_goal)
            self.command(0.0, max(-1.0, min(1.0, 2.0 * error)))
            return
        guard = crossing_guard_radius(self.p['robot_speed_limit'])
        if intersects_crossing(pose[0], pose[1], guard) and route_needs_crossing(
                [pose[:2], *self.targets]) and not self.owns_crossing(now):
            self.set_phase('WAIT_CROSSING', 'CROSSING_UNAVAILABLE')
            return
        self.set_phase(self.leg_phase, self.leg_goal)
        cap = self.p['robot_speed_limit']
        if final and distance <= self.p['final_approach_distance']:
            cap = self.p['final_approach_speed']
        self.command(min(cap, 2.0 * distance))

    def congestion_replan(self, now, pose):
        """Replace a still-valid route at a node, outside C, when markedly cheaper."""
        if now - self.last_replan_check < self.p['replan_cooldown_sec'] or len(self.route) < 2:
            return False
        node = self.route[0]
        if math.dist(pose[:2], self.config['nodes'][node]) > 1e-6 or intersects_crossing(
                pose[0], pose[1], crossing_guard_radius(self.p['robot_speed_limit'])):
            return False
        self.last_replan_check = now
        observations = self.edge_snapshot()
        path, _, _ = shortest_path(self.config, observations, node, self.leg_goal, 'robot',
                                   crossing=True)
        current = route_cost(self.config, observations, self.route)
        new = route_cost(self.config, observations, path) if path else None
        ratio = self.p['replan_improvement_ratio']
        if path == self.route or not should_replace(current, new, ratio):
            return False
        self.event('REPLAN', json.dumps({'reason': 'CONGESTION', 'old_cost': current,
                                         'new_cost': new}))
        self.route = self.targets = []
        self.route_attempt = 0
        return True

    def arrive(self, now, pose):
        """Require tolerance and measured zero held for the configured interval."""
        error = math.dist(pose[:2], self.config['nodes'][self.leg_goal])
        if error > self.p['arrival_tolerance_m'] or not self.zero_measured():
            self.arrived_since = None
            return
        if self.arrived_since is None:
            self.arrived_since = now
            return
        if now - self.arrived_since < self.p['arrival_hold_sec']:
            return
        self.event('LEG_ARRIVED', json.dumps({'node': self.leg_goal, 'error_m': error}))
        if self.legs:
            self.targets = self.route = []
            self.ready = False
            self.ready_since = now
            self.set_phase('WAIT_READY', self.leg_goal)
        else:
            self.finish(True, 'ARRIVED', pose=pose)

    @synchronized
    def publish_feedback(self):
        """Publish action feedback at the 2 Hz contract rate."""
        if not self.goal:
            return
        remaining = max(0.0, self.remaining) if self.remaining >= 0 else -1.0
        progress = mission_progress(self.travelled, remaining) if remaining >= 0 else 0.0
        if self.kind == 'escort':
            feedback = EscortPassenger.Feedback(
                phase=self.phase, progress=float(progress),
                distance_remaining_m=float(remaining))
        else:
            feedback = NavigateTo.Feedback(
                phase=self.phase, progress=float(progress),
                distance_remaining_m=float(remaining))
        self.goal.publish_feedback(feedback)

    async def prepare_reset(self, request, response):
        """Hold new goals, stop any mission and await measured zero."""
        with self.lock:
            if (request.scenario_id != 'm2_baseline' or self.reset_waiter
                    or self.reset_finish_waiter):
                response.reason = 'UNKNOWN_OR_BUSY'
                return response
            self.reset_hold = True
            self.command()
            if self.goal:
                self.begin_stop('SCENARIO_RESET')
            if self.goal is None and self.zero_measured():
                response.success, response.reason = True, 'ROBOT_ZERO'
                return response
            self.reset_deadline = time.monotonic() + 0.6
            waiter = Future(executor=self.executor)
            self.reset_waiter = waiter
        response.success = await waiter
        with self.lock:
            self.reset_waiter = None
            response.reason = 'ROBOT_ZERO' if response.success else 'ROBOT_RESET_UNCONFIRMED'
        return response

    async def finish_reset(self, request, response):
        """Release the administrative hold after a fresh supervisor reset hold."""
        with self.lock:
            if (request.scenario_id != 'm2_baseline' or not self.reset_hold
                    or self.reset_waiter is not None or self.reset_finish_waiter is not None):
                response.reason = 'ROBOT_RESET_UNSAFE_OR_BUSY'
                return response
            if self.reset_finish_ready():
                self.release_reset_hold()
                response.success, response.reason = True, 'ROBOT_RESET'
                return response
            waiter = Future(executor=self.executor)
            self.reset_finish_waiter = waiter
            self.reset_finish_deadline = time.monotonic() + 0.2
        response.success = await waiter
        with self.lock:
            self.reset_finish_waiter = None
            response.reason = 'ROBOT_RESET' if response.success else 'ROBOT_RESET_UNSAFE'
            if response.success:
                self.release_reset_hold()
        return response

    def reset_finish_ready(self):
        """Require no mission, measured zero and the supervisor's reset hold."""
        safety = self.state('safety', 0.5)
        return bool(self.reset_hold and self.goal is None and self.zero_measured()
                    and safety and not safety.stop_latched
                    and safety.reason == 'reset_in_progress')

    def release_reset_hold(self):
        """Clear administrative caches under the caller's lock."""
        self.reset_hold = False
        self.token = ''
        if self.pending_crossing:
            self.cross_client.remove_pending_request(self.pending_crossing[0])
            self.pending_crossing = None
        self.clear_mission()
        self.set_phase('IDLE')


def main(args=None):
    """Use two executor threads plus an observation thread, as A section 7.3 requires."""
    rclpy.init(args=args)
    node = RobotManager()
    executor = MultiThreadedExecutor(num_threads=2)
    executor.add_node(node)
    observations = SingleThreadedExecutor(context=node.context)
    observations.add_node(node.observations)

    def receive_observations():
        try:
            observations.spin()
        except (KeyboardInterrupt, rclpy.executors.ExternalShutdownException):
            pass

    receiver = Thread(target=receive_observations, name='robot-observations')
    receiver.start()
    try:
        executor.spin()
    except (KeyboardInterrupt, rclpy.executors.ExternalShutdownException):
        pass
    finally:
        executor.shutdown()
        observations.shutdown()
        receiver.join(timeout=2.0)
        if rclpy.ok():
            node.command()
        node.destroy_node()
        node.observations.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
