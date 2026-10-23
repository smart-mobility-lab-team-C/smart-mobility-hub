"""ROS adapters for sensor-backed parking and traffic monitoring."""

import time

import rclpy
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile
from smart_hub_interfaces.msg import (
    EdgeState, EdgeStateArray, ParkingSlot, ParkingState,
    SlotObservationArray, VehicleStateArray,
)
from smart_hub_interfaces.srv import ReleaseParking, ReserveParking
from std_msgs.msg import Bool

from .parking import Parking
from .routing import fresh, load_map
from .traffic import Traffic


def seconds(stamp):
    """Convert ROS timestamps to seconds."""
    return stamp.sec + stamp.nanosec * 1e-9


def set_stamp(stamp, value):
    """Populate a nonnegative ROS timestamp."""
    stamp.sec = int(value)
    stamp.nanosec = int((value - int(value)) * 1e9)


class ParkingManager(Node):
    """Expose atomic reservation services and conservative barrier requests."""

    def __init__(self):
        """Subscribe only to observed sensing; startup remains unknown/closed."""
        super().__init__('parking_manager')
        self.core = Parking()
        self.source = None
        self.entrance = None
        self.status = None
        self.state = self.create_publisher(ParkingState, '/parking/state', QoSProfile(
            depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL))
        self.barrier = self.create_publisher(Bool, '/parking/barrier_request', 1)
        self.create_subscription(SlotObservationArray, '/parking/observed', self.observe, 10)
        self.create_subscription(Bool, '/parking/entrance_clear', self.entrance_cb, 1)
        self.create_subscription(Bool, '/parking/barrier_open', self.status_cb, 1)
        self.create_service(ReserveParking, '/parking/reserve_slot', self.reserve)
        self.create_service(ReleaseParking, '/parking/release_slot', self.release)
        self.create_timer(.5, self.tick)

    def entrance_cb(self, msg):
        """Track local receipt age for the unstamped entrance sensor."""
        self.entrance = (msg.data, time.monotonic())

    def status_cb(self, msg):
        """Retain observed acknowledgment separately from requested state."""
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
        self.tick()

    def reserve(self, req, res):
        """Return the cached service result for an identical retry."""
        result = self.core.reserve(req.request_id, req.vehicle_id, req.preferred_slot,
                                   req.ttl_sec, self.now())
        res.success, res.reservation_id, res.slot_id, expiry, res.reason = result
        set_stamp(res.expires_at, expiry)
        self.tick()
        return res

    def release(self, req, res):
        """Release matching live ownership only."""
        res.success, res.reason = self.core.release(
            req.request_id, req.reservation_id, req.vehicle_id, self.now())
        self.tick()
        return res

    def tick(self):
        """Publish sensing-backed state; never treat barrier request as status."""
        states = self.core.snapshot(self.now())
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
        self.state.publish(msg)
        clear = self.entrance and self.entrance[0] and (
            time.monotonic() - self.entrance[1] <= .5)
        acknowledged = self.status and time.monotonic() - self.status[1] <= .5
        authorized = any(owner for _, owner in states.values())
        self.barrier.publish(Bool(data=bool(clear and acknowledged and authorized)))


class TrafficMonitor(Node):
    """Publish measured edge state at the contracted two hertz."""

    def __init__(self):
        """Keep evaluator-only truth out of all control subscriptions."""
        super().__init__('traffic_monitor')
        self.core = Traffic(load_map())
        self.output = self.create_publisher(EdgeStateArray, '/traffic/edges', 10)
        self.create_subscription(VehicleStateArray, '/hub/vehicles', self.observe, 10)
        self.create_timer(.5, self.tick)

    def observe(self, msg):
        """Validate frame, receipt and source ages before recording observations."""
        if not fresh(self, (msg, time.monotonic())):
            return
        records = [(v.vehicle_id, v.edge_id, v.pose.x, v.pose.y, v.speed_mps,
                    v.kind, v.valid) for v in msg.vehicles]
        self.core.observe(records, seconds(msg.header.stamp),
                          self.get_clock().now().nanoseconds * 1e-9)

    def tick(self):
        """Retain invalidity explicitly for stale edge states."""
        msg = EdgeStateArray()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.header.frame_id = 'map'
        for edge, (speed, density, blocked, valid, _) in self.core.snapshot(
                self.get_clock().now().nanoseconds * 1e-9).items():
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
