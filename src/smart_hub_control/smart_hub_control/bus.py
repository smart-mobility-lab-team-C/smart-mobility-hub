"""Cancellable M3 docking with asynchronous services and independent safety gates."""

from functools import wraps
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
from smart_hub_interfaces.action import DockBus
from smart_hub_interfaces.msg import (
    BusArrival,
    CrossingState,
    EdgeStateArray,
    HubEvent,
    SafetyState,
    VehicleStateArray,
)
from smart_hub_interfaces.srv import ComputeRoute, RequestCrossing, ResetScenario
from smart_hub_sim.geometry import intersects_crossing, segment_distance
from std_msgs.msg import Bool, String
from tf2_ros import Buffer, TransformException, TransformListener

from .routing import fresh, load_map, shortest_path, valid_edges


def wrap(angle):
    """Normalize planar yaw differences."""
    return math.atan2(math.sin(angle), math.cos(angle))


def route_needs_crossing(points):
    """Conservatively test the remaining axis-aligned route against inflated C."""
    for a, b in zip(points, points[1:]):
        if max(min(a[0], b[0]), 4.2) <= min(max(a[0], b[0]), 5.8) and max(
            min(a[1], b[1]), 0.95
        ) <= min(max(a[1], b[1]), 5.05):
            return True
    return False


def synchronized(callback):
    """Serialize externally scheduled callbacks; never hold this lock across await."""

    @wraps(callback)
    def guarded(self, *args, **kwargs):
        with self.lock:
            return callback(self, *args, **kwargs)

    return guarded


class BusManager(Node):
    """Own one mission with locked shared state and reentrant action/service callbacks."""

    def __init__(self):
        """Create short callbacks, timer-driven control and a coroutine result waiter."""
        super().__init__('bus_manager')
        self.lock = RLock()
        self.results = {}
        defaults = {
            'bus_speed_limit': 0.4,
            'final_approach_speed': 0.1,
            'final_approach_distance': 1.0,
            'eta_smoothing_sec': 1.0,
            'edge_freshness_sec': 1.0,
            'service_timeout_sec': 1.0,
            'route_backoff_sec': 0.25,
            'crossing_backoff_sec': 0.25,
            'crossing_backoff_max_sec': 1.0,
            'crossing_renew_sec': 0.25,
            'crossing_ack_timeout_sec': 0.5,
            'boarding_interval_sec': 8.0,
        }
        for name, value in defaults.items():
            self.declare_parameter(name, value, ParameterDescriptor(read_only=True))
        self.p = {name: float(self.get_parameter(name).value) for name in defaults}
        for name, value in self.p.items():
            if not math.isfinite(value) or not 0 < value <= defaults[name]:
                raise ValueError(f'{name} must be finite in (0,{defaults[name]}]')
        if (
            self.p['boarding_interval_sec'] != 8.0
            or self.p['final_approach_distance'] != 1.0
            or self.p['final_approach_speed'] > self.p['bus_speed_limit']
            or self.p['crossing_renew_sec'] >= self.p['crossing_ack_timeout_sec']
        ):
            raise ValueError('invalid dwell/speed/renewal parameter relationship')
        self.config = load_map()
        self.samples = {}
        self.in_tick = False
        self.desired_command = (0.0, 0.0)
        self.last_door_request = None
        self.goal = self.done = None
        self.reserved = False
        self.reset_hold = False
        self.reset_waiter = None
        self.reset_finish_waiter = None
        self.reset_finish_deadline = 0.0
        self.reset_deadline = 0.0
        self.reset_started = 0.0
        self.reset_observation = None
        self.phase = 'IDLE'
        self.reason = ''
        self.correlation = ''
        self.run_id = ''
        self.route = []
        self.targets = []
        self.pending_route = None
        self.route_attempt = 0
        self.route_next = 0.0
        self.token = ''
        self.pending_crossing = None
        self.crossing_next = 0.0
        self.crossing_backoff = self.p['crossing_backoff_sec']
        self.last_renewed = 0.0
        self.stop_reason = ''
        self.stop_started = None
        self.stable_since = self.board_since = self.close_since = None
        self.board_requested = False
        self.smoothed_speed = None
        self.last_speed_at = None
        self.distance = -1.0
        self.eta = -1.0
        self.observations = Node(
            'bus_observations', context=self.context,
            start_parameter_services=False, enable_rosout=False)
        self.tf_buffer = Buffer()
        self.tf_listener = TransformListener(self.tf_buffer, self.observations)
        self.group = ReentrantCallbackGroup()
        transient = QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL)
        for key, message, topic, qos in (
            ('odom', Odometry, '/bus/odom', 10),
            ('vehicles', VehicleStateArray, '/hub/vehicles', 10),
            ('safety', SafetyState, '/hub/safety', transient),
            ('crossing', CrossingState, '/crossing/state', transient),
            ('edges', EdgeStateArray, '/traffic/edges', 10),
            ('door', Bool, '/bus/door_open', 1),
            ('final', Twist, '/bus/cmd_vel', 1),
            ('bay', Bool, '/sim/bay_clear', 1),
        ):
            self.observations.create_subscription(
                message, topic, lambda msg, k=key: self.record(k, msg), qos)
        self.commands = self.create_publisher(TwistStamped, '/bus/cmd_vel_candidate', 1)
        self.doors = self.create_publisher(Bool, '/bus/door_request', 1)
        self.arrival = self.create_publisher(BusArrival, '/hub/bus_arrival', 10)
        self.events = self.create_publisher(HubEvent, '/hub/events', 100)
        self.goal_ids = self.create_publisher(String, '/sim/bus_goal_id', 1)
        self.observations.create_subscription(String, '/sim/run_id', self.on_run, transient)
        self.route_client = self.create_client(
            ComputeRoute, '/route/compute', callback_group=self.group)
        self.cross_client = self.create_client(
            RequestCrossing, '/crossing/request', callback_group=self.group)
        self.server = ActionServer(
            self,
            DockBus,
            '/bus/dock',
            self.execute,
            goal_callback=self.accept,
            cancel_callback=self.cancel,
            handle_accepted_callback=self.accepted,
            callback_group=self.group,
        )
        self.create_service(
            ResetScenario, '/bus/prepare_reset', self.prepare_reset, callback_group=self.group
        )
        self.create_service(
            ResetScenario, '/bus/finish_reset', self.finish_reset, callback_group=self.group)
        self.create_timer(0.05, self.tick)
        self.create_timer(0.5, self.publish_state)

    @synchronized
    def on_run(self, message):
        """Correlate transitions to the simulator's current run identifier."""
        self.run_id = message.data

    @synchronized
    def record(self, key, message):
        """Store acquisition and receipt ages without refreshing the source stamp."""
        self.samples[key] = (message, time.monotonic())

    def state(self, key, ttl=1.0):
        """Return a fresh message, including receipt-only Bool watchdogs."""
        sample = self.samples.get(key)
        if key in ('door', 'bay', 'final'):
            return sample[0] if sample and time.monotonic() - sample[1] <= ttl else None
        frame = 'bus/odom' if key == 'odom' else 'map'
        return sample[0] if fresh(self, sample, ttl, frame) else None

    def pose(self):
        """Transform odometry to map; reject malformed poses and stale TF."""
        odom = self.state('odom')
        if odom is None or odom.child_frame_id != 'bus/base_link':
            return None
        p, q, twist = odom.pose.pose.position, odom.pose.pose.orientation, odom.twist.twist
        values = (
            p.x,
            p.y,
            p.z,
            q.x,
            q.y,
            q.z,
            q.w,
            twist.linear.x,
            twist.linear.y,
            twist.linear.z,
            twist.angular.x,
            twist.angular.y,
            twist.angular.z,
        )
        if (
            not all(math.isfinite(v) for v in values)
            or abs(sum(v * v for v in (q.x, q.y, q.z, q.w)) - 1) > 1e-3
            or abs(q.x) + abs(q.y) > 1e-6
        ):
            return None
        try:
            transform = self.tf_buffer.lookup_transform('map', 'bus/odom', rclpy.time.Time())
        except TransformException:
            return None
        tr, rot = transform.transform.translation, transform.transform.rotation
        stamp = transform.header.stamp
        age = self.get_clock().now().nanoseconds * 1e-9 - (stamp.sec + stamp.nanosec * 1e-9)
        if not 0 <= age <= 1.0:
            return None
        if not all(math.isfinite(v) for v in (tr.x, tr.y, rot.z, rot.w)):
            return None
        yaw0 = 2 * math.atan2(rot.z, rot.w)
        return (
            tr.x + p.x * math.cos(yaw0) - p.y * math.sin(yaw0),
            tr.y + p.x * math.sin(yaw0) + p.y * math.cos(yaw0),
            wrap(yaw0 + 2 * math.atan2(q.z, q.w)),
        )

    def zero_measured(self):
        """Require fresh measured zero motion, never infer it from an old command."""
        odom = self.state('odom')
        return bool(
            odom
            and self.pose()
            and all(
                v == 0.0
                for v in (
                    odom.twist.twist.linear.x,
                    odom.twist.twist.linear.y,
                    odom.twist.twist.linear.z,
                    odom.twist.twist.angular.x,
                    odom.twist.twist.angular.y,
                    odom.twist.twist.angular.z,
                )
            )
        )

    @synchronized
    def accept(self, request):
        """Reject unsupported, busy, stale or unsafe goals before reserving the server."""
        safety = self.state('safety', 0.5)
        if (
            self.reserved
            or self.reset_hold
            or request.bus_id != 'bus'
            or request.bay_id != 'B'
            or not math.isfinite(request.max_duration_sec)
            or request.max_duration_sec <= 0
            or safety is None
            or safety.stop_latched
            or safety.reason not in ('clear', 'candidate_stale', 'crossing_not_owned')
            or self.state('door', 0.5) is None
            or self.state('door', 0.5).data
            or self.pose() is None
        ):
            return GoalResponse.REJECT
        sample = self.samples.get('edges')
        observations = (
            valid_edges(sample[0], {e['id'] for e in self.config['edges']})
            if (fresh(self, sample, self.p['edge_freshness_sec']))
            else {}
        )
        pose = self.pose()
        start = min(
            self.config['nodes'], key=lambda n: math.dist(pose[:2], self.config['nodes'][n])
        )
        path, _, reason = shortest_path(self.config, observations, start, 'B', 'bus')
        if not path:
            self.event('GOAL_REJECTED', reason, correlation='')
            return GoalResponse.REJECT
        self.reserved = True
        self.accepted_deadline = time.monotonic() + request.max_duration_sec
        return GoalResponse.ACCEPT

    @synchronized
    def accepted(self, handle):
        """Reserve exclusively at acceptance and start the nonblocking mission."""
        self.goal = handle
        self.done = Future(executor=self.executor)
        self.results[bytes(handle.goal_id.uuid)] = self.done
        self.deadline = self.accepted_deadline
        self.correlation = bytes(handle.goal_id.uuid).hex()
        self.goal_ids.publish(String(data=self.correlation))
        self.route = self.targets = []
        self.route_attempt = 0
        self.route_next = 0.0
        self.distance, self.eta = -1.0, -1.0
        self.stop_reason = ''
        self.stop_started = None
        self.stable_since = self.board_since = self.close_since = None
        self.board_requested = False
        self.smoothed_speed = self.last_speed_at = None
        self.set_phase('APPROACH', 'PLANNING')
        handle.execute()

    async def execute(self, handle):
        """Await a timer-resolved result while subscriptions and cancel remain runnable."""
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
        """Accept cancellation promptly and immediately replace candidates with zero."""
        if handle is not self.goal or self.stop_reason not in ('', 'CANCELED'):
            return CancelResponse.REJECT
        self.begin_stop('CANCELED')
        return CancelResponse.ACCEPT

    def event(self, name, reason, correlation=None):
        """Emit transitions and transactions with action and run correlation."""
        message = HubEvent()
        message.header.stamp = self.get_clock().now().to_msg()
        message.header.frame_id = 'map'
        message.run_id, message.scenario_id = self.run_id, 'm3_baseline'
        message.entity_id = 'bus'
        message.event, message.reason = name, reason
        message.correlation_id = self.correlation if correlation is None else correlation
        self.events.publish(message)

    def set_phase(self, phase, reason=''):
        """Publish state changes rather than one event for every control tick."""
        if (phase, reason) != (self.phase, self.reason):
            self.phase, self.reason = phase, reason
            self.event(phase, reason)

    def command(self, linear=0.0, angular=0.0):
        """Send only base-frame candidates through the independent supervisor."""
        if self.in_tick:
            self.desired_command = (linear, angular)
            return
        message = TwistStamped()
        message.header.stamp = self.get_clock().now().to_msg()
        message.header.frame_id = 'bus/base_link'
        message.twist = Twist()
        message.twist.linear.x, message.twist.angular.z = float(linear), float(angular)
        self.commands.publish(message)

    def door(self, opened):
        """Request a door transition; measured status remains authoritative."""
        if opened != self.last_door_request:
            self.doors.publish(Bool(data=opened))
            self.last_door_request = opened

    def begin_stop(self, reason):
        """Invalidate outstanding route work and start bounded safe cleanup."""
        if not self.stop_reason:
            self.stop_reason = reason
            self.eta = -1.0
            self.smoothed_speed = self.last_speed_at = None
            self.stop_started = time.monotonic()
            self.discard_route()
            self.set_phase('SAFE_STOP', reason)
        self.command()
        self.door(False)

    def discard_route(self):
        """Detach expired requests so late replies cannot revive an old route."""
        if self.pending_route:
            self.route_client.remove_pending_request(self.pending_route[0])
            self.pending_route = None

    def finish(self, success, reason, canceled=False):
        """Return a result on every terminal path, confirming stop before canceled()."""
        self.command()
        self.door(False)
        result = DockBus.Result(
            success=success, final_state='COMPLETE' if success else 'SAFE_STOP', reason=reason
        )
        if success:
            self.goal.succeed()
            self.set_phase('COMPLETE', reason)
        elif canceled:
            self.goal.canceled()
        else:
            self.goal.abort()
        self.event('RESULT', json.dumps({'success': success, 'reason': reason}))
        self.done.set_result(result)
        self.goal = None
        self.reserved = False
        self.discard_route()
        self.goal_ids.publish(String(data=''))

    def route_step(self, now, pose):
        """Retry planner transport failure twice with bounded deterministic backoff."""
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
                        self.begin_stop(response.reason)
                        return
                    ids = list(response.node_ids)
                    if (
                        not ids
                        or ids[-1] != 'B'
                        or len(ids) != len(response.waypoints)
                        or any(n not in self.config['nodes'] for n in ids)
                    ):
                        self.begin_stop('INVALID_ROUTE')
                        return
                    permitted = {e['id'] for e in self.config['edges'] if 'bus' in e['agents']}
                    if (
                        not math.isfinite(response.estimated_cost_sec)
                        or response.estimated_cost_sec < 0
                        or any(
                            '-'.join(sorted((a, b))) not in permitted for a, b in zip(ids, ids[1:])
                        )
                        or any(
                            not all(math.isfinite(v) for v in (w.x, w.y, w.z))
                            or math.dist((w.x, w.y), self.config['nodes'][n]) > 1e-6
                            for n, w in zip(ids, response.waypoints)
                        )
                    ):
                        self.begin_stop('INVALID_ROUTE')
                        return
                    if self.route_prefix and (len(ids) < 2 or ids[1] != self.route_prefix):
                        ids = [self.route_prefix, *ids]
                    self.route = ids
                    targets = [tuple(self.config['nodes'][n]) for n in ids]
                    if not self.route_prefix and math.dist(pose[:2], targets[0]) > 0.05:
                        self.begin_stop('ROUTE_START_MISMATCH')
                        return
                    # Collinear graph nodes do not require a physical stop.
                    self.targets = [targets[0]]
                    for i in range(1, len(targets) - 1):
                        a, b, c = targets[i-1:i+2]
                        if (
                            abs((b[0] - a[0]) * (c[1] - b[1]) - (b[1] - a[1]) * (c[0] - b[0]))
                            > 1e-9
                        ):
                            self.targets.append(b)
                    self.targets.append(targets[-1])
                    self.targets = self.targets[1:]
                    self.event(
                        'ROUTE',
                        json.dumps({'nodes': ids, 'cost_sec': response.estimated_cost_sec}),
                    )
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
        self.route_attempt += 1
        node = min(
            self.config['nodes'], key=lambda n: math.dist(pose[:2], self.config['nodes'][n])
        )
        self.route_prefix = ''
        if math.dist(pose[:2], self.config['nodes'][node]) > 0.05:
            for edge in self.config['edges']:
                if node not in edge['nodes'] or 'bus' not in edge['agents']:
                    continue
                a, b = (self.config['nodes'][n] for n in edge['nodes'])
                if segment_distance(pose[0], pose[1], *a, *b) <= 1e-6:
                    self.route_prefix = next(n for n in edge['nodes'] if n != node)
                    break
            if not self.route_prefix:
                self.begin_stop('OFF_GRAPH_START')
                return
        request = ComputeRoute.Request(start_node=node, goal_node='B', agent_type='bus')
        future = self.route_client.call_async(request)
        self.pending_route = (future, now)
        self.event(
            'ROUTE_REQUEST', json.dumps({'attempt': self.route_attempt, 'sent_monotonic': now})
        )

    def route_valid(self):
        """Check each untraversed route edge against the current snapshot."""
        sample = self.samples.get('edges')
        if not fresh(self, sample, self.p['edge_freshness_sec']):
            return False
        edges = valid_edges(sample[0], {e['id'] for e in self.config['edges']})
        return all(
            (edge := edges.get('-'.join(sorted((a, b))))) is not None
            and edge.valid
            and not edge.blocked
            for a, b in zip(self.route, self.route[1:])
        )

    def crossing_step(self, now, pose):
        """Maintain one bounded token transaction and never release inside C."""
        state = self.state('crossing', 0.5)
        inside = intersects_crossing(pose[0], pose[1], 0.65)
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
                    self.event(
                        'CROSSING_DENIED',
                        operation + ':' + (response.reason if response else 'TRANSPORT_FAILURE'),
                    )
                    self.crossing_next = now + self.crossing_backoff
                    self.crossing_backoff = min(
                        self.p['crossing_backoff_max_sec'], 2 * self.crossing_backoff
                    )
            elif now - sent >= (self.p['crossing_ack_timeout_sec'] if self.token else 1.0):
                self.cross_client.remove_pending_request(future)
                self.pending_crossing = None
                self.crossing_next = now + self.crossing_backoff
            else:
                return
        if self.token:
            if (
                state
                and state.owner_id != 'bus'
                and not inside
                and now - self.last_renewed > self.p['crossing_ack_timeout_sec']
            ):
                self.token = ''
                return
            # Release only after travelling beyond C, or safe terminal cleanup outside C.
            cleared = pose[0] > 6.1 or (self.goal is None or self.stop_reason) and not inside
            operation = 'RELEASE' if cleared else 'RENEW'
            if operation == 'RENEW' and now - self.last_renewed < self.p['crossing_renew_sec']:
                return
        elif (
            self.goal
            and not self.stop_reason
            and self.targets
            and pose[0] < 5.8
            and (inside or 2.5 <= pose[0] and 0.95 <= pose[1] <= 5.05)
        ):
            # Acquire before the five-metre ETA checkpoint, not only at the stop margin.
            operation = 'ACQUIRE'
        else:
            return
        if now < self.crossing_next or not self.cross_client.service_is_ready():
            return
        request = RequestCrossing.Request(
            requester_id='bus',
            operation=operation,
            token=self.token if operation != 'ACQUIRE' else '',
        )
        self.pending_crossing = (self.cross_client.call_async(request), now, operation)

    def update_eta(self, pose, now, angular_error=0.0):
        """Estimate docking time; keep unknown waits and stale speed explicitly invalid."""
        if not self.targets:
            self.distance, self.eta = 0.0, -1.0
            return
        points = [pose[:2], *self.targets]
        self.distance = sum(math.dist(a, b) for a, b in zip(points, points[1:]))
        odom = self.state('odom')
        speed = abs(odom.twist.twist.linear.x) if odom else None
        if speed is not None and speed > 0.001:
            alpha = (
                1.0
                if self.last_speed_at is None
                else -math.expm1(-(now - self.last_speed_at) / self.p['eta_smoothing_sec'])
            )
            self.smoothed_speed = (
                speed
                if self.smoothed_speed is None
                else (self.smoothed_speed + alpha * (speed - self.smoothed_speed))
            )
            self.last_speed_at = now
        crossing = self.state('crossing', 0.5)
        owned = (
            crossing
            and crossing.valid
            and crossing.state == 'OWNED'
            and crossing.owner_id == 'bus'
            and crossing.token == self.token
            and bool(self.token)
            and now - self.last_renewed <= self.p['crossing_ack_timeout_sec']
        )
        if route_needs_crossing(points) and not owned:
            self.eta = -1.0
            return
        if self.phase == 'BOARD' or self.phase == 'COMPLETE':
            self.eta = 0.0
        elif self.phase in ('WAIT', 'SAFE_STOP') or self.smoothed_speed is None:
            self.eta = -1.0
        elif speed is None or speed <= 0.001 and abs(angular_error) < 1e-7:
            self.eta = -1.0
        else:
            final = min(self.distance, self.p['final_approach_distance'])
            cruise = max(0.0, self.distance - final)
            # Docking stops within 0.05 m, rather than asymptotically targeting exact B.
            final_time = max(0.0, final - 0.05) / min(
                self.p['final_approach_speed'], max(self.smoothed_speed, 0.05)
            )
            self.eta = cruise / max(self.smoothed_speed, 0.05) + final_time + 1.15
            if abs(angular_error) > 1e-7:
                self.eta += abs(angular_error) / 1.0 + 6.0

    @synchronized
    def tick(self):
        """Publish exactly one candidate per control tick, including all zero paths."""
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

    def control_tick(self):
        """Advance one bounded state-machine step; callbacks are serialized."""
        now = time.monotonic()
        pose = self.pose()
        self.command()
        if pose:
            self.crossing_step(now, pose)
        if self.reset_waiter and not self.reset_waiter.done():
            door = self.state('door', 0.5)
            zero = self.goal is None and self.zero_measured()
            observation = (self.goal is not None, zero, door.data if door else None,
                           pose is not None)
            if observation != self.reset_observation:
                print(json.dumps({
                    'event': 'bus_reset_observation',
                    'elapsed_sec': now - self.reset_started,
                    'goal_active': observation[0], 'zero_measured': zero,
                    'door_open': observation[2], 'pose_valid': observation[3],
                }, sort_keys=True), flush=True)
                self.reset_observation = observation
            if zero and door and not door.data:
                self.reset_waiter.set_result(True)
            elif now >= self.reset_deadline:
                self.reset_waiter.set_result(False)
        if self.reset_finish_waiter and not self.reset_finish_waiter.done():
            safety = self.state('safety', 0.5)
            zero = self.zero_measured()
            ready = self.reset_finish_ready()
            if ready or now >= self.reset_finish_deadline:
                print(json.dumps({
                    'event': 'bus_finish_reset_observation', 'ready': ready,
                    'reset_hold': self.reset_hold, 'goal_active': self.goal is not None,
                    'zero_measured': zero,
                    'safety_reason': safety.reason if safety else None,
                    'stop_latched': safety.stop_latched if safety else None,
                }, sort_keys=True), flush=True)
                self.reset_finish_waiter.set_result(ready)
        if not self.goal:
            return
        safety = self.state('safety', 0.5)
        vehicles = self.state('vehicles')
        door = self.state('door', 0.5)
        if self.goal.is_cancel_requested:
            self.begin_stop('CANCELED')
        elif now >= self.deadline:
            self.begin_stop('TIMEOUT')
        elif safety is None or safety.stop_latched:
            sample = self.samples.get('safety')
            observed = sample[0] if sample else None
            stamp = (observed.header.stamp.sec + observed.header.stamp.nanosec * 1e-9
                     if observed else None)
            self.event('SAFETY_INPUT_REJECTED', json.dumps({
                'receipt_age_sec': now - sample[1] if sample else None,
                'source_age_sec': (self.get_clock().now().nanoseconds * 1e-9 - stamp
                                   if stamp is not None else None),
                'stop_latched': observed.stop_latched if observed else None,
                'last_reason': observed.reason if observed else None,
            }, sort_keys=True))
            self.begin_stop('SAFETY_STOP')
        elif pose is None or vehicles is None:
            self.begin_stop('STALE_POSE')
        elif (
            len(vehicles.vehicles) != 2
            or {v.vehicle_id for v in vehicles.vehicles} != {'bus', 'robot'}
            or any(
                not v.valid
                or v.kind != v.vehicle_id
                or not all(
                    math.isfinite(x) for x in (v.pose.x, v.pose.y, v.pose.theta, v.speed_mps)
                )
                for v in vehicles.vehicles
            )
        ):
            self.begin_stop('INVALID_VEHICLE_OBSERVATION')
        elif door is None:
            self.begin_stop('STALE_DOOR')
        elif safety.reason not in (
            'clear',
            'candidate_stale',
            'crossing_not_owned',
            'bus_door_open',
            'reset_in_progress',
        ):
            self.begin_stop('SAFETY_INPUT_UNKNOWN:' + safety.reason)
        if self.stop_reason:
            self.command()
            self.door(False)
            if (
                self.zero_measured()
                and door
                and not door.data
                and self.samples['odom'][1] > self.stop_started
                and self.state('final', 0.5) is not None
                and self.samples['final'][1] > self.stop_started
                and self.samples['final'][0].linear.x == 0
                and self.samples['final'][0].angular.z == 0
            ):
                self.finish(False, self.stop_reason, canceled=self.goal.is_cancel_requested)
            elif now - self.stop_started >= 2.0:
                self.finish(False, self.stop_reason + ':STOP_UNCONFIRMED')
            return
        if not self.targets:
            self.route_step(now, pose)
            return
        while len(self.route) > 1:
            a, b = (self.config['nodes'][n] for n in self.route[:2])
            progress = sum((pose[i] - a[i]) * (b[i] - a[i]) for i in (0, 1))
            if progress < math.dist(a, b) ** 2 - 1e-7:
                break
            self.route.pop(0)
        if not self.route_valid():
            self.begin_stop('ROUTE_INVALID_OR_STALE')
            return
        bay = self.state('bay')
        if bay is None or not bay.data:
            self.set_phase('WAIT', 'BAY_UNAVAILABLE')
            self.eta = -1.0
            return
        target = self.targets[0]
        distance = math.dist(pose[:2], target)
        final = len(self.targets) == 1
        threshold = 0.05 if final else 1e-8
        if distance <= threshold:
            if not final:
                self.targets.pop(0)
                return
            yaw_error = wrap(-pose[2])
            if not self.board_requested:
                self.set_phase('DOCK')
            if abs(yaw_error) > 1e-7:
                self.command(0.0, max(-1.0, min(1.0, 2.0 * yaw_error)))
                self.stable_since = None
                return
            if not self.board_requested:
                if not self.zero_measured():
                    self.stable_since = None
                    return
                if self.stable_since is None:
                    self.stable_since = now
                if now - self.stable_since < 1.0:
                    return
                self.set_phase('BOARD')
                self.board_requested = True
                self.door(True)
                if door.data:
                    self.board_since = now
                return
            self.set_phase('BOARD')
            self.eta = 0.0
            if self.board_since is None:
                self.door(True)
                if door.data:
                    self.board_since = now
            elif now - self.board_since < self.p['boarding_interval_sec']:
                if not door.data or not self.zero_measured():
                    self.begin_stop('BOARDING_INTERLOCK')
                    return
                self.door(True)
            else:
                self.door(False)
                if self.close_since is None:
                    self.close_since = now
                # Demand a measured status received after the close request.
                if not door.data and self.samples['door'][1] > self.close_since:
                    self.finish(True, 'DOCKED_BOARDED_DOOR_CLOSED')
                elif now - self.close_since > 1.0:
                    self.begin_stop('DOOR_CLOSE_TIMEOUT')
            return
        desired = math.atan2(target[1] - pose[1], target[0] - pose[0])
        # M1 roads are axis aligned. Do not steer toward numerical lateral error:
        # align at nodes to high precision, then translate along the segment.
        if abs(target[0] - pose[0]) < 1e-6:
            desired = math.copysign(math.pi / 2, target[1] - pose[1])
        elif abs(target[1] - pose[1]) < 1e-6:
            desired = 0.0 if target[0] > pose[0] else math.pi
        error = wrap(desired - pose[2])
        points = [pose[:2], *self.targets]
        self.distance = sum(math.dist(a, b) for a, b in zip(points, points[1:]))
        if abs(error) > 1e-9:
            self.set_phase('APPROACH' if self.distance > 1.0 else 'DOCK')
            self.update_eta(pose, now, error)
            self.command(0.0, max(-1.0, min(1.0, 2.0 * error)))
            return
        if intersects_crossing(pose[0], pose[1], 0.56):
            state = self.state('crossing', 0.5)
            if not (
                self.token
                and now - self.last_renewed <= self.p['crossing_ack_timeout_sec']
                and state
                and state.valid
                and state.owner_id == 'bus'
                and state.token == self.token
                and state.state == 'OWNED'
            ):
                self.set_phase('WAIT', 'CROSSING_UNAVAILABLE')
                self.eta = -1.0
                return
        if door.data:
            self.begin_stop('DOOR_OPEN_WHILE_APPROACHING')
            return
        self.set_phase('APPROACH' if self.distance > 1.0 else 'DOCK')
        self.update_eta(pose, now, error)
        cap = self.p['bus_speed_limit']
        if final and distance <= self.p['final_approach_distance'] + 0.08:
            cap = self.p['final_approach_speed']
        self.command(min(cap, 2.0 * distance))

    @synchronized
    def publish_state(self):
        """Publish arrival and action feedback at exactly the declared timer rate."""
        msg = BusArrival()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.header.frame_id = 'map'
        msg.bus_id, msg.state = 'bus', self.phase
        door = self.state('door', 0.5)
        previous_door = self.samples.get('door')
        if previous_door is None:
            return
        msg.door_open = previous_door[0].data
        if door is None:
            msg.state = 'UNKNOWN'
        msg.eta_sec = float(self.eta if self.goal or self.phase == 'COMPLETE' else -1.0)
        if door is None:
            msg.eta_sec = -1.0
        msg.eta_valid = msg.eta_sec >= 0.0
        self.arrival.publish(msg)
        if self.goal:
            self.goal.publish_feedback(
                DockBus.Feedback(
                    phase=self.phase,
                    distance_remaining_m=float(self.distance),
                    eta_sec=msg.eta_sec,
                )
            )

    async def prepare_reset(self, request, response):
        """Hold new goals and await terminal/zero/closed acknowledgement before world reset."""
        received_at = time.monotonic()
        print(json.dumps({
            'event': 'bus_reset_received', 'monotonic': received_at,
        }), flush=True)
        lock_started = time.monotonic()
        with self.lock:
            print(json.dumps({
                'event': 'bus_reset_lock_acquired',
                'lock_wait_sec': time.monotonic() - lock_started,
            }), flush=True)
            if (request.scenario_id != 'm2_baseline' or self.reset_waiter
                    or self.reset_finish_waiter):
                response.reason = 'UNKNOWN_OR_BUSY'
                return response
            self.reset_hold = True
            self.command()
            self.door(False)
            if self.goal:
                self.begin_stop('SCENARIO_RESET')
            if self.reset_zero_closed():
                response.success = True
                response.reason = 'BUS_ZERO_CLOSED'
                return response
            self.reset_started = time.monotonic()
            self.reset_deadline = self.reset_started + 0.8
            self.reset_observation = None
            waiter = Future(executor=self.executor)
            self.reset_waiter = waiter
            print(json.dumps({'event': 'bus_reset_waiting_for_zero'}), flush=True)
        response.success = await waiter
        print(json.dumps({
            'event': 'bus_reset_complete', 'success': response.success,
            'elapsed_sec': time.monotonic() - received_at,
        }), flush=True)
        with self.lock:
            self.reset_waiter = None
            response.reason = 'BUS_ZERO_CLOSED' if response.success else 'BUS_RESET_UNCONFIRMED'
        return response

    async def finish_reset(self, request, response):
        """Await fresh zero/hold observations briefly before releasing administrative hold."""
        with self.lock:
            if (request.scenario_id != 'm2_baseline' or not self.reset_hold
                    or self.reset_waiter is not None or self.reset_finish_waiter is not None):
                response.reason = 'BUS_RESET_UNSAFE_OR_BUSY'
                return response
            if self.reset_finish_ready():
                self.release_reset_hold()
                response.success = True
                response.reason = 'BUS_RESET'
                return response
            waiter = Future(executor=self.executor)
            self.reset_finish_waiter = waiter
            self.reset_finish_deadline = time.monotonic() + 0.25
        response.success = await waiter
        with self.lock:
            self.reset_finish_waiter = None
            response.reason = 'BUS_RESET' if response.success else 'BUS_RESET_UNSAFE'
            if response.success:
                self.release_reset_hold()
        return response

    def reset_zero_closed(self):
        """Require a terminal mission plus fresh measured zero and closed door."""
        door = self.state('door', 0.5)
        return bool(self.goal is None and self.zero_measured() and door and not door.data)

    def reset_finish_ready(self):
        """Use identical freshness/interlock checks for immediate and delayed reset ack."""
        safety = self.state('safety', 0.5)
        return bool(self.reset_hold and self.reset_zero_closed() and safety
                    and not safety.stop_latched and safety.reason == 'reset_in_progress')

    def release_reset_hold(self):
        """Clear administrative mission caches only under the caller's state lock."""
        self.reset_hold = False
        self.token = ''
        if self.pending_crossing:
            self.cross_client.remove_pending_request(self.pending_crossing[0])
            self.pending_crossing = None
        self.route = self.targets = []
        self.smoothed_speed = self.last_speed_at = None
        self.eta = -1.0
        self.set_phase('IDLE')


def main(args=None):
    """Use two executor threads and locked shared state as assignment section 7.3 requires."""
    rclpy.init(args=args)
    node = BusManager()
    executor = MultiThreadedExecutor(num_threads=2)
    executor.add_node(node)
    observations = SingleThreadedExecutor(context=node.context)
    observations.add_node(node.observations)

    def receive_observations():
        try:
            observations.spin()
        except (KeyboardInterrupt, rclpy.executors.ExternalShutdownException):
            pass

    receiver = Thread(target=receive_observations, name='bus-observations')
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
            node.door(False)
        node.destroy_node()
        node.observations.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
