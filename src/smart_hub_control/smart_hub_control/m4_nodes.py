"""ROS adapters for sensor-backed parking and traffic monitoring."""

import json
import math
import time

import rclpy
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile
from smart_hub_interfaces.msg import (
    EdgeState, EdgeStateArray, HubEvent, ParkingSlot, ParkingState, SafetyState,
    SlotObservationArray, VehicleStateArray,
)
from smart_hub_interfaces.srv import ReleaseParking, ReserveParking, ResetScenario
from std_msgs.msg import Bool, String

from .parking import entrance_distances, Parking
from .routing import fresh, load_map
from .traffic import Traffic


def seconds(stamp):
    """Convert ROS timestamps to seconds."""
    return stamp.sec + stamp.nanosec * 1e-9


def set_stamp(stamp, value):
    """Populate a nonnegative ROS timestamp."""
    stamp.sec = int(value)
    stamp.nanosec = int((value - int(value)) * 1e9)


class M4Node(Node):
    """Share transition evidence and safety-held reset validation."""

    def __init__(self, name):
        """Retain run identity and independently received safety state."""
        super().__init__(name)
        self.run_id = ''
        self.safety = None
        self.previous = {}
        self.events = self.create_publisher(HubEvent, '/hub/events', 100)
        qos = QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL)
        self.create_subscription(String, '/sim/run_id', self.run_cb, qos)
        self.create_subscription(SafetyState, '/hub/safety', self.safety_cb, qos)

    def run_cb(self, msg):
        """Correlate transitions with the simulator's current run."""
        self.run_id = msg.data

    def safety_cb(self, msg):
        """Keep source and local safety freshness for reset validation."""
        self.safety = (msg, time.monotonic())

    def event(self, entity, event, reason, correlation=''):
        """Record decisions, commands, acknowledgments and state changes."""
        msg = HubEvent()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.header.frame_id = 'map'
        msg.run_id, msg.scenario_id = self.run_id, 'm4_baseline'
        msg.entity_id, msg.event, msg.reason = entity, event, reason
        msg.correlation_id = correlation
        self.events.publish(msg)

    def reset_allowed(self, request):
        """Require the coordinator's fresh protective hold before acknowledging."""
        return bool(request.scenario_id == 'm2_baseline' and fresh(self, self.safety, .5)
                    and not self.safety[0].stop_latched
                    and self.safety[0].reason == 'reset_in_progress')


class ParkingManager(M4Node):
    """Expose atomic reservation services and conservative barrier requests."""

    def __init__(self):
        """Subscribe only to observed sensing; startup remains unknown/closed."""
        super().__init__('parking_manager')
        # A section 17 parameter; A section 7.1 default client TTL 30 s, accepted 5..120.
        self.declare_parameter('reservation_ttl_sec', 30.0)
        self.default_ttl = float(self.get_parameter('reservation_ttl_sec').value)
        if not math.isfinite(self.default_ttl) or not 5.0 <= self.default_ttl <= 120.0:
            raise ValueError('reservation_ttl_sec must be in [5, 120]')
        self.distances = entrance_distances(load_map())
        self.core = Parking(distances=self.distances)
        self.source = None
        self.entrance = None
        self.status = None
        self.entry_vehicle = None
        self.source_receipt = None
        self.last_barrier = None
        self.state = self.create_publisher(ParkingState, '/parking/state', QoSProfile(
            depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL))
        self.barrier = self.create_publisher(Bool, '/parking/barrier_request', 1)
        self.barrier_heartbeat = self.create_publisher(Bool, '/parking/barrier_heartbeat', 1)
        self.create_subscription(SlotObservationArray, '/parking/observed', self.observe, 10)
        self.create_subscription(Bool, '/parking/entrance_clear', self.entrance_cb, 1)
        self.create_subscription(Bool, '/parking/barrier_open', self.status_cb, 1)
        self.create_subscription(String, '/parking/entry_vehicle_id', self.entry_cb, 1)
        self.create_service(ResetScenario, '/parking/reset_state', self.reset)
        self.create_timer(.1, self.watchdog)
        self.create_service(ReserveParking, '/parking/reserve_slot', self.reserve)
        self.create_service(ReleaseParking, '/parking/release_slot', self.release)
        self.create_timer(.5, self.tick)

    def entry_cb(self, msg):
        """Bind barrier permission to the observed entrance vehicle identity."""
        self.entry_vehicle = (msg.data, time.monotonic())

    def reset(self, req, res):
        """Flush ownership and deduplication only under a fresh safety reset hold."""
        res.success = self.reset_allowed(req)
        res.reason = 'ACKNOWLEDGED' if res.success else 'SAFETY_HOLD_REQUIRED'
        if res.success:
            self.core = Parking(distances=self.distances)
            self.source = self.source_receipt = None
            self.entrance = self.entry_vehicle = self.status = None
            self.previous.clear()
            self.tick()
        return res

    def watchdog(self):
        """Publish stale transitions promptly and refresh the actuator command lease."""
        self.tick(publish_state=False)

    def entrance_cb(self, msg):
        """Track local receipt age for the unstamped entrance sensor."""
        self.entrance = (msg.data, time.monotonic())

    def status_cb(self, msg):
        """Retain observed acknowledgment separately from requested state."""
        if self.status is None or self.status[0] != msg.data:
            self.event('barrier', 'BARRIER_ACKNOWLEDGMENT', str(msg.data))
        self.status = (msg.data, time.monotonic())

    def now(self):
        """Use ROS time for reservation expiry and sensor acquisition age."""
        return self.get_clock().now().nanoseconds * 1e-9

    def observe(self, msg):
        """Reject repeated stamps, duplicate slots and low confidence sensing."""
        sample = (msg, time.monotonic())
        stamp = seconds(msg.header.stamp)
        if not fresh(self, sample) or self.source is not None and stamp <= self.source:
            return
        self.source = stamp
        self.source_receipt = time.monotonic()
        values = {}
        duplicates = set()
        for slot in msg.slots:
            if slot.slot_id in values:
                duplicates.add(slot.slot_id)
            values[slot.slot_id] = (
                slot.occupied if slot.valid and .5 <= slot.confidence <= 1 else None
            )
        for key in duplicates:
            values[key] = None
        self.core.observe(values, stamp)
        self.tick(publish_state=False)

    def reserve(self, req, res):
        """Return the cached service result for an identical retry."""
        result = self.core.reserve(req.request_id, req.vehicle_id, req.preferred_slot,
                                   req.ttl_sec or self.default_ttl, self.now())
        res.success, res.reservation_id, res.slot_id, expiry, res.reason = result
        set_stamp(res.expires_at, expiry)
        self.event(req.vehicle_id, 'PARKING_RESERVE', res.reason, req.request_id)
        self.tick(publish_state=False)
        return res

    def release(self, req, res):
        """Release matching live ownership only."""
        res.success, res.reason = self.core.release(
            req.request_id, req.reservation_id, req.vehicle_id, self.now())
        self.event(req.vehicle_id, 'PARKING_RELEASE', res.reason, req.request_id)
        self.tick(publish_state=False)
        return res

    def tick(self, publish_state=True):
        """Publish sensing-backed state; never treat barrier request as status."""
        if self.source_receipt is not None and time.monotonic() - self.source_receipt > 1:
            self.core.observe({}, self.now())
            self.source_receipt = None
        states = self.core.snapshot(self.now())
        changed = states != self.previous
        if changed:
            for key, value in states.items():
                if value != self.previous.get(key):
                    self.event(key, 'PARKING_STATE', value[0])
            self.previous = states
        msg = ParkingState()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.header.frame_id = 'map'
        for key, (state, owner) in states.items():
            slot = ParkingSlot(slot_id=key, state=state)
            if owner:
                slot.vehicle_id, slot.reservation_id, expiry = owner
                set_stamp(slot.expires_at, expiry)
            msg.slots.append(slot)
        msg.available_count = sum(state == 'FREE' for state, _ in states.values())
        if publish_state or changed:
            self.state.publish(msg)
        clear = self.entrance and self.entrance[0] and (
            time.monotonic() - self.entrance[1] <= .5)
        acknowledged = self.status and time.monotonic() - self.status[1] <= .5
        identity = self.entry_vehicle
        authorized = (identity and time.monotonic() - identity[1] <= .5 and
                      any(owner and owner[0] == identity[0] and state != 'UNKNOWN'
                          for state, owner in states.values()))
        requested = bool(clear and acknowledged and authorized)
        if requested != self.last_barrier:
            self.event('barrier', 'BARRIER_REQUEST', str(requested))
            self.last_barrier = requested
            self.barrier.publish(Bool(data=requested))
        self.barrier_heartbeat.publish(Bool(data=requested))


class TrafficMonitor(M4Node):
    """Publish measured edge state at the contracted two hertz."""

    def __init__(self):
        """Keep evaluator-only truth out of all control subscriptions."""
        super().__init__('traffic_monitor')
        # A section 17 parameter; A section 12.2 congestion at density >= 0.70.
        self.declare_parameter('congestion_density_threshold', 0.7)
        self.density_threshold = float(
            self.get_parameter('congestion_density_threshold').value)
        self.core = Traffic(load_map(), self.density_threshold)
        self.create_service(ResetScenario, '/traffic/reset_state', self.reset)
        self.output = self.create_publisher(EdgeStateArray, '/traffic/edges', 10)
        self.create_subscription(VehicleStateArray, '/hub/vehicles', self.observe, 10)
        self.create_timer(.5, self.tick)

    def reset(self, req, res):
        """Flush old road samples under the coordinated safety hold."""
        res.success = self.reset_allowed(req)
        res.reason = 'ACKNOWLEDGED' if res.success else 'SAFETY_HOLD_REQUIRED'
        if res.success:
            self.core = Traffic(load_map(), self.density_threshold)
            self.previous.clear()
            self.tick()
        return res

    def observe(self, msg):
        """Validate frame, receipt and source ages before recording observations."""
        if not fresh(self, (msg, time.monotonic())):
            return
        records = [(v.vehicle_id, v.edge_id, v.pose.x, v.pose.y, v.speed_mps,
                    v.kind, v.valid) for v in msg.vehicles]
        self.core.observe(records, seconds(msg.header.stamp),
                          self.get_clock().now().nanoseconds * 1e-9, time.monotonic())

    def tick(self):
        """Retain invalidity explicitly for stale edge states."""
        msg = EdgeStateArray()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.header.frame_id = 'map'
        states = self.core.snapshot(self.get_clock().now().nanoseconds * 1e-9,
                                    time.monotonic())
        for edge, (speed, density, blocked, valid, label) in states.items():
            if label != self.previous.get(edge):
                self.event(edge, 'TRAFFIC_STATE', json.dumps({
                    'label': label, 'speed': speed, 'density': density}))
                self.previous[edge] = label
            msg.edges.append(EdgeState(edge_id=edge, mean_speed_mps=speed,
                                       density_ratio=density, blocked=blocked, valid=valid))
        self.output.publish(msg)


def run(cls, args=None):
    """Run one adapter with explicit shutdown cleanup."""
    rclpy.init(args=args)
    node = cls()
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, rclpy.executors.ExternalShutdownException):
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


def parking_main(args=None):
    """Start the parking service adapter."""
    run(ParkingManager, args)


def traffic_main(args=None):
    """Start the traffic monitor adapter."""
    run(TrafficMonitor, args)
