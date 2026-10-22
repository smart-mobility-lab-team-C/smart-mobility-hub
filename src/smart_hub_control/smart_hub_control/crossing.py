"""Arbitrate one crossing owner from fresh observations, never ground truth."""
from collections import OrderedDict
import math
import time
import uuid

import rclpy
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile
from smart_hub_interfaces.msg import CrossingState, HubEvent, QueueState, VehicleStateArray
from smart_hub_interfaces.srv import RequestCrossing, ResetScenario
from smart_hub_sim.geometry import intersects_crossing, swept_clear


class CrossingArbiter(Node):
    """Retain ownership until fresh observations prove full footprint clearance."""

    def __init__(self):
        """Create the crossing service and independent observation watchdog."""
        super().__init__('hub_coordinator')
        self.declare_parameter('crossing_clear_sec', 2.0)
        self.declare_parameter('crossing_lease_sec', 1.0)
        self.declare_parameter('queue_confidence_min', 0.5)
        self.confidence_min = float(self.get_parameter('queue_confidence_min').value)
        if not math.isfinite(self.confidence_min) or not 0 <= self.confidence_min <= 1:
            raise ValueError('invalid queue confidence threshold')
        self.clear_sec = float(self.get_parameter('crossing_clear_sec').value)
        self.lease_sec = float(self.get_parameter('crossing_lease_sec').value)
        if not (math.isfinite(self.clear_sec) and self.clear_sec >= 2.0 and
                math.isfinite(self.lease_sec) and self.lease_sec > 0):
            raise ValueError('invalid crossing timing parameters')
        self.queue = None
        self.vehicles = None
        self.owner = self.token = ''
        self.expiry = 0.0
        self.clear_since = None
        self.waiters = OrderedDict()
        self.previous = None
        qos = QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL)
        self.publisher = self.create_publisher(CrossingState, '/crossing/state', qos)
        self.events = self.create_publisher(HubEvent, '/hub/events', 100)
        self.create_subscription(QueueState, '/hub/queue', self.on_queue, 10)
        self.create_subscription(VehicleStateArray, '/hub/vehicles', self.on_vehicles, 10)
        self.create_service(RequestCrossing, '/crossing/request', self.request)
        self.create_service(ResetScenario, '/crossing/reset_state', self.reset)
        self.create_timer(0.1, self.tick)

    def on_queue(self, msg):
        """Preserve source and local receipt times independently."""
        self.queue = (msg, time.monotonic())

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
        seen = set()
        occupied = False
        for vehicle in self.vehicles[0].vehicles:
            values = (vehicle.pose.x, vehicle.pose.y, vehicle.pose.theta, vehicle.speed_mps)
            if (not vehicle.valid or not all(math.isfinite(v) for v in values) or
                    vehicle.vehicle_id in seen or vehicle.kind not in ('bus', 'robot', 'car') or
                    (vehicle.vehicle_id in ('bus', 'robot') and
                     vehicle.kind != vehicle.vehicle_id)):
                return False, queue.crossing_occupied, True
            seen.add(vehicle.vehicle_id)
            radius = 0.2 if vehicle.kind == 'robot' else 0.3
            position = (vehicle.pose.x, vehicle.pose.y)
            if not swept_clear(position, position, radius, (), ()):
                return False, queue.crossing_occupied, True
            occupied |= intersects_crossing(vehicle.pose.x, vehicle.pose.y, radius)
        if not {'bus', 'robot'}.issubset(seen):
            return False, queue.crossing_occupied, True
        return True, queue.crossing_occupied, occupied

    def refresh(self):
        """Age leases without ever releasing an occupied or unknown crossing."""
        now = time.monotonic()
        valid, pedestrian, occupied = self.observe()
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
