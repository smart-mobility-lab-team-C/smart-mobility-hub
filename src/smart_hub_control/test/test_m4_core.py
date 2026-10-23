"""Exercise ownership races, sensor expiry and measured traffic boundaries."""

from concurrent.futures import ThreadPoolExecutor
import json
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
