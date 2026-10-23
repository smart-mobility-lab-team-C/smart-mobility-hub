"""Verify independent barrier authority, expiry and passage-occupancy interlocks."""

from smart_hub_sim.barrier import Barrier


def test_barrier_requires_owner_safety_and_live_request():
    """A request alone, stale request or missing supervisor cannot open passage."""
    barrier = Barrier()
    assert not barrier.update(0, True, True, True)
    barrier.command(True, 1)
    assert not barrier.update(1, True, False, True)
    assert not barrier.update(1, True, True, False)
    assert barrier.update(1, True, True, True)
    assert not barrier.update(1.501, True, True, True)


def test_barrier_holds_occupied_passage_until_clear():
    """Loss of all control authority never closes onto a physical obstruction."""
    barrier = Barrier()
    barrier.command(True, 1)
    assert barrier.update(1, True, True, True)
    barrier.command(False, 1.1)
    assert barrier.update(2, False, False, False)
    assert not barrier.update(2.1, True, False, False)
    assert not barrier.update(2.2, False, True, True)
