"""Publish observed hub state as map-frame dashboard markers at five hertz."""

import math
import time

import rclpy
from rclpy.node import Node
from smart_hub_interfaces.msg import (
    CrossingState, DemandPrediction, QueueState, VehicleStateArray)
from visualization_msgs.msg import Marker, MarkerArray


class DashboardMarkers(Node):
    """Visualize observations without consuming evaluator-only ground truth."""

    def __init__(self):
        """Subscribe to public state and create the documented marker owner."""
        super().__init__('dashboard_marker_publisher')
        self.vehicles = self.queue = self.crossing = self.demand = None
        self.publisher = self.create_publisher(MarkerArray, '/hub/markers', 10)
        self.create_subscription(VehicleStateArray, '/hub/vehicles',
                                 lambda msg: self._receive('vehicles', msg), 10)
        self.create_subscription(QueueState, '/hub/queue',
                                 lambda msg: self._receive('queue', msg), 10)
        self.create_subscription(DemandPrediction, '/hub/demand',
                                 lambda msg: self._receive('demand', msg), 10)
        qos = rclpy.qos.QoSProfile(
            depth=1, durability=rclpy.qos.DurabilityPolicy.TRANSIENT_LOCAL)
        self.create_subscription(CrossingState, '/crossing/state',
                                 lambda msg: self._receive('crossing', msg), qos)
        self.create_timer(0.2, self.tick)

    def _receive(self, name, message):
        """Keep receipt time alongside the state acquisition stamp."""
        setattr(self, name, (message, time.monotonic()))

    def _fresh(self, sample, ttl):
        """Reject stale, future and non-map observations."""
        if sample is None:
            return False
        message, received = sample
        stamp = message.header.stamp.sec + message.header.stamp.nanosec * 1e-9
        age = self.get_clock().now().nanoseconds * 1e-9 - stamp
        return (message.header.frame_id == 'map' and 0 <= age <= ttl and
                time.monotonic() - received <= ttl)

    def _marker(self, identity, marker_type, x, y, scale, color, text=''):
        """Create one short-lived map marker from observed data."""
        marker = Marker()
        marker.header.stamp = self.get_clock().now().to_msg()
        marker.header.frame_id = 'map'
        marker.ns = 'hub'
        marker.id = identity
        marker.type = marker_type
        marker.action = Marker.ADD
        marker.pose.position.x = float(x)
        marker.pose.position.y = float(y)
        marker.pose.orientation.w = 1.0
        marker.scale.x = marker.scale.y = marker.scale.z = float(scale)
        marker.color.r, marker.color.g, marker.color.b, marker.color.a = color
        marker.text = text
        marker.lifetime.sec = 0
        marker.lifetime.nanosec = 400_000_000
        return marker

    def tick(self):
        """Publish one MarkerArray per timer tick, including an empty array."""
        output = MarkerArray()
        if self._fresh(self.vehicles, 1.0):
            for index, vehicle in enumerate(self.vehicles[0].vehicles):
                if (vehicle.valid and
                        all(math.isfinite(value) for value in
                            (vehicle.pose.x, vehicle.pose.y, vehicle.pose.theta))):
                    color = ((0.1, 0.2, 0.9, 0.9) if vehicle.kind == 'robot'
                             else (0.9, 0.2, 0.1, 0.9))
                    output.markers.append(self._marker(
                        index, Marker.CYLINDER, vehicle.pose.x, vehicle.pose.y,
                        0.35 if vehicle.kind == 'bus' else 0.25, color))
        if self._fresh(self.queue, 1.0):
            queue = self.queue[0]
            label = str(queue.count) if queue.valid else 'UNKNOWN'
            output.markers.append(self._marker(
                100, Marker.TEXT_VIEW_FACING, 4.0, 6.8, 0.35,
                (0.0, 0.0, 0.0, 1.0), 'Queue: ' + label))
        # A section 9.3 step 1: say so explicitly when no valid forecast is available.
        demand = self.demand[0] if self._fresh(self.demand, 1.5) else None
        if (demand is not None and demand.valid and demand.horizon_sec == 30 and
                math.isfinite(demand.predicted_count)):
            forecast = f'Forecast 30 s: {demand.predicted_count:.1f}'
        else:
            forecast = 'Prediction unavailable'
        output.markers.append(self._marker(
            102, Marker.TEXT_VIEW_FACING, 4.0, 6.3, 0.3, (0.0, 0.0, 0.0, 1.0), forecast))
        if self._fresh(self.crossing, 0.5):
            crossing = self.crossing[0]
            color = ((0.8, 0.1, 0.1, 0.4) if crossing.owner_id or
                     crossing.pedestrian_present else (0.1, 0.8, 0.1, 0.4))
            output.markers.append(self._marker(
                101, Marker.CUBE, 5.0, 3.0, 0.8, color))
        self.publisher.publish(output)


def main(args=None):
    """Run the dashboard marker publisher."""
    rclpy.init(args=args)
    node = DashboardMarkers()
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, rclpy.executors.ExternalShutdownException):
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
