"""Timestamped corridor-validated five-second traffic estimation."""

from collections import deque
import math
import statistics


class Traffic:
    """Keep acquisition time separate from publication and reject malformed frames."""

    def __init__(self, config):
        """Fit car footprints along usable edge length with declared center headway."""
        limits = config.get('limits', {})
        self.free_flow = limits.get('car_speed_mps', .35)
        headway = limits.get('car_min_headway_m', .8)
        radius = config.get('footprint_radius_m', {}).get('car', .3)
        if (not all(math.isfinite(v) for v in (self.free_flow, headway, radius))
                or not 0 < self.free_flow <= .35 or headway < .8 or radius <= 0):
            raise ValueError('invalid car speed, headway or footprint')
        self.edges = {}
        self.allowed = {}
        for edge in config['edges']:
            a, b = (config['nodes'][key] for key in edge['nodes'])
            length = math.dist(a, b)
            usable = max(0., length - 2 * radius)
            capacity = max(1, math.floor(usable / headway) + 1)
            self.edges[edge['id']] = (a, b, capacity)
            self.allowed[edge['id']] = set(edge['agents']) | {'obstacle'}
        self.history = deque()
        self.last_stamp = None
        self.receipt = None
        self.slow = {key: 0 for key in self.edges}

    def observe(self, vehicles, stamp, now, receipt=None):
        """Accept complete snapshots only with advancing, fresh acquisition time."""
        if (not math.isfinite(stamp) or not 0 <= now - stamp <= 1.0
                or self.last_stamp is not None and stamp <= self.last_stamp):
            return False
        records = {}
        seen = set()
        invalid_edges = set()
        caps = {'car': self.free_flow, 'bus': .4, 'robot': .25, 'obstacle': 0}
        for vehicle in vehicles:
            ident, edge, x, y, speed, kind, valid = vehicle
            if edge not in self.edges:
                invalid_edges.update(self.edges)
                continue
            if (not valid or not ident or kind not in caps or kind not in self.allowed[edge]
                    or not all(math.isfinite(v) for v in (x, y, speed))
                    or not 0 <= speed <= caps.get(kind, 0) + 1e-6):
                invalid_edges.add(edge)
                if self.history and ident in self.history[-1][1]:
                    invalid_edges.add(self.history[-1][1][ident][0])
                continue
            if ident in seen:
                invalid_edges.update(self.edges)
                continue
            seen.add(ident)
            a, b, _ = self.edges[edge]
            dx, dy = b[0] - a[0], b[1] - a[1]
            t = ((x - a[0]) * dx + (y - a[1]) * dy) / (dx * dx + dy * dy)
            distance = math.hypot(x - a[0] - t * dx, y - a[1] - t * dy)
            margin = .03 / math.dist(a, b)
            if not -margin <= t <= 1 + margin or distance > 0.5:
                invalid_edges.add(edge)
                if self.history and ident in self.history[-1][1]:
                    invalid_edges.add(self.history[-1][1][ident][0])
                continue
            records[ident] = (edge, speed, kind)
        self.last_stamp = stamp
        self.receipt = now if receipt is None else receipt
        self.history.append((stamp, records, invalid_edges))
        return not invalid_edges

    def snapshot(self, now, receipt=None, advance=True):
        """Return UNKNOWN on loss, immediate obstruction and sustained low speed."""
        while self.history and now - self.history[0][0] > 5:
            self.history.popleft()
        receipt = now if receipt is None else receipt
        frame_valid = (self.last_stamp is not None and 0 <= now - self.last_stamp <= .65
                       and 0 <= receipt - self.receipt <= .65)
        output = {}
        latest = self.history[-1][1] if self.history else {}
        invalid_edges = self.history[-1][2] if self.history else set(self.edges)
        for edge, (_, _, capacity) in self.edges.items():
            valid = frame_valid and edge not in invalid_edges
            current = [v for v in latest.values() if v[0] == edge]
            current_ids = {key for key, v in latest.items() if v[0] == edge}
            speeds = [v[1] for _, records, _ in self.history for key, v in records.items()
                      if key in current_ids and v[0] == edge and v[2] != 'obstacle']
            speed = statistics.median(speeds) if speeds else self.free_flow
            density = min(1., sum(v[2] != 'obstacle' for v in current) / capacity)
            blocked = frame_valid and any(v[2] == 'obstacle' for v in current)
            if advance:
                self.slow[edge] = (self.slow[edge] + 1
                                   if valid and speeds and speed < .4 * self.free_flow else 0)
            label = ('BLOCKED' if blocked else 'UNKNOWN' if not valid else
                     'CONGESTED' if density >= .7 or self.slow[edge] >= 3 else 'NORMAL')
            output[edge] = (speed, density, blocked, valid, label)
        return output
