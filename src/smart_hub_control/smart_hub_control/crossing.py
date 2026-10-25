"""Arbitrate one crossing owner from fresh observations, never ground truth."""
from collections import OrderedDict
import math
import time
import uuid

import rclpy
from rclpy.action import ActionClient
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile
from smart_hub_interfaces.action import DockBus
from smart_hub_interfaces.msg import (
    BusArrival, CrossingState, DemandPrediction, HubEvent, QueueState,
    VehicleStateArray,
)
from smart_hub_interfaces.srv import RequestCrossing, ResetScenario
from smart_hub_sim.geometry import intersects_crossing, swept_clear
from smart_hub_sim.world import POSE_NOISE_BOUND_M


class CrossingArbiter(Node):
    """Retain ownership until fresh observations prove full footprint clearance."""

    def __init__(self):
        """Create the crossing service and independent observation watchdog."""
        super().__init__('hub_coordinator')
        self.declare_parameter('crossing_clear_sec', 2.0)
        self.declare_parameter('crossing_lease_sec', 1.0)
        self.declare_parameter('queue_confidence_min', 0.5)
        self.declare_parameter('dispatch_high', 6.0)
        self.declare_parameter('dispatch_low', 4.0)
        self.declare_parameter('dispatch_policy', 'predictive')
        self.dispatch_high = float(self.get_parameter('dispatch_high').value)
        self.dispatch_low = float(self.get_parameter('dispatch_low').value)
        self.dispatch_policy = str(self.get_parameter('dispatch_policy').value)
        if (not all(math.isfinite(value) for value in
                    (self.dispatch_high, self.dispatch_low)) or
                not 0 <= self.dispatch_low < self.dispatch_high or
                self.dispatch_policy not in ('predictive', 'reactive')):
            raise ValueError('invalid dispatch thresholds or policy')
        self.confidence_min = float(self.get_parameter('queue_confidence_min').value)
        if not math.isfinite(self.confidence_min) or not 0 <= self.confidence_min <= 1:
            raise ValueError('invalid queue confidence threshold')
        self.clear_sec = float(self.get_parameter('crossing_clear_sec').value)
        self.lease_sec = float(self.get_parameter('crossing_lease_sec').value)
        if not (math.isfinite(self.clear_sec) and self.clear_sec >= 2.0 and
                math.isfinite(self.lease_sec) and self.lease_sec > 0):
            raise ValueError('invalid crossing timing parameters')
        self.queue = None
        self.demand = None
        self.bus_arrival = None
        self.dispatch_high_samples = 0
        self.dispatch_low_samples = 0
        self.dispatch_escalated = False
        self.dispatch_outstanding = False
        self.last_dispatch = float('-inf')
        self.vehicles = None
        self.owner = self.token = ''
        self.expiry = 0.0
        self._lease_lost = False
        self.clear_since = None
        self.waiters = OrderedDict()
        self.previous = None
        qos = QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL)
        self.publisher = self.create_publisher(CrossingState, '/crossing/state', qos)
        self.events = self.create_publisher(HubEvent, '/hub/events', 100)
        self.create_subscription(QueueState, '/hub/queue', self.on_queue, 10)
        self.create_subscription(DemandPrediction, '/hub/demand',
                                 self.on_demand, 10)
        self.create_subscription(BusArrival, '/hub/bus_arrival',
                                 self.on_bus_arrival, 10)
        self.bus_action = ActionClient(self, DockBus, '/bus/dock')
        self.create_subscription(VehicleStateArray, '/hub/vehicles', self.on_vehicles, 10)
        self.create_service(RequestCrossing, '/crossing/request', self.request)
        self.create_service(ResetScenario, '/crossing/reset_state', self.reset)
        self.create_timer(0.1, self.tick)
        self.create_timer(1.0, self.dispatch_tick)

    def on_queue(self, msg):
        """Preserve source and local receipt times independently."""
        self.queue = (msg, time.monotonic())

    def on_demand(self, msg):
        """Preserve forecast receipt time for dispatch eligibility."""
        self.demand = (msg, time.monotonic())

    def on_bus_arrival(self, msg):
        """Track independently observed bus availability."""
        self.bus_arrival = (msg, time.monotonic())

    def _dispatch_fresh(self, sample, ttl):
        """Require source and receipt age for a dispatch input."""
        if sample is None:
            return False
        msg, received = sample
        stamp = msg.header.stamp.sec + msg.header.stamp.nanosec * 1e-9
        age = self.get_clock().now().nanoseconds * 1e-9 - stamp
        return (msg.header.frame_id == 'map' and 0 <= age <= ttl and
                time.monotonic() - received <= ttl)

    def _dispatch_event(self, name, reason):
        """Expose transition and fallback decisions for independent evaluation."""
        event = HubEvent()
        event.header.stamp = self.get_clock().now().to_msg()
        event.header.frame_id = 'map'
        event.entity_id = 'hub_coordinator'
        event.event = name
        event.reason = reason
        self.events.publish(event)

    def dispatch_tick(self):
        """Require sustained valid demand, availability and a thirty-second cooldown."""
        queue_fresh = (self._dispatch_fresh(self.queue, 0.5) and
                       self.queue[0].valid and
                       self.queue[0].confidence >= self.confidence_min)
        demand_fresh = (self._dispatch_fresh(self.demand, 1.5) and
                        self.demand[0].valid and
                        self.demand[0].horizon_sec == 30 and
                        math.isfinite(self.demand[0].predicted_count))
        if self.dispatch_policy == 'predictive':
            if not demand_fresh:
                self.dispatch_high_samples = self.dispatch_low_samples = 0
                if queue_fresh:
                    self._dispatch_event('QUEUE_FALLBACK_OBSERVED',
                                         f'count={self.queue[0].count};forecast=invalid')
                return
            value = self.demand[0].predicted_count
        else:
            if not queue_fresh:
                self.dispatch_high_samples = self.dispatch_low_samples = 0
                return
            value = self.queue[0].count
        self.dispatch_high_samples = (self.dispatch_high_samples + 1
                                      if value >= self.dispatch_high else 0)
        self.dispatch_low_samples = (self.dispatch_low_samples + 1
                                     if value < self.dispatch_low else 0)
        if self.dispatch_low_samples >= 5 and self.dispatch_escalated:
            self.dispatch_escalated = False
            self._dispatch_event('DISPATCH_ESCALATION_CLEARED', f'value={value}')
        if self.dispatch_high_samples < 3 or self.dispatch_escalated:
            return
        if self.dispatch_outstanding or time.monotonic() - self.last_dispatch < 30.0:
            return
        if (not self._dispatch_fresh(self.bus_arrival, 1.0) or
                self.bus_arrival[0].state not in ('IDLE', 'COMPLETE') or
                self.bus_arrival[0].door_open or
                not self.bus_action.server_is_ready()):
            return
        self.dispatch_outstanding = True
        self.dispatch_escalated = True
        self.last_dispatch = time.monotonic()
        self._dispatch_event('BUS_DISPATCH_REQUESTED', f'value={value}')
        goal = DockBus.Goal(bus_id='bus', bay_id='B', max_duration_sec=120.0)
        future = self.bus_action.send_goal_async(goal)
        future.add_done_callback(self._dispatch_goal_response)

    def _dispatch_goal_response(self, future):
        """Track the one outstanding goal through rejection or terminal result."""
        try:
            handle = future.result()
            if not handle.accepted:
                self.dispatch_outstanding = False
                self._dispatch_event('BUS_DISPATCH_REJECTED', 'goal rejected')
                return
            handle.get_result_async().add_done_callback(self._dispatch_result)
        except Exception as error:
            self.dispatch_outstanding = False
            self._dispatch_event('BUS_DISPATCH_FAILED', repr(error))

    def _dispatch_result(self, future):
        """Release outstanding ownership only after a terminal action result."""
        self.dispatch_outstanding = False
        try:
            result = future.result().result
            self._dispatch_event('BUS_DISPATCH_RESULT',
                                 f'success={result.success};reason={result.reason}')
        except Exception as error:
            self._dispatch_event('BUS_DISPATCH_FAILED', repr(error))

    def on_vehicles(self, msg):
        """Receive synchronized observed vehicle states."""
        self.vehicles = (msg, time.monotonic())

    def fresh(self, sample):
        """Reject missing, future, frozen or old observations."""
        if sample is None:
            return False
        msg, received = sample
        stamp = msg.header.stamp.sec + msg.header.stamp.nanosec * 1e-9
        age = self.get_clock().now().nanoseconds * 1e-9 - stamp
        return msg.header.frame_id == 'map' and 0 <= age <= 1 and (
            time.monotonic() - received <= 1)

    def observe(self):
        """Return validity, pedestrian occupancy and whole-footprint occupancy."""
        if not self.fresh(self.queue) or not self.fresh(self.vehicles):
            return False, False, True
        queue = self.queue[0]
        if (not queue.valid or queue.zone_id != 'Q' or
                not math.isfinite(queue.confidence) or
                not self.confidence_min <= queue.confidence <= 1):
            return False, False, True
        stamp = self.vehicles[0].header.stamp
        age = self.get_clock().now().nanoseconds * 1e-9 - (
            stamp.sec + stamp.nanosec * 1e-9)
        seen = set()
        occupied = False
        for vehicle in self.vehicles[0].vehicles:
            values = (vehicle.pose.x, vehicle.pose.y, vehicle.pose.theta, vehicle.speed_mps)
            if (not vehicle.valid or not all(math.isfinite(v) for v in values) or
                    vehicle.vehicle_id in seen or vehicle.kind not in ('bus', 'robot') or
                    (vehicle.vehicle_id in ('bus', 'robot') and
                     vehicle.kind != vehicle.vehicle_id)):
                return False, queue.crossing_occupied, True
            seen.add(vehicle.vehicle_id)
            radius = 0.2 if vehicle.kind == 'robot' else 0.3
            position = (vehicle.pose.x, vehicle.pose.y)
            if not swept_clear(position, position, radius, (), ()):
                return False, queue.crossing_occupied, True
            occupied |= intersects_crossing(
                vehicle.pose.x, vehicle.pose.y,
                radius + math.sqrt(2.0) * POSE_NOISE_BOUND_M +
                max(0.0, age) * (0.25 if vehicle.kind == 'robot' else 0.4))
        if not {'bus', 'robot'}.issubset(seen):
            return False, queue.crossing_occupied, True
        return True, queue.crossing_occupied, occupied

    def refresh(self):
        """Age leases without ever releasing an occupied or unknown crossing."""
        now = time.monotonic()
        valid, pedestrian, occupied = self.observe()
        if self.owner and now > self.expiry and not self._lease_lost:
            self._lease_lost = True
            self.clear_since = None
        if valid and not pedestrian and not occupied:
            if self.clear_since is None:
                self.clear_since = now
        else:
            self.clear_since = None
        if self.owner and now > self.expiry and self.clear_since is not None:
            if now - self.clear_since >= self.clear_sec:
                self.owner = self.token = ''
        for requester, received in list(self.waiters.items()):
            if now - received > self.lease_sec:
                del self.waiters[requester]
        return valid, pedestrian, occupied

    def request(self, request, response):
        """Perform prompt token-checked ACQUIRE, RENEW and RELEASE operations."""
        valid, pedestrian, occupied = self.refresh()
        now = time.monotonic()
        response.granted = False
        response.reason = 'INVALID_REQUEST'
        if request.requester_id not in ('bus', 'robot'):
            return response
        matching = (request.requester_id == self.owner and request.token == self.token and
                    bool(self.token))
        if request.operation == 'RENEW':
            if matching and valid and not pedestrian:
                self.expiry = now + self.lease_sec
                self._lease_lost = False
                response.granted, response.token, response.reason = True, self.token, 'RENEWED'
            else:
                response.reason = 'INVALID_OR_EXPIRED_TOKEN'
        elif request.operation == 'RELEASE':
            if matching and valid and not pedestrian and not occupied:
                self.owner = self.token = ''
                response.granted, response.reason = True, 'RELEASED'
            else:
                response.reason = 'TOKEN_OR_CLEARANCE_REQUIRED'
        elif request.operation == 'ACQUIRE' and not request.token:
            if request.requester_id not in self.waiters and len(self.waiters) >= 32:
                response.reason = 'QUEUE_FULL'
                return response
            self.waiters[request.requester_id] = now
            if not valid:
                response.reason = 'UNKNOWN'
            elif pedestrian or occupied:
                response.reason = 'OCCUPIED'
            elif self.owner:
                response.reason = 'OWNER_EXISTS'
            elif self.clear_since is None or now - self.clear_since < self.clear_sec:
                response.reason = 'CLEAR_DEBOUNCE'
            elif next(iter(self.waiters)) != request.requester_id:
                response.reason = 'FIFO_WAIT'
            else:
                self.owner = request.requester_id
                self.token = uuid.uuid4().hex
                self.expiry = now + self.lease_sec
                self._lease_lost = False
                del self.waiters[self.owner]
                response.granted, response.token, response.reason = True, self.token, 'ACQUIRED'
        self.tick()
        return response

    def reset(self, request, response):
        """Acknowledge administrative reset only with fresh proven clearance."""
        valid, pedestrian, occupied = self.refresh()
        response.success = (request.scenario_id == 'm2_baseline' and valid and
                            not pedestrian and not occupied)
        response.reason = 'RESET' if response.success else 'UNSAFE_OR_UNKNOWN'
        if response.success:
            self.owner = self.token = ''
            self.waiters.clear()
            self.clear_since = None
            self.tick()
        return response

    def tick(self):
        """Publish UNKNOWN explicitly and log every crossing state transition."""
        valid, pedestrian, occupied = self.refresh()
        msg = CrossingState()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.header.frame_id = 'map'
        msg.owner_id, msg.token = self.owner, self.token
        msg.valid, msg.pedestrian_present = valid, pedestrian
        msg.state = 'UNKNOWN' if not valid else (
            'HOLD' if self.owner and time.monotonic() > self.expiry else (
                'OWNED' if self.owner else ('OCCUPIED' if pedestrian or occupied else 'CLEAR')))
        self.publisher.publish(msg)
        state = (msg.state, msg.owner_id, msg.valid, msg.pedestrian_present)
        if state != self.previous:
            event = HubEvent()
            event.header = msg.header
            event.entity_id = self.get_name()
            event.event = 'CROSSING_STATE'
            event.reason = str(state)
            self.events.publish(event)
            self.previous = state


def main(args=None):
    """Run the independent crossing arbiter."""
    rclpy.init(args=args)
    node = CrossingArbiter()
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, rclpy.executors.ExternalShutdownException):
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
