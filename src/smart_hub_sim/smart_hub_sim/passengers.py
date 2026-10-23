"""Seeded synthetic queue lifecycle; no perception or future online features."""

import math


class PassengerQueue:
    """Board at four fixed slots, retaining FIFO identities and interrupted history."""

    def __init__(self, seed, initial=6, arrivals=()):
        """Define explicit arrival times in elapsed simulation seconds."""
        if not isinstance(initial, int) or not 0 <= initial <= 1000:
            raise ValueError('initial_passengers must be an integer in [0,1000]')
        if any(not math.isfinite(t) or t < 0 for t in arrivals):
            raise ValueError('passenger arrival times must be finite and nonnegative')
        self.seed, self.initial, self.arrivals = seed, initial, sorted(arrivals)
        self.reset(seed)

    def reset(self, seed):
        """Restore the seeded queue without deleting external evidence."""
        self.seed = seed
        self.waiting = [(f'{seed}-p{i:04d}', 0.0) for i in range(self.initial)]
        self.next_id = self.initial
        self.arrival_index = 0
        self.open_since = None
        self.slot = 0
        self.boarded = []
        self.mission = ''
        self.boarded_this_goal = 0

    def tick(self, elapsed, door_open, safely_docked, goal_id):
        """Emit individual boarding events only at eligible open-door slots."""
        while (
            self.arrival_index < len(self.arrivals)
            and self.arrivals[self.arrival_index] <= elapsed
        ):
            at = self.arrivals[self.arrival_index]
            self.waiting.append((f'{self.seed}-p{self.next_id:04d}', at))
            self.next_id += 1
            self.arrival_index += 1
        if goal_id != self.mission:
            self.mission = goal_id
            self.boarded_this_goal = 0
            self.open_since = None
            self.slot = 0
        if not door_open or not safely_docked or not goal_id:
            self.open_since = None
            return []
        if self.open_since is None:
            self.open_since = elapsed
            self.slot = 0
        events = []
        while self.slot < 4 and elapsed - self.open_since + 1e-8 >= 2 * (self.slot + 1):
            self.slot += 1
            if self.waiting and self.boarded_this_goal < 4:
                identity, entered = self.waiting.pop(0)
                event = {
                    'passenger_id': identity,
                    'entry_sec': entered,
                    'boarding_sec': elapsed,
                    'goal_id': goal_id,
                    'slot': self.slot,
                }
                events.append(event)
                self.boarded.append(event)
                self.boarded_this_goal += 1
        return events
