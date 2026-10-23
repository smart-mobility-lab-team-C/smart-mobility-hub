"""Independent parking actuator interlock with request and owner watchdogs."""


class Barrier:
    """Hold an occupied passage; opening requires independently checked authority."""

    def __init__(self):
        """Start physically closed, without a command lease."""
        self.open = False
        self.request = (False, float('-inf'))

    def command(self, requested, now):
        """Record a request without treating it as measured opening."""
        self.request = (bool(requested), now)

    def update(self, now, passage_clear, owner_valid, safety_ready):
        """Expire commands independently and never close onto an occupied passage."""
        allowed = (self.request[0] and 0 <= now - self.request[1] <= .5
                   and owner_valid and safety_ready)
        if passage_clear:
            self.open = bool(allowed)
        return self.open
