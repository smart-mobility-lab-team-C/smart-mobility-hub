"""Capture evaluator-only door transitions around actual World mutations."""

import time


class DoorEvidence:
    """Bracket mutations while the caller holds the simulator's existing lock."""

    def __init__(self, clock=time.monotonic_ns):
        """Use same-host integer monotonic time, injectable for controlled schedules."""
        self.clock = clock
        self.sequence = 0

    def capture(self, world, run_id, goal_id, operation, mutate):
        """Return measured changes or explicit boundaries, never request acknowledgments."""
        previous = world.door_open
        before = self.clock()
        mutate()
        after = self.clock()
        measured = world.door_open
        if previous == measured and operation not in ('reset', 'goal_start', 'goal_end'):
            return None
        self.sequence += 1
        return {
            'schema': 'smart-mobility-hub/door-evidence-v1',
            'sequence': self.sequence,
            'run_id': run_id,
            'goal_id': goal_id,
            'operation': operation,
            'previous_open': previous,
            'door_open': measured,
            'before_ns': before,
            'after_ns': after,
        }
