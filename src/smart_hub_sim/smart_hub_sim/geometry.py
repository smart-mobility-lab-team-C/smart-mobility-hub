"""Footprint-aware geometry helpers for the M2 simulator."""

from __future__ import annotations

import math
from typing import Iterable, Sequence, Tuple


MAP_X = (0.0, 12.0)
MAP_Y = (0.0, 8.0)
CROSSING = (4.5, 5.5, 1.25, 4.75)


def segment_distance(
    px: float,
    py: float,
    ax: float,
    ay: float,
    bx: float,
    by: float,
) -> float:
    """Return the Euclidean distance from point P to segment AB."""
    dx = bx - ax
    dy = by - ay
    length_sq = dx * dx + dy * dy
    if length_sq == 0.0:
        return math.hypot(px - ax, py - ay)
    projection = ((px - ax) * dx + (py - ay) * dy) / length_sq
    projection = min(1.0, max(0.0, projection))
    return math.hypot(px - (ax + projection * dx), py - (ay + projection * dy))


def intersects_crossing(x: float, y: float, radius: float) -> bool:
    """Return whether a circular footprint intersects the crossing rectangle."""
    if radius < 0.0:
        raise ValueError('radius must be non-negative')
    left, right, bottom, top = CROSSING
    nearest_x = min(right, max(left, x))
    nearest_y = min(top, max(bottom, y))
    return math.hypot(x - nearest_x, y - nearest_y) <= radius + 1e-12


def _finite_point(point: Sequence[float]) -> bool:
    return len(point) == 2 and all(math.isfinite(value) for value in point)


def _point_segment_distance(
    point: Sequence[float], start: Sequence[float], end: Sequence[float]
) -> float:
    return segment_distance(point[0], point[1], start[0], start[1], end[0], end[1])


def _segments_distance(
    start_a: Sequence[float],
    end_a: Sequence[float],
    start_b: Sequence[float],
    end_b: Sequence[float],
) -> float:
    """Return minimum distance between two closed 2D segments."""
    # In 2D, non-parallel segments intersect when their orientation signs differ.
    ax, ay = start_a
    bx, by = end_a
    cx, cy = start_b
    dx, dy = end_b
    cross1 = (bx - ax) * (cy - ay) - (by - ay) * (cx - ax)
    cross2 = (bx - ax) * (dy - ay) - (by - ay) * (dx - ax)
    cross3 = (dx - cx) * (ay - cy) - (dy - cy) * (ax - cx)
    cross4 = (dx - cx) * (by - cy) - (dy - cy) * (bx - cx)
    if cross1 * cross2 <= 0.0 and cross3 * cross4 <= 0.0:
        # The orientation test above also overlaps collinear disjoint segments;
        # endpoint distances below handle that case without false zero results.
        if (
            min(ax, bx) <= max(cx, dx)
            and min(cx, dx) <= max(ax, bx)
            and min(ay, by) <= max(cy, dy)
            and min(cy, dy) <= max(ay, by)
        ):
            return 0.0
    return min(
        _point_segment_distance(start_a, start_b, end_b),
        _point_segment_distance(end_a, start_b, end_b),
        _point_segment_distance(start_b, start_a, end_a),
        _point_segment_distance(end_b, start_a, end_a),
    )


def swept_clear(
    start: Tuple[float, float],
    end: Tuple[float, float],
    radius: float,
    obstacles: Iterable[Tuple[float, float, float]],
    others: Iterable[Tuple[float, float, float]],
    clearance: float = 0.2,
) -> bool:
    """
    Check a circular footprint's swept path against the map and circles.

    Obstacles and other agents are circles described by ``(x, y, radius)``.
    Both footprint radii and the requested clearance are included in collision
    checks. Map bounds constrain the full radius, not only the centre point.
    """
    if not _finite_point(start) or not _finite_point(end):
        return False
    if not math.isfinite(radius) or not math.isfinite(clearance):
        return False
    if radius < 0.0 or clearance < 0.0:
        raise ValueError('radius and clearance must be non-negative')
    for point in (start, end):
        if not (
            MAP_X[0] + radius <= point[0] <= MAP_X[1] - radius
            and MAP_Y[0] + radius <= point[1] <= MAP_Y[1] - radius
        ):
            return False
    for circle in tuple(obstacles) + tuple(others):
        if len(circle) != 3 or not all(math.isfinite(value) for value in circle):
            return False
        ox, oy, other_radius = circle
        if other_radius < 0.0:
            return False
        if segment_distance(ox, oy, start[0], start[1], end[0], end[1]) <= (
            radius + other_radius + clearance + 1e-12
        ):
            return False
    return True


def swept_segments_clear(
    start_a: Sequence[float],
    end_a: Sequence[float],
    radius_a: float,
    start_b: Sequence[float],
    end_b: Sequence[float],
    radius_b: float,
    clearance: float = 0.2,
) -> bool:
    """Return whether two simultaneously swept circular footprints stay clear."""
    if not all(_finite_point(point) for point in (start_a, end_a, start_b, end_b)):
        return False
    if not all(math.isfinite(value) for value in (radius_a, radius_b, clearance)):
        return False
    if min(radius_a, radius_b, clearance) < 0.0:
        raise ValueError('radii and clearance must be non-negative')
    return _segments_distance(start_a, end_a, start_b, end_b) > (
        radius_a + radius_b + clearance + 1e-12
    )
