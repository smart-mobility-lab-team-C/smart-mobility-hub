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
from smart_hub_interfaces.msg import CrossingState, EdgeStateArray
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


def crossing_edge(config, edge):
    """Identify edges whose line segment meets the C rectangle (map metres)."""
    a, b = (config['nodes'][name] for name in edge['nodes'])
    bounds = config['zones']['C']
    if a[0] == b[0]:
        return (bounds['x'][0] <= a[0] <= bounds['x'][1] and
                max(min(a[1], b[1]), bounds['y'][0]) <=
                min(max(a[1], b[1]), bounds['y'][1]))
    if a[1] == b[1]:
        return (bounds['y'][0] <= a[1] <= bounds['y'][1] and
                max(min(a[0], b[0]), bounds['x'][0]) <=
                min(max(a[0], b[0]), bounds['x'][1]))
    return False


def crossing_wait(state, agent):
    """
    Estimate wait from fresh arbitration state, without treating unknown as clear.

    This conservative static estimate uses the two-second clearance debounce and
    a one-second ownership lease. It is a planning cost, never motion permission.
    """
    if (state is None or not state.valid or
            state.state not in ('CLEAR', 'OWNED', 'OCCUPIED', 'HOLD')):
        return None
    if state.pedestrian_present or state.state in ('OCCUPIED', 'HOLD'):
        return 2.0
    if state.owner_id and state.owner_id != agent:
        return 1.0
    return 0.0


def shortest_path(config, observations, start, goal, agent, excluded=(), crossing=True):
    """Use nonnegative assignment costs and deterministic Dijkstra tie breaking."""
    if start not in config['nodes'] or goal not in config['nodes']:
        return [], 0.0, 'INVALID_NODE'
    if agent not in ('bus', 'robot', 'car'):
        return [], 0.0, 'INVALID_AGENT'
    known = {edge['id'] for edge in config['edges']}
    if not set(excluded) <= known:
        return [], 0.0, 'INVALID_EXCLUDED_EDGE'
    graph = {name: [] for name in config['nodes']}
    speed_cap = {'bus': 0.4, 'robot': 0.25, 'car': 0.35}[agent]
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
        wait = 0.0
        if crossing_edge(config, edge):
            wait = 0.0 if crossing is True else crossing_wait(crossing, agent)
            if wait is None:
                continue
        a, b = edge['nodes']
        length = math.dist(config['nodes'][a], config['nodes'][b])
        cost = (
            length
            / max(min(state.mean_speed_mps, speed_cap), 0.05)
            * (1 + 2 * state.density_ratio)
        ) + wait
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
        self.crossing_sample = None
        self.create_subscription(EdgeStateArray, '/traffic/edges', self.observe, 10)
        qos = rclpy.qos.QoSProfile(
            depth=1, durability=rclpy.qos.DurabilityPolicy.TRANSIENT_LOCAL)
        self.create_subscription(CrossingState, '/crossing/state',
                                 self.observe_crossing, qos)
        self.create_service(ComputeRoute, '/route/compute', self.compute)

    def observe(self, message):
        """Preserve the original acquisition stamp and receipt clock."""
        self.sample = (message, time.monotonic())

    def observe_crossing(self, message):
        """Retain acquisition and receipt ages for route eligibility."""
        self.crossing_sample = (message, time.monotonic())

    def compute(self, request, response):
        """Return explicit failure and no waypoints for unavailable routes."""
        observations = {}
        if fresh(self, self.sample, self.ttl):
            observations = valid_edges(self.sample[0], {e['id'] for e in self.config['edges']})
        crossing = (self.crossing_sample[0] if fresh(self, self.crossing_sample, 0.5)
                    else None)
        path, cost, reason = shortest_path(
            self.config,
            observations,
            request.start_node,
            request.goal_node,
            request.agent_type,
            request.excluded_edges,
            crossing,
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
