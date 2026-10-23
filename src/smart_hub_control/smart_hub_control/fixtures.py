"""Explicit M3 synthetic road/bay inputs; not a production traffic monitor."""

import math

from rcl_interfaces.msg import SetParametersResult
import rclpy
from rclpy.node import Node
from smart_hub_interfaces.msg import EdgeState, EdgeStateArray
from std_msgs.msg import Bool

from .routing import load_map


class SyntheticRoads(Node):
    """Publish known synthetic edge snapshots at the contracted two hertz."""

    def __init__(self):
        """Keep fault settings test-only and leave operator E-stop external."""
        super().__init__('m3_synthetic_roads')
        self.declare_parameter('blocked_edges', [''])
        self.declare_parameter('bay_clear', True)
        self.declare_parameter('publish_edges', True)
        self.declare_parameter('freeze_edges', False)
        self.declare_parameter('density_ratio', 0.0)
        self.config = load_map()
        self.add_on_set_parameters_callback(self.validate_parameters)
        self.edges = self.create_publisher(EdgeStateArray, '/traffic/edges', 10)
        self.bay = self.create_publisher(Bool, '/sim/bay_clear', 1)
        self.frozen = None
        self.create_timer(0.5, self.tick)

    def validate_parameters(self, parameters):
        """Accept only bounded synthetic states; fault switches explicitly model loss."""
        known = {edge['id'] for edge in self.config['edges']} | {''}
        for parameter in parameters:
            if parameter.name == 'blocked_edges' and not set(parameter.value) <= known:
                return SetParametersResult(successful=False, reason='unknown edge')
            if parameter.name == 'density_ratio' and not (
                math.isfinite(parameter.value) and 0 <= parameter.value <= 1
            ):
                return SetParametersResult(successful=False, reason='invalid density')
        return SetParametersResult(successful=True)

    def tick(self):
        """Expose declared fixture state, including stale-feed faults for verification."""
        self.bay.publish(Bool(data=bool(self.get_parameter('bay_clear').value)))
        if not self.get_parameter('publish_edges').value:
            return
        msg = EdgeStateArray()
        stamp = self.get_clock().now().to_msg()
        if self.get_parameter('freeze_edges').value:
            if self.frozen is None:
                self.frozen = stamp
            stamp = self.frozen
        else:
            self.frozen = None
        msg.header.stamp = stamp
        msg.header.frame_id = 'map'
        blocked = self.get_parameter('blocked_edges').value
        density = float(self.get_parameter('density_ratio').value)
        for edge in self.config['edges']:
            msg.edges.append(
                EdgeState(
                    edge_id=edge['id'],
                    mean_speed_mps=0.4,
                    density_ratio=density,
                    blocked=edge['id'] in blocked,
                    valid=math.isfinite(density) and 0 <= density <= 1,
                )
            )
        self.edges.publish(msg)


def main(args=None):
    """Run the opt-in fixture source only in M3 synthetic bringup."""
    rclpy.init(args=args)
    node = SyntheticRoads()
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, rclpy.executors.ExternalShutdownException):
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
