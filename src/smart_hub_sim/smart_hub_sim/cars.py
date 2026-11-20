"""Scripted synthetic cars for the S8 integration fixture (A section 15.1 p21)."""

# A section 15.1 asks for synthetic cars spawned only on valid edges. These cars are
# kinematic stimuli, not controlled agents: they follow a declared node path at a
# constant speed and stop at its last node. They have no crossing client, so a path
# whose footprint could touch crossing C is rejected at load instead of being allowed
# to enter C without ownership.


import json
import math

from .geometry import CROSSING

CAR_SPEED_CAP = 0.35   # map_m1.yaml limits.car_speed_mps
CAR_RADIUS = 0.3       # map_m1.yaml footprint_radius_m.car
CLEARANCE = 0.2


def _touches_crossing(a, b, margin):
    """Conservatively test an axis-aligned segment against C inflated by margin."""
    x0, x1, y0, y1 = CROSSING
    return (min(a[0], b[0]) <= x1 + margin and max(a[0], b[0]) >= x0 - margin and
            min(a[1], b[1]) <= y1 + margin and max(a[1], b[1]) >= y0 - margin)


def parse_cars(text, config):
    """Validate a JSON list of {id, nodes, speed}; return {id: (points, edges, speed)}."""
    if not text.strip():
        return {}
    items = json.loads(text)
    if not isinstance(items, list):
        raise ValueError('synthetic_cars must be a JSON list')
    edges = {frozenset(edge['nodes']): edge for edge in config['edges']}
    cars = {}
    for item in items:
        ident, nodes, speed = item.get('id'), item.get('nodes'), item.get('speed', 0.35)
        if (not isinstance(ident, str) or not ident or ident in cars
                or ident in ('bus', 'robot', 'O')):
            raise ValueError(f'invalid or duplicate car id {ident!r}')
        if not isinstance(nodes, list) or not nodes or any(n not in config['nodes']
                                                           for n in nodes):
            raise ValueError(f'car {ident}: unknown node in path')
        if not isinstance(speed, (int, float)) or not 0 < speed <= CAR_SPEED_CAP:
            raise ValueError(f'car {ident}: speed must be in (0, {CAR_SPEED_CAP}]')
        points = [tuple(float(v) for v in config['nodes'][n]) for n in nodes]
        path_edges = []
        for a, b in zip(nodes, nodes[1:]):
            edge = edges.get(frozenset((a, b)))
            if edge is None or 'car' not in edge['agents']:
                raise ValueError(f'car {ident}: {a}-{b} is not a car edge')
            path_edges.append(edge['id'])
        if any(_touches_crossing(a, b, CAR_RADIUS + CLEARANCE)
               for a, b in zip(points, points[1:])) or (
                len(points) == 1 and _touches_crossing(points[0], points[0],
                                                       CAR_RADIUS + CLEARANCE)):
            raise ValueError(f'car {ident}: path would enter crossing C without ownership')
        if len(points) == 1:
            first = next((e['id'] for e in config['edges']
                          if nodes[0] in e['nodes'] and 'car' in e['agents']), '')
            if not first:
                raise ValueError(f'car {ident}: node {nodes[0]} has no car edge')
            path_edges = [first]
        cars[ident] = (points, path_edges, float(speed))
    return cars


class ScriptedCar:
    """Constant-speed motion along a validated polyline; stops at the last node."""

    def __init__(self, points, edges, speed):
        """Start at the first node of the path."""
        self.points, self.edges, self.speed = points, edges, speed
        self.segment = 0
        self.x, self.y = points[0]
        self.yaw = self._heading()
        self.linear_x = 0.0
        self.arrived = len(points) == 1

    def _heading(self):
        if len(self.points) < 2:
            return 0.0
        index = min(self.segment, len(self.points) - 2)
        a, b = self.points[index], self.points[index + 1]
        return math.atan2(b[1] - a[1], b[0] - a[0])

    @property
    def edge_id(self):
        """Return the map edge the car currently occupies."""
        return self.edges[min(self.segment, len(self.edges) - 1)]

    def step(self, dt):
        """Advance by speed * dt along the path, carrying distance across nodes."""
        if self.arrived:
            self.linear_x = 0.0
            return
        remaining = self.speed * dt
        while remaining > 0 and self.segment < len(self.points) - 1:
            target = self.points[self.segment + 1]
            distance = math.hypot(target[0] - self.x, target[1] - self.y)
            if distance <= remaining:
                self.x, self.y = target
                remaining -= distance
                if self.segment + 1 < len(self.points) - 1:
                    self.segment += 1
                    self.yaw = self._heading()
                else:
                    self.arrived = True
                    break
            else:
                self.x += (target[0] - self.x) * remaining / distance
                self.y += (target[1] - self.y) * remaining / distance
                remaining = 0.0
        self.linear_x = 0.0 if self.arrived else self.speed
