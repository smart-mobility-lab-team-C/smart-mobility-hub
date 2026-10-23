"""Exercise ownership races, sensor expiry and measured traffic boundaries."""

from concurrent.futures import ThreadPoolExecutor
import json
import math
from pathlib import Path
import threading

from smart_hub_control.parking import Parking
from smart_hub_control.traffic import Traffic


def empty_parking():
    """Establish stable readings before any allocation."""
    core = Parking()
    core.observe({'P1': True, 'P2': False, 'P3': False}, 0)
    core.observe({'P1': True, 'P2': False, 'P3': False}, .6)
    return core


def test_concurrent_pairs():
    """Twenty synchronized pairs never share a slot or ownership token."""
    for _ in range(20):
        core = empty_parking()
        gate = threading.Barrier(2)

        def reserve(vehicle):
            gate.wait()
            return core.reserve(vehicle, vehicle, 'P2', 30, .6)

        with ThreadPoolExecutor(2) as pool:
            a, b = list(pool.map(reserve, ['C1', 'C2']))
        assert a[0] and b[0] and a[2] != b[2] and a[1] != b[1]
        assert core.reserve('C1', 'C1', 'P2', 30, .7) == a
        assert not core.reserve('C1', 'C3', 'P2', 30, .7)[0]
        assert not core.reserve('new', 'C1', '', 30, .7)[0]


def test_expiry_release_and_invalid_ttl():
    """Expiry cannot fabricate vacancy; release requires matching live ownership."""
    core = empty_parking()
    a = core.reserve('a', 'C1', 'P2', 5, .6)
    assert not core.release('bad', 'wrong', 'C1', .7)[0]
    core.observe({'P2': True}, 1)
    core.observe({'P2': True}, 1.6)
    assert core.snapshot(1.6)['P2'][0] == 'OCCUPIED'
    assert core.snapshot(6)['P2'] == ('UNKNOWN', None)
    assert not core.release('old', a[1], 'C1', 6)[0]
    for ttl in (0, 4.9, 121, float('nan')):
        assert not core.reserve(str(ttl), 'C2', '', ttl, 6)[0]


def traffic():
    """Load the actual map without requiring ROS imports."""
    path = Path(__file__).parents[2] / 'smart_hub_sim/config/map_m1.yaml'
    return Traffic(json.loads(path.read_text()))


def test_traffic_freshness_geometry_and_free_flow():
    """Ten free-flow trials stay normal; frozen stamps expire and recover."""
    for _ in range(10):
        core = traffic()
        vehicle = ('C1', 'Cs-J', 6., 2., .35, 'car', True)
        assert core.observe([vehicle], 0, 0)
        assert core.snapshot(.5)['Cs-J'][4] == 'NORMAL'
        assert not core.observe([vehicle], 0, .9)
        assert core.snapshot(1.01)['Cs-J'][4] == 'UNKNOWN'
        assert core.observe([vehicle], 1.1, 1.1)
        assert core.snapshot(1.1)['Cs-J'][4] == 'NORMAL'
        invalid = ('C2', 'Cs-J', 6., 6., .35, 'car', True)
        assert not core.observe([invalid], 1.2, 1.2)
        assert core.observe([], 1.3, 1.3)
        assert core.snapshot(1.3)['Cs-J'][4] == 'NORMAL'


def test_traffic_congestion_and_obstruction():
    """Density triggers immediately and obstruction takes priority."""
    core = traffic()
    cars = [(str(i), 'Cs-J', 5.5 + i * .8, 2., .1, 'car', True)
            for i in range(4)]
    assert core.observe(cars, 0, 0)
    assert core.snapshot(0)['Cs-J'][4] == 'CONGESTED'
    obstacle = ('O', 'Cs-J', 7., 2., 0., 'obstacle', True)
    assert core.observe([obstacle], .1, .1)
    assert core.snapshot(.1)['Cs-J'][4] == 'BLOCKED'


def test_debounce_requires_multiple_samples_and_recovers_after_loss():
    """A single empty sample cannot become stable merely by waiting."""
    core = Parking()
    core.observe({'P2': False}, 0)
    assert core.snapshot(.8)['P2'][0] == 'UNKNOWN'
    core.observe({'P2': False}, .8)
    assert core.snapshot(.8)['P2'][0] == 'FREE'
    core.observe({'P2': False}, 2)
    assert core.snapshot(2)['P2'][0] == 'UNKNOWN'
    core.observe({'P2': False}, 2.6)
    assert core.snapshot(2.6)['P2'][0] == 'FREE'


def test_nearest_fallback_cache_bound_and_stale_token():
    """Bound request storage without evicting retry results or freeing a new owner."""
    core = empty_parking()
    a = core.reserve('a', 'C1', '', 5, .6)
    assert a[2] == 'P3'
    core.observe({'P3': False}, 5.2)
    core.observe({'P3': False}, 5.8)
    b = core.reserve('b', 'C2', 'P3', 5, 5.8)
    assert b[0] and b[2] == a[2]
    assert not core.release('old', a[1], 'C1', 5.9)[0]
    assert core.snapshot(5.9)['P3'][1][0] == 'C2'
    core.max_requests = len(core.requests)
    assert core.reserve('a', 'C1', '', 5, 6) == a
    assert core.reserve('extra', 'C3', '', 30, 6)[4] == 'REQUEST_CAPACITY_RESET_REQUIRED'


def test_traffic_monotonic_loss_and_noise_margin():
    """Frozen ROS time cannot defeat receipt watchdog; endpoint noise is bounded."""
    core = traffic()
    car = ('C1', 'Cs-J', 4.98, 2.02, .35, 'car', True)
    assert core.observe([car], 0, 0, receipt=100)
    assert core.snapshot(0, receipt=101.01)['Cs-J'][4] == 'UNKNOWN'
    invalid = ('C1', 'Cs-J', 4.9, 2., .35, 'car', True)
    assert not core.observe([invalid], .1, .1, receipt=101.1)
    overspeed = ('C1', 'Cs-J', 6., 2., 9., 'car', True)
    assert not core.observe([overspeed], .1, .1, receipt=101.1)


def test_slow_speed_uses_three_regular_publications_and_no_ghost_cars():
    """Watchdog evaluations do not accelerate congestion debounce."""
    core = traffic()
    car = ('C1', 'Cs-J', 6., 2., .1, 'car', True)
    assert core.observe([car], 0, 0)
    assert core.snapshot(0)['Cs-J'][4] == 'NORMAL'
    for t in (.1, .2, .3):
        assert core.snapshot(t, advance=False)['Cs-J'][4] == 'NORMAL'
    assert core.snapshot(.5)['Cs-J'][4] == 'NORMAL'
    assert core.observe([car], 1, 1)
    assert core.snapshot(1)['Cs-J'][4] == 'CONGESTED'
    assert core.observe([], 1.1, 1.1)
    assert core.snapshot(1.1)['Cs-J'][4] == 'NORMAL'


def test_invalid_source_cannot_make_its_road_empty_or_poison_healthy_edges():
    """An aggregator marks frozen individual sources invalid in the public array."""
    core = traffic()
    records = [('frozen', 'Cs-J', 6., 2., .35, 'car', False),
               ('healthy', 'Cn-N', 3., 4., .35, 'car', True)]
    assert not core.observe(records, 0, 0)
    assert core.snapshot(0)['Cs-J'][4] == 'UNKNOWN'
    assert core.snapshot(0)['Cn-N'][4] == 'NORMAL'
    assert core.observe([('frozen', 'Cs-J', 6., 2., .35, 'car', True)], .1, .1)
    assert core.snapshot(.1)['Cs-J'][4] == 'NORMAL'


def test_capacity_counts_footprints_and_headway_and_nearest_uses_graph():
    """Capacity fits centers within the edge; parking distance follows car permissions."""
    from smart_hub_control.parking import entrance_distances

    path = Path(__file__).parents[2] / 'smart_hub_sim/config/map_m1.yaml'
    config = json.loads(path.read_text())
    distances = entrance_distances(config)
    assert [distances[key] for key in ('P1', 'P2', 'P3')] == [5.5, 4., 2.5]
    core = Traffic(config)
    for a, b, capacity in core.edges.values():
        length = math.dist(a, b)
        assert (capacity - 1) * .8 + .6 <= length + 1e-6
        assert capacity * .8 + .6 > length - 1e-6
    config['limits']['car_min_headway_m'] = .1
    try:
        Traffic(config)
        assert False, 'unsafe headway accepted'
    except ValueError:
        pass


def test_known_obstruction_remains_blocked_when_other_source_is_invalid():
    """Fresh geometric obstruction takes precedence over unknown vehicle density."""
    core = traffic()
    records = [('frozen', 'Cs-J', 6., 2., .35, 'car', False),
               ('O', 'Cs-J', 7., 2., 0., 'obstacle', True)]
    assert not core.observe(records, 0, 0)
    state = core.snapshot(0)['Cs-J']
    assert state[2] and not state[3] and state[4] == 'BLOCKED'
    assert core.snapshot(.7)['Cs-J'][4] == 'UNKNOWN'
