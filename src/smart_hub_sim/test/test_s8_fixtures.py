"""Unit tests for the S8 vehicle-snapshot rule (D16) and scripted cars (D17)."""

import json
from pathlib import Path

import pytest
from smart_hub_interfaces.msg import VehicleState
from smart_hub_sim.cars import parse_cars, ScriptedCar
from smart_hub_sim.observations import other_circles, vehicle_snapshot

MAP = json.loads((Path(__file__).resolve().parents[1] / 'config/map_m1.yaml').read_text())


def record(ident, kind, x=1.0, y=2.0, valid=True, speed=0.0):
    """Build one observed vehicle record."""
    message = VehicleState(vehicle_id=ident, kind=kind, valid=valid, speed_mps=speed)
    message.pose.x, message.pose.y = x, y
    return message


def test_snapshot_requires_exactly_one_bus_and_robot():
    """Missing, duplicated or mislabelled agents make the whole snapshot invalid."""
    assert vehicle_snapshot([record('bus', 'bus'), record('robot', 'robot')]) is not None
    assert vehicle_snapshot([record('bus', 'bus')]) is None
    assert vehicle_snapshot([record('bus', 'bus'), record('robot', 'bus')]) is None
    assert vehicle_snapshot([record('bus', 'bus'), record('robot', 'robot'),
                             record('robot', 'robot')]) is None


def test_snapshot_accepts_cars_and_obstacles_but_rejects_unknown_kinds():
    """Cars and obstacles are allowed extras; anything else is UNKNOWN, not ignored."""
    base = [record('bus', 'bus'), record('robot', 'robot')]
    snapshot = vehicle_snapshot(base + [record('C1', 'car', 11, 3), record('O', 'obstacle', 7, 2)])
    assert set(snapshot) == {'bus', 'robot', 'C1', 'O'}
    assert other_circles(snapshot) == ((11.0, 3.0, 0.3), (7.0, 2.0, 0.35))
    assert vehicle_snapshot(base + [record('X', 'truck')]) is None
    assert vehicle_snapshot(base + [record('C1', 'car', valid=False)]) is None
    assert vehicle_snapshot(base + [record('C1', 'car', x=float('nan'))]) is None


def test_scripted_car_reaches_its_slot_at_the_declared_speed():
    """E-U-P3 is 4.5 m; at 0.35 m/s the car arrives after about 12.9 s and stops."""
    car = ScriptedCar(*parse_cars(json.dumps(
        [{'id': 'C1', 'nodes': ['E', 'U', 'P3'], 'speed': 0.35}]), MAP)['C1'])
    elapsed = 0.0
    while not car.arrived:
        assert car.edge_id in ('E-U', 'P3-U')
        car.step(0.05)
        elapsed += 0.05
    assert elapsed == pytest.approx(4.5 / 0.35, abs=0.06)
    assert (car.x, car.y, car.linear_x) == (11.0, 6.5, 0.0)


@pytest.mark.parametrize('cars, message', [
    ([{'id': 'C1', 'nodes': ['A', 'Cs']}], 'crossing C'),
    ([{'id': 'C1', 'nodes': ['E', 'P3']}], 'not a car edge'),
    ([{'id': 'C1', 'nodes': ['E', 'U'], 'speed': 0.5}], 'speed'),
    ([{'id': 'bus', 'nodes': ['E']}], 'car id'),
    ([{'id': 'C1', 'nodes': ['E']}, {'id': 'C1', 'nodes': ['U']}], 'car id'),
])
def test_invalid_car_scripts_are_rejected(cars, message):
    """Cars stay on car edges, under the speed cap, outside C, with unique ids."""
    with pytest.raises(ValueError, match=message):
        parse_cars(json.dumps(cars), MAP)
