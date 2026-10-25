"""Exercise production callbacks with real World state and independent schedules."""

from copy import deepcopy
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import rclpy
from rosidl_runtime_py.convert import message_to_ordereddict
from smart_hub_interfaces.msg import CrossingState, SafetyState
from smart_hub_interfaces.srv import ResetScenario
from smart_hub_sim.scenario_runner import ScenarioRunner
from smart_hub_sim.world import AgentState
from std_msgs.msg import Bool, String

spec = importlib.util.spec_from_file_location(
    'door_duration', Path(__file__).resolve().parents[3] / 'scripts/door_duration.py')
duration = importlib.util.module_from_spec(spec)
spec.loader.exec_module(duration)
BASE = 8_000_000_000_000_000_000
OPEN = BASE + 1_000_000_000


@pytest.fixture
def harness():
    """Use real callbacks, asserting capture under lock and publication afterward."""
    rclpy.init(args=[])
    node = ScenarioRunner()
    node.world.bus = AgentState(8.0, 4.0, 0.0)
    events = []
    bounds = iter(())

    def clock():
        assert node._lock._is_owned()
        return next(bounds)

    def publish(event):
        assert not node._lock._is_owned()
        events.append(message_to_ordereddict(event))

    def at(instant, callback, width=0):
        nonlocal bounds
        bounds = iter((instant - width, instant + width))
        callback()
        assert next(bounds, None) is None, 'mutation did not use both clock bounds'

    node._door_evidence.clock = clock
    node._boarding_pub = SimpleNamespace(publish=publish)
    try:
        yield node, events, at
    finally:
        node.destroy_node()
        rclpy.shutdown()


def mission(harness, dwell_ns, width=0, nominal=True):
    """Script mutations at explicit instants, independently of generated evidence."""
    node, events, at = harness
    run_id = node._run_id
    at(BASE, lambda: node._goal_id(String(data='goal')))
    at(OPEN, lambda: node._door_request(Bool(data=True)), width)
    assert node.world.door_open
    at(OPEN + dwell_ns, lambda: node._door_request(Bool(data=False)), width)
    assert not node.world.door_open
    at(OPEN + dwell_ns + 100, lambda: node._goal_id(String(data='')))
    return duration.assess_source(events, run_id, 'goal', nominal)


@pytest.mark.parametrize('dwell_ns,expected', [
    (8_000_000_000, 'PASS'), (8_100_000_000, 'PASS'),
    (7_900_000_000, 'FAIL'), (7_999_999_999, 'FAIL'), (8_000_000_001, 'PASS'),
])
def test_scripted_actual_duration_and_exact_nanosecond_boundary(harness, dwell_ns, expected):
    """The expected duration comes from the mutation schedule, never event payloads."""
    observed = mission(harness, dwell_ns)
    assert observed['minimum_ns'] == observed['maximum_ns'] == dwell_ns
    assert observed['status'] == expected


@pytest.mark.parametrize('dwell_ns,receipt_end,source_status,receipt_status', [
    (7_900_000_000, 108.1, 'FAIL', 'PASS'),
    (8_100_000_000, 107.9, 'PASS', 'FAIL'),
])
def test_observer_delay_cannot_change_source_result(
        harness, dwell_ns, receipt_end, source_status, receipt_status):
    """Delayed/reversed observer estimates retain discrepancies without overriding truth."""
    observed = mission(harness, dwell_ns)
    receipt = duration.assess_receipts(100.0, receipt_end, observed)
    assert observed['status'] == source_status
    assert receipt['status'] == receipt_status
    assert receipt['disagrees_with_source']


@pytest.mark.parametrize('dwell_ns,width,expected', [
    (8_000_000_000, 1, 'BLOCKED'), (8_000_000_002, 1, 'PASS'),
    (7_999_999_997, 1, 'FAIL'), (7_999_999_998, 1, 'BLOCKED'),
])
def test_conservative_bounds_at_exact_boundary(harness, dwell_ns, width, expected):
    """Subtract opposite bracket endpoints with no float conversion or tolerance."""
    observed = mission(harness, dwell_ns, width)
    assert observed['minimum_ns'] == dwell_ns - 2 * width
    assert observed['maximum_ns'] == dwell_ns + 2 * width
    assert observed['status'] == expected


def test_rejected_request_is_not_a_measured_opening(harness):
    """An undocked real World rejects opening despite receiving a true request."""
    node, events, at = harness
    node.world.bus = AgentState(1.0, 2.0, 0.0)
    at(BASE, lambda: node._goal_id(String(data='goal')))
    at(OPEN, lambda: node._door_request(Bool(data=True)))
    assert node.world.door_request and not node.world.door_open
    at(OPEN + 9_000_000_000, lambda: node._goal_id(String(data='')))
    assert len(events) == 2
    assert duration.assess_source(events, node._run_id, 'goal', True)['status'] == 'BLOCKED'


def test_physics_opening_and_protective_closure_are_measured(harness):
    """Actual physics can satisfy or break the computed door interlock."""
    node, events, at = harness
    node.world.bus.linear_x = 0.1
    at(BASE, lambda: node._goal_id(String(data='goal')))
    at(OPEN - 100, lambda: node._door_request(Bool(data=True)))
    assert not node.world.door_open
    at(OPEN, node._step)
    assert node.world.door_open
    node._active_command = lambda agent, now: (0.1, 0.0) if agent == 'bus' else (0.0, 0.0)
    at(OPEN + 7_900_000_000, node._step)
    assert not node.world.door_open
    at(OPEN + 7_900_000_100, lambda: node._goal_id(String(data='')))
    observed = duration.assess_source(events, node._run_id, 'goal', False)
    assert observed['duration_status'] == 'FAIL' and observed['status'] == 'BLOCKED'
    assert [json.loads(e['reason'])['operation'] for e in events] == [
        'goal_start', 'physics', 'physics', 'goal_end']


def test_cancellation_closes_early_without_nominal_success(harness):
    """A cancellation close request remains a short interval and an interruption."""
    observed = mission(harness, 7_900_000_000, nominal=False)
    assert observed['duration_status'] == 'FAIL'
    assert observed['status'] == 'BLOCKED'
    assert 'interruption' in observed['reason']


@pytest.mark.parametrize('open_first', [False, True])
def test_actual_reset_records_old_identity_and_blocks_acceptance(harness, open_first):
    """Real reset callback retains the invalidated run/goal even without a transition."""
    node, events, at = harness
    old_run = node._run_id
    at(BASE, lambda: node._goal_id(String(data='goal')))
    if open_first:
        at(OPEN, lambda: node._door_request(Bool(data=True)))
    safety = SafetyState(reason='reset_in_progress')
    safety.header.frame_id = 'map'
    safety.header.stamp = node._stamp()
    crossing = CrossingState(valid=True)
    crossing.header.frame_id = 'map'
    crossing.header.stamp = node._stamp()
    node._safety_state(safety)
    node._crossing_state(crossing)
    response = ResetScenario.Response()
    at(OPEN + 7_900_000_000, lambda: node._reset_scenario(
        ResetScenario.Request(scenario_id='m2_baseline', seed=304), response))
    assert response.success and node._run_id != old_run and not node.world.door_open
    reset = json.loads(events[-1]['reason'])
    assert reset['operation'] == 'reset'
    assert reset['run_id'] == old_run and reset['goal_id'] == 'goal'
    assert reset['previous_open'] is open_first and reset['door_open'] is False
    assert duration.assess_source(events, old_run, 'goal', True)['status'] == 'BLOCKED'


@pytest.mark.parametrize('fault', [
    'missing_open', 'missing_close', 'missing_start', 'missing_end', 'sequence_gap',
    'wrong_run', 'wrong_goal', 'identity_mismatch', 'reversed_bounds', 'float_time',
    'out_of_order', 'duplicate', 'state_discontinuity', 'malformed', 'extra_interval',
])
def test_incomplete_or_uncertain_evidence_blocks_acceptance(harness, fault):
    """Corrupt complete evidence to ensure that loss or identity errors fail closed."""
    node, events, _ = harness
    assert mission(harness, 8_100_000_000)['status'] == 'PASS'
    damaged = deepcopy(events)
    if fault.startswith('missing_'):
        damaged.pop({'start': 0, 'open': 1, 'close': 2, 'end': 3}[fault[8:]])
    elif fault == 'out_of_order':
        damaged[1], damaged[2] = damaged[2], damaged[1]
    elif fault in ('duplicate', 'extra_interval'):
        damaged.insert(2, deepcopy(damaged[1]))
    elif fault == 'malformed':
        damaged[1]['reason'] = 'invalid json'
    else:
        record = json.loads(damaged[1]['reason'])
        if fault == 'sequence_gap':
            record['sequence'] += 1
        elif fault == 'wrong_run':
            record['run_id'] = damaged[1]['run_id'] = 'wrong'
        elif fault == 'wrong_goal':
            record['goal_id'] = damaged[1]['correlation_id'] = 'wrong'
        elif fault == 'identity_mismatch':
            record['goal_id'] = 'wrong'
        elif fault == 'reversed_bounds':
            record['before_ns'] = record['after_ns'] + 1
        elif fault == 'float_time':
            record['before_ns'] = float(record['before_ns'])
        elif fault == 'state_discontinuity':
            record['previous_open'] = True
        damaged[1]['reason'] = json.dumps(record)
    assert duration.assess_source(damaged, node._run_id, 'goal', True)['status'] == 'BLOCKED'
