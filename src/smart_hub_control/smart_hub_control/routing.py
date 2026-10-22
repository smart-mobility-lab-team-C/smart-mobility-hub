"""Compute permitted routes from fresh, synchronized edge observations."""

import heapq
import json
import math
from pathlib import Path
import time

from ament_index_python.packages import get_package_share_directory
from geometry_msgs.msg import Point
from rcl_interfaces.msg import ParameterDescriptor
import rclpy
from rclpy.node import Node
from smart_hub_interfaces.msg import EdgeStateArray
from smart_hub_interfaces.srv import ComputeRoute


def load_map():
    """Load the source-traceable JSON-formatted YAML map installed by M1."""
    path = Path(get_package_share_directory('smart_hub_sim')) / 'config/map_m1.yaml'
    return json.loads(path.read_text())


def fresh(node, sample, ttl=1.0, frame='map'):
    """Require source and monotonic receipt age; repeated stamps still expire."""
    if sample is None:
        return False
    message, receipt = sample
    stamp = message.header.stamp.sec + message.header.stamp.nanosec * 1e-9
    age = node.get_clock().now().nanoseconds * 1e-9 - stamp
    return (
        message.header.frame_id == frame
        and 0 <= age <= ttl
        and (time.monotonic() - receipt <= ttl)
    )


def valid_edges(message, known):
    """Reject duplicate/unknown IDs and malformed synchronized snapshots."""
    edges = {}
    for edge in message.edges:
        if edge.edge_id not in known or edge.edge_id in edges:
            return {}
        if (
            not math.isfinite(edge.mean_speed_mps)
            or edge.mean_speed_mps < 0
            or not math.isfinite(edge.density_ratio)
            or not 0 <= edge.density_ratio <= 1
        ):
            return {}
        edges[edge.edge_id] = edge
    return edges


def shortest_path(config, observations, start, goal, agent, excluded=()):
    """Use nonnegative assignment costs and deterministic Dijkstra tie breaking."""
    if start not in config['nodes'] or goal not in config['nodes']:
        return [], 0.0, 'INVALID_NODE'
    if agent not in ('bus', 'robot', 'car'):
        return [], 0.0, 'INVALID_AGENT'
    known = {edge['id'] for edge in config['edges']}
    if not set(excluded) <= known:
        return [], 0.0, 'INVALID_EXCLUDED_EDGE'
    graph = {name: [] for name in config['nodes']}
    speed_cap = {'bus': 0.4, 'robot': 0.25, 'car': 0.4}[agent]
    for edge in config['edges']:
        state = observations.get(edge['id'])
        if (
            state is None
            or not state.valid
            or state.blocked
            or edge['id'] in excluded
            or agent not in edge['agents']
        ):
            continue
        a, b = edge['nodes']
        length = math.dist(config['nodes'][a], config['nodes'][b])
        # No credible crossing-wait estimate exists in M3: declared cost term is zero.
        cost = (
            length
            / max(min(state.mean_speed_mps, speed_cap), 0.05)
            * (1 + 2 * state.density_ratio)
        )
        graph[a].append((b, cost))
        graph[b].append((a, cost))
    pending = [(0.0, (start,))]
    distances = {start: 0.0}
    while pending:
        cost, path = heapq.heappop(pending)
        current = path[-1]
        if cost > distances[current]:
            continue
        if current == goal:
            return list(path), cost, 'OK'
        for neighbor, edge_cost in sorted(graph[current]):
            new_cost = cost + edge_cost
            if new_cost < distances.get(neighbor, math.inf):
                distances[neighbor] = new_cost
                heapq.heappush(pending, (new_cost, (*path, neighbor)))
    return [], 0.0, 'NO_ROUTE'


class RoutePlanner(Node):
    """Serve bounded computations without assuming unobserved roads are clear."""

    def __init__(self):
        """Subscribe to the exact M1 edge contract and expose ComputeRoute."""
        super().__init__('route_planner')
        self.config = load_map()
        self.declare_parameter('edge_freshness_sec', 1.0, ParameterDescriptor(read_only=True))
        self.ttl = float(self.get_parameter('edge_freshness_sec').value)
        if not math.isfinite(self.ttl) or not 0 < self.ttl <= 1.0:
            raise ValueError('edge_freshness_sec must be in (0, 1]')
        self.sample = None
        self.create_subscription(EdgeStateArray, '/traffic/edges', self.observe, 10)
        self.create_service(ComputeRoute, '/route/compute', self.compute)

    def observe(self, message):
        """Preserve the original acquisition stamp and receipt clock."""
        self.sample = (message, time.monotonic())

    def compute(self, request, response):
        """Return explicit failure and no waypoints for unavailable routes."""
        observations = {}
        if fresh(self, self.sample, self.ttl):
            observations = valid_edges(self.sample[0], {e['id'] for e in self.config['edges']})
        path, cost, reason = shortest_path(
            self.config,
            observations,
            request.start_node,
            request.goal_node,
            request.agent_type,
            request.excluded_edges,
        )
        response.success = bool(path)
        response.node_ids = path
        response.waypoints = [
            Point(x=float(self.config['nodes'][n][0]), y=float(self.config['nodes'][n][1]))
            for n in path
        ]
        response.estimated_cost_sec = float(cost)
        response.reason = reason
        return response


def main(args=None):
    """Run the route service with short single-threaded callbacks."""
    rclpy.init(args=args)
    node = RoutePlanner()
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, rclpy.executors.ExternalShutdownException):
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
