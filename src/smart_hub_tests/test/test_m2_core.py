"""Independent geometry checks for the M2 simulator and safety core."""

import math

from smart_hub_sim.geometry import (
    intersects_crossing,
    segment_distance,
    swept_clear,
)


def test_segment_distance_projects_onto_segment_and_handles_degenerate_segment():
    """Measure distance to the finite segment, including a zero-length segment."""
    assert math.isclose(segment_distance(2.0, 3.0, 0.0, 0.0, 4.0, 0.0), 3.0)
    assert math.isclose(segment_distance(5.0, 0.0, 0.0, 0.0, 4.0, 0.0), 1.0)
    assert math.isclose(segment_distance(3.0, 4.0, 1.0, 1.0, 1.0, 1.0), math.sqrt(13.0))


def test_crossing_occupancy_includes_the_full_agent_footprint():
    """A center outside C still intersects it when the circular footprint overlaps."""
    assert intersects_crossing(4.2, 3.0, 0.31)
    assert not intersects_crossing(4.19, 3.0, 0.30)
    assert intersects_crossing(5.0, 1.25, 0.0)


def test_swept_clear_enforces_map_bounds_for_the_full_footprint():
    """The whole swept footprint must fit inside the 12 m by 8 m map."""
    assert swept_clear((0.25, 1.0), (1.0, 1.0), 0.25, (), ())
    assert not swept_clear((0.24, 1.0), (1.0, 1.0), 0.25, (), ())
    assert not swept_clear((1.0, 1.0), (11.8, 1.0), 0.25, (), ())


def test_swept_clear_detects_obstacle_collision_and_added_clearance():
    """Swept distance checks include both footprint radii and configured clearance."""
    obstacle = ((5.0, 2.0, 0.3),)
    assert not swept_clear((1.0, 2.0), (9.0, 2.0), 0.2, obstacle, (), clearance=0.2)
    assert swept_clear((1.0, 2.8), (9.0, 2.8), 0.2, obstacle, (), clearance=0.2)


def test_swept_clear_prevents_tunneling_through_an_obstacle():
    """A fast step is checked along its segment, not only at its endpoints."""
    obstacle = ((6.0, 3.0, 0.35),)
    assert not swept_clear((2.0, 3.0), (10.0, 3.0), 0.3, obstacle, ())


def test_swept_clear_applies_clearance_to_other_agent_footprints():
    """Other agents participate in the same swept collision and clearance check."""
    other = ((5.0, 4.0, 0.3),)
    assert not swept_clear((1.0, 4.0), (9.0, 4.0), 0.2, (), other, clearance=0.2)
    assert swept_clear((1.0, 4.8), (9.0, 4.8), 0.2, (), other, clearance=0.2)
