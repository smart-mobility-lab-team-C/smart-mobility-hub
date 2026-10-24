"""Verify that a freeze cannot acquire one extra post-fault parking frame."""

from types import SimpleNamespace

from builtin_interfaces.msg import Time
import rclpy
from rclpy.parameter import Parameter
from smart_hub_sim.scenario_runner import ScenarioRunner


def test_freeze_preserves_the_last_acquisition_until_recovery():
    """Freeze between sensor ticks retains old stamps; recovery advances them."""
    rclpy.init(args=['--ros-args', '-p', 'm4_mode:=true'])
    node = ScenarioRunner()
    messages = []
    node._parking_pub = SimpleNamespace(publish=messages.append)
    try:
        before = node.get_clock().now().to_msg()
        node._publish_parking(before)
        next_tick = Time(sec=before.sec + 1, nanosec=before.nanosec)
        node.set_parameters([Parameter('freeze_parking', value=True)])
        node._publish_parking(next_tick)
        assert messages[-1].header.stamp == before
        assert messages[-1] is messages[0]
        node.set_parameters([Parameter('freeze_parking', value=False)])
        node._publish_parking(next_tick)
        assert messages[-1].header.stamp == next_tick
        assert messages[-1] is not messages[0]
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
