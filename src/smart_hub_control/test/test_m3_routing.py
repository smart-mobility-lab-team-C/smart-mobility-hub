"""Exercise route permissions, failure states and independent cost comparison."""

import itertools
import math
import random
from types import SimpleNamespace

from smart_hub_control.routing import load_map, shortest_path


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
    assert math.isclose(cost, 10 / 0.4)
    states['Cs-J'].blocked = True
    path, cost, _ = shortest_path(config, states, 'A', 'E', 'car')
    assert math.isclose(cost, 14 / 0.4)
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
