"""Pure checks for robot routing, crossing guard, progress and waypoint helpers."""

import math
from types import SimpleNamespace

from smart_hub_control.bus import route_needs_crossing, route_waypoints
from smart_hub_control.robot import (
    axis_heading,
    crossing_exit_clear,
    crossing_guard_radius,
    mission_progress,
    path_length,
    route_cost,
    route_uses_permitted_edges,
    should_replace,
)
from smart_hub_control.routing import load_map, shortest_path
from smart_hub_sim.geometry import intersects_crossing


def snapshots(config):
    """Explicit observed free-road states for every edge."""
    return {
        e['id']: SimpleNamespace(valid=True, blocked=False, mean_speed_mps=0.25,
                                 density_ratio=0.0)
        for e in config['edges']
    }


def test_escort_route_and_detour():
    """R to D uses robot links; blocking Cs-J forces the upper detour; both blocked fail."""
    config = load_map()
    states = snapshots(config)
    path, _, _ = shortest_path(config, states, 'R', 'D', 'robot')
    assert path == ['R', 'W', 'Cn', 'Cs', 'J', 'D']
    assert math.isclose(path_length([config['nodes'][n] for n in path]), 11.0)
    states['Cs-J'].blocked = True
    path, _, _ = shortest_path(config, states, 'Cn', 'D', 'robot')
    assert path == ['Cn', 'B', 'U', 'E', 'J', 'D']
    states['B-Cn'].blocked = True
    assert shortest_path(config, states, 'R', 'D', 'robot')[2] == 'NO_ROUTE'
    assert shortest_path(config, snapshots(config), 'R', 'P1', 'robot')[2] == 'NO_ROUTE'


def test_route_permissions():
    """Bus-only and car-only edges are rejected for the robot."""
    config = load_map()
    assert route_uses_permitted_edges(config, ['R', 'W', 'Cn', 'Cs', 'J', 'D'])
    assert not route_uses_permitted_edges(config, ['A', 'Cs', 'J'])
    assert not route_uses_permitted_edges(config, ['U', 'P3'])
    assert not route_uses_permitted_edges(config, ['R', 'X'])
    assert not route_uses_permitted_edges(config, [])


def test_crossing_guard_and_release():
    """Ownership is needed on W-Cn before C; release only east of the guarded area."""
    radius = crossing_guard_radius(0.25)
    assert math.isclose(radius, 0.46 + 0.25 * 1.05)
    assert not intersects_crossing(5.0, 6.0, radius)
    assert intersects_crossing(5.0, 4.75 + radius - 0.01, radius)
    assert not crossing_exit_clear((5.0, 2.0, 0.0), 0.25)
    assert not crossing_exit_clear((5.9, 2.0, 0.0), 0.25)
    assert crossing_exit_clear((5.5 + radius + 0.01, 2.0, 0.0), 0.25)
    config = load_map()
    points = [config['nodes'][n] for n in ('W', 'Cn', 'Cs', 'J', 'D')]
    assert route_needs_crossing([(3.0, 6.0), *points])
    assert not route_needs_crossing([(9.0, 2.0), (9.0, 1.0)])


def test_waypoints_and_progress():
    """Turn nodes are kept; progress is bounded and falls when a detour adds distance."""
    config = load_map()
    waypoints, approach = route_waypoints(config, ['R', 'W', 'Cn', 'Cs', 'J', 'D'],
                                          (3.0, 6.0, 0.0))
    assert not approach
    assert waypoints == [(5, 6), (5, 2), (9, 2), (9, 1)]
    assert mission_progress(0.0, 0.0) == 1.0
    assert mission_progress(5.5, 5.5) == 0.5
    assert mission_progress(6.0, 9.0) < mission_progress(6.0, 5.0)
    assert 0.0 <= mission_progress(1e9, 0.0) <= 1.0


def test_axis_heading_near_node():
    """A residual horizontal offset at W must not turn the robot north (regression)."""
    assert axis_heading((4.9999991, 6.0, 0.0), (5.0, 6.0)) == 0.0
    assert axis_heading((5.0000004, 6.0, 0.0), (5.0, 6.0)) == math.pi
    assert axis_heading((5.0, 6.0, 0.0), (5.0, 2.0)) == -math.pi / 2
    assert axis_heading((5.0, 2.0, 0.0), (9.0, 2.0)) == 0.0
    assert axis_heading((9.0, 2.0, 0.0), (9.0, 1.0)) == -math.pi / 2


def test_congestion_replan_rule():
    """A section 13.2: replace only when at least 15% cheaper; blocked edges have no cost."""
    config = load_map()
    states = snapshots(config)
    base = route_cost(config, states, ['R', 'W', 'Cn', 'Cs', 'J', 'D'])
    assert math.isclose(base, 11 / 0.25)
    states['Cs-J'].density_ratio = 1.0
    congested = route_cost(config, states, ['R', 'W', 'Cn', 'Cs', 'J', 'D'])
    detour = route_cost(config, states, ['R', 'W', 'Cn', 'B', 'U', 'E', 'J', 'D'])
    assert should_replace(congested, detour, 0.15)
    assert not should_replace(100.0, 86.0, 0.15)
    assert should_replace(100.0, 85.0, 0.15)
    states['Cs-J'].blocked = True
    assert route_cost(config, states, ['Cs', 'J']) is None
    assert not should_replace(None, 10.0, 0.15)
