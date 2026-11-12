"""Shared validation of observed vehicle snapshots (A section 6 p8, section 15.1 p21)."""

# Every consumer of /hub/vehicles applies the same rule: exactly one valid bus and one
# valid robot, whose kind equals their identifier, plus any number of uniquely named
# valid cars or obstacles. Anything else makes the whole snapshot invalid, so a
# malformed record is UNKNOWN, never silently ignored.


import math

# Footprint radii from map_m1.yaml; the obstacle radius is the map obstacle O.
RADIUS = {'robot': 0.2, 'bus': 0.3, 'car': 0.3, 'obstacle': 0.35}
AGENTS = ('robot', 'bus')
OTHER_KINDS = ('car', 'obstacle')


def _finite(record):
    return all(math.isfinite(float(value)) for value in (
        record.pose.x, record.pose.y, record.pose.theta, record.speed_mps))


def vehicle_snapshot(records):
    """Return {vehicle_id: record} for a well-formed snapshot, otherwise None."""
    by_id = {}
    for record in records:
        if (not record.vehicle_id or record.vehicle_id in by_id or not record.valid
                or not _finite(record)):
            return None
        if record.vehicle_id in AGENTS:
            if record.kind != record.vehicle_id:
                return None
        elif record.kind not in OTHER_KINDS:
            return None
        by_id[record.vehicle_id] = record
    if not all(agent in by_id for agent in AGENTS):
        return None
    return by_id


def other_circles(by_id, kinds=OTHER_KINDS):
    """Return (x, y, radius) circles for non-agent records of the requested kinds."""
    return tuple((float(r.pose.x), float(r.pose.y), RADIUS[r.kind])
                 for key, r in sorted(by_id.items())
                 if key not in AGENTS and r.kind in kinds)
