"""Exercise route permissions, failure states and independent cost comparison."""

import itertools
import math
import random
from types import SimpleNamespace

from smart_hub_control.bus import crossing_exit_clear, crossing_guard_radius, route_waypoints
from smart_hub_control.routing import load_map, shortest_path
from smart_hub_sim.geometry import intersects_crossing


def snapshots(config):
    """Supply explicit observed free-road states, never fallback defaults."""
    return {
        e['id']: SimpleNamespace(valid=True, blocked=False, mean_speed_mps=0.4, density_ratio=0.0)
        for e in config['edges']
    }


def test_routes_and_permissions():
    """Check baseline lengths, bus docking path, no route and robot-only exclusions."""
    config = load_map()
    states = snapshots(config)
    path, cost, _ = shortest_path(config, states, 'A', 'B', 'bus')
    assert path == ['A', 'N', 'Cn', 'B']
    assert math.isclose(cost, 9 / 0.4)
    path, cost, _ = shortest_path(config, states, 'A', 'E', 'car')
    assert math.isclose(cost, 10 / 0.35)
    states['Cs-J'].blocked = True
    path, cost, _ = shortest_path(config, states, 'A', 'E', 'car')
    assert math.isclose(cost, 14 / 0.35)
    states['B-Cn'].blocked = True
    assert shortest_path(config, states, 'A', 'E', 'bus')[2] == 'NO_ROUTE'
    assert shortest_path(config, {}, 'A', 'B', 'bus')[2] == 'NO_ROUTE'
    assert shortest_path(config, states, 'R', 'B', 'bus')[2] == 'NO_ROUTE'
    assert shortest_path(config, states, '?', 'B', 'bus')[2] == 'INVALID_NODE'
    assert shortest_path(config, states, 'A', 'B', 'plane')[2] == 'INVALID_AGENT'


def test_cost_against_independent_enumerator():
    """Compare varied bus routes to exhaustive paths; this is not ROS T11 acceptance."""
    config = load_map()
    rng = random.Random(301)
    nodes = list(config['nodes'])
    for _ in range(20):
        states = snapshots(config)
        for state in states.values():
            state.blocked = rng.random() < 0.2
            state.density_ratio = rng.random()
            state.mean_speed_mps = rng.uniform(0.01, 0.4)
        independent = {}
        for edge in config['edges']:
            state = states[edge['id']]
            if 'bus' in edge['agents'] and not state.blocked:
                a, b = edge['nodes']
                independent[frozenset((a, b))] = (
                    math.dist(config['nodes'][a], config['nodes'][b])
                    / max(state.mean_speed_mps, 0.05)
                    * (1 + 2 * state.density_ratio)
                )
        best = math.inf
        # Only eight road nodes are bus reachable.
        middle = [
            n for n in nodes if n not in ('A', 'B') and any(n in pair for pair in independent)
        ]
        for count in range(len(middle) + 1):
            for permutation in itertools.permutations(middle, count):
                path = ('A', *permutation, 'B')
                cost = sum(
                    independent.get(frozenset(pair), math.inf) for pair in zip(path, path[1:])
                )
                best = min(best, cost)
        path, cost, _ = shortest_path(config, states, 'A', 'B', 'bus')
        assert bool(path) == math.isfinite(best)
        if path:
            assert math.isclose(cost, best, rel_tol=1e-6)


def test_crossing_guard_covers_bus_motion_during_freshness_window():
    """Keep the bus outside the tested stop line through one freshness window."""
    radius = crossing_guard_radius(0.4)
    assert math.isclose(radius, 0.98)
    assert intersects_crossing(3.52, 4.0, radius)
    assert not intersects_crossing(3.51, 4.0, radius)


def test_crossing_ownership_is_retained_until_the_guard_is_cleared():
    """Do not release at the old exit mark while movement still needs ownership."""
    assert not crossing_exit_clear((4.0, 4.0, 0.0), 0.4)
    assert not crossing_exit_clear((6.1, 4.0, 0.0), 0.4)
    assert not crossing_exit_clear((6.48, 4.0, 0.0), 0.4)
    assert crossing_exit_clear((6.481, 4.0, 0.0), 0.4)


def test_mid_edge_replan_keeps_nearest_node_as_first_waypoint():
    """Continue through the nearest endpoint instead of reversing to its neighbor."""
    config = load_map()
    waypoints, approach_start = route_waypoints(config, ['Cn', 'B'], (4.6, 4.0, 0.0))
    assert waypoints == [(5.0, 4.0), (8.0, 4.0)]
    assert approach_start
    waypoints, approach_start = route_waypoints(config, ['B'], (8.0, 4.0, 0.0))
    assert waypoints == [(8.0, 4.0)]
    assert not approach_start


def test_freshness_boundary_and_invalid_snapshots(monkeypatch):
    """Distinguish source age from receipt age and reject invalid edge numeric data."""
    from smart_hub_control.routing import fresh, valid_edges
    import smart_hub_control.routing as routing

    now = 2.0
    monkeypatch.setattr(routing.time, 'monotonic', lambda: now)
    node = SimpleNamespace(
        get_clock=lambda: SimpleNamespace(now=lambda: SimpleNamespace(nanoseconds=int(now * 1e9)))
    )
    header = SimpleNamespace(frame_id='map', stamp=SimpleNamespace(sec=1, nanosec=0))
    msg = SimpleNamespace(header=header)
    assert fresh(node, (msg, 1.0))
    assert not fresh(node, (msg, 0.999))
    header.stamp.sec = 3
    assert not fresh(node, (msg, 2.0))
    header.stamp.sec = 0
    assert not fresh(node, (msg, 2.0))
    config = load_map()
    edge = snapshots(config)['A-N']
    edge.edge_id = 'A-N'
    assert valid_edges(SimpleNamespace(edges=[edge]), {'A-N'})
    assert not valid_edges(SimpleNamespace(edges=[edge, edge]), {'A-N'})
    edge.mean_speed_mps = float('nan')
    assert not valid_edges(SimpleNamespace(edges=[edge]), {'A-N'})


def test_remaining_crossing_wait_region():
    """Keep wait unknown before/across C, while allowing ETA once C is behind the bus."""
    from smart_hub_control.bus import route_needs_crossing

    assert route_needs_crossing([(1, 2), (1, 4), (8, 4)])
    assert route_needs_crossing([(3, 4), (8, 4)])
    assert route_needs_crossing([(5, 4), (8, 4)])
    assert not route_needs_crossing([(6.1, 4), (8, 4)])
    assert not route_needs_crossing([(11, 2), (11, 4), (8, 4)])
