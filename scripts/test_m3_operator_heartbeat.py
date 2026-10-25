#!/usr/bin/env python3
"""Check M3 operator state precedence for stop, resume and parent loss."""

import os
import unittest

from m3_operator_heartbeat import operator_state, read_process_state


class OperatorStateTest(unittest.TestCase):
    """Keep parent faults dominant until an explicit clear command."""

    def test_parent_suspension_stops_and_resume_does_not_clear(self):
        value, exited = operator_state(False, 'T', True)
        self.assertTrue(value)
        self.assertFalse(exited)
        value, exited = operator_state(value, 'S', True)
        self.assertTrue(value)
        self.assertFalse(exited)
        value, exited = operator_state(value, 'S', True, command=False)
        self.assertFalse(value)
        self.assertFalse(exited)

    def test_parent_loss_asserts_stop_and_exits(self):
        value, exited = operator_state(False, None, False)
        self.assertTrue(value)
        self.assertTrue(exited)

    def test_suspend_fault_overrides_clear_command(self):
        value, exited = operator_state(False, 'T', True, command=False)
        self.assertTrue(value)
        self.assertFalse(exited)

    def test_current_process_state_is_readable(self):
        self.assertIn(read_process_state(os.getpid()), {'R', 'S'})


if __name__ == '__main__':
    unittest.main()
