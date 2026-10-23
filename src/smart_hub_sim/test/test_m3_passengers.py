"""Verify boarding slots, FIFO, interrupted capacity and seed reset."""

import pytest

from smart_hub_sim.passengers import PassengerQueue


@pytest.mark.parametrize('count', [0, 2, 4, 6])
def test_capacity_and_slots(count):
    """Preserve excess passengers and emit one individual timestamp per used slot."""
    queue = PassengerQueue(9, count)
    emitted = []
    for t in range(10):
        emitted += queue.tick(float(t), True, True, 'goal')
    assert len(emitted) == min(4, count)
    assert [e['boarding_sec'] for e in emitted] == [2.0, 4.0, 6.0, 8.0][:count]
    assert len(queue.waiting) == max(0, count - 4)
    assert len({e['passenger_id'] for e in emitted}) == len(emitted)


def test_arrivals_empty_slots_and_interruption():
    """New arrivals use future slots; interrupted openings never exceed goal capacity."""
    queue = PassengerQueue(11, 0, [3.0, 3.0, 7.0])
    events = []
    for t in range(9):
        events += queue.tick(t, True, True, 'goal')
    assert [e['boarding_sec'] for e in events] == [4, 6, 8]
    queue.tick(9, False, True, 'goal')
    queue.tick(10, True, True, 'goal')
    assert not queue.tick(12, True, False, 'goal')
    queue.reset(12)
    assert not queue.boarded and not queue.waiting and queue.seed == 12


def test_same_goal_capacity_survives_reopen():
    """Door cycling cannot board more than four passengers for one action."""
    queue = PassengerQueue(5, 8)
    for t in range(5):
        queue.tick(t, True, True, 'goal')
    queue.tick(5, False, True, 'goal')
    for t in range(6, 17):
        queue.tick(t, True, True, 'goal')
    assert len(queue.boarded) == 4
    assert len(queue.waiting) == 4
