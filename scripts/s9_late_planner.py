#!/usr/bin/env python3
"""Serve /route/compute like route_planner, but answer only after a fixed delay (T18)."""

import argparse
import time

import rclpy
from smart_hub_control.routing import RoutePlanner


class LatePlanner(RoutePlanner):
    """Compute the same routes as the real planner, then reply late on purpose."""

    def __init__(self, delay):
        """Keep the real planner's inputs; only the reply time changes."""
        super().__init__()
        self.delay = delay

    def compute(self, request, response):
        """Sleep past the client's 1 s timeout before returning a valid route."""
        time.sleep(self.delay)
        return super().compute(request, response)


def main():
    """Run until interrupted."""
    parser = argparse.ArgumentParser()
    parser.add_argument('--delay', type=float, default=1.5)
    args, ros_args = parser.parse_known_args()
    rclpy.init(args=ros_args)
    node = LatePlanner(args.delay)
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, rclpy.executors.ExternalShutdownException):
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()
