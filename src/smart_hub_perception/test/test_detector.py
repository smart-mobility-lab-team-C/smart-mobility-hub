"""Check calibrated synthetic tracking semantics without a ROS graph."""

import math

from smart_hub_perception.detector import homography, project, Tracker


def test_four_point_calibration():
    """Map the four corners and an interior point into map metres."""
    image = [(0, 0), (159, 0), (159, 95), (0, 95)]
    ground = [(0, 8), (12, 8), (12, 0), (0, 0)]
    matrix = homography(image, ground)
    for point, expected in zip(image, ground):
        assert all(math.isclose(a, b, abs_tol=1e-9)
                   for a, b in zip(project(matrix, point), expected))
    assert math.isclose(project(matrix, (79.5, 47.5))[0], 6.0)


def test_debounce_and_occlusion_retention():
    """Count a stable identity once and keep it across a 0.3 s gap."""
    tracks = Tracker()
    assert tracks.update([(3.0, 6.0)], 0.0) == []
    assert tracks.occupancy(0.0) == (0, False)
    assert tracks.update([(3.0, 6.0)], 0.4)[0][0] == 'entry'
    assert tracks.occupancy(0.4) == (1, False)
    assert tracks.update([], 0.7) == []
    assert tracks.occupancy(0.7) == (1, False)
    assert tracks.update([(3.05, 6.0)], 0.8) == []
    assert tracks.tracks[0].identity == 0
    assert tracks.update([], 1.31)[0][0] == 'exit'
    assert tracks.occupancy(1.31) == (0, False)
