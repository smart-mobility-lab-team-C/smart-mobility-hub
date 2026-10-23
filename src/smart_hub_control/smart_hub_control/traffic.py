"""Timestamped corridor-validated five-second traffic estimation."""

from collections import deque
import math
import statistics


class Traffic:
    """Keep acquisition time separate from publication and reject malformed frames."""

    def __init__(self, config):
        """Derive capacities using 0.80 m minimum center headway."""
        self.edges = {}
        for edge in config['edges']:
            a, b = (config['nodes'][key] for key in edge['nodes'])
            length = math.dist(a, b)
            self.edges[edge['id']] = (a, b, max(1, math.floor(length / 0.8)))
        self.history = deque()
        self.last_stamp = None
        self.receipt = None
        self.slow = {key: 0 for key in self.edges}

    def observe(self, vehicles, stamp, now):
        """Accept complete snapshots only with advancing, fresh acquisition time."""
        if (not math.isfinite(stamp) or not 0 <= now - stamp <= 1.0
                or self.last_stamp is not None and stamp <= self.last_stamp):
            return False
        records = {}
        seen = set()
        for vehicle in vehicles:
            ident, edge, x, y, speed, kind, valid = vehicle
            if (not valid or ident in seen or not ident or edge not in self.edges
                    or not all(math.isfinite(v) for v in (x, y, speed)) or speed < 0):
                return False
            seen.add(ident)
            a, b, _ = self.edges[edge]
            dx, dy = b[0] - a[0], b[1] - a[1]
            t = ((x - a[0]) * dx + (y - a[1]) * dy) / (dx * dx + dy * dy)
            distance = math.hypot(x - a[0] - t * dx, y - a[1] - t * dy)
            if not 0 <= t <= 1 or distance > 0.5:
                return False
            records[ident] = (edge, speed, kind)
        self.last_stamp, self.receipt = stamp, now
        self.history.append((stamp, records))
        return True

    def snapshot(self, now):
        """Return UNKNOWN on loss, immediate obstruction and sustained low speed."""
        while self.history and now - self.history[0][0] > 5:
            self.history.popleft()
        valid = (self.last_stamp is not None and 0 <= now - self.last_stamp <= 1
                 and 0 <= now - self.receipt <= 1)
        output = {}
        latest = self.history[-1][1] if self.history else {}
        for edge, (_, _, capacity) in self.edges.items():
            current = [v for v in latest.values() if v[0] == edge]
            speeds = [v[1] for _, records in self.history for v in records.values()
                      if v[0] == edge and v[2] != 'obstacle']
            speed = statistics.median(speeds) if speeds else 0.35
            density = min(1., sum(v[2] != 'obstacle' for v in current) / capacity)
            blocked = valid and any(v[2] == 'obstacle' for v in current)
            self.slow[edge] = self.slow[edge] + 1 if valid and speeds and speed < .14 else 0
            label = ('UNKNOWN' if not valid else 'BLOCKED' if blocked else
                     'CONGESTED' if density >= .7 or self.slow[edge] >= 3 else 'NORMAL')
            output[edge] = (speed, density, blocked, valid, label)
        return output
