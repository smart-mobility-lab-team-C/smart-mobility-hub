"""Exercise unsuccessful gates, fail-fast control flow and real timeout cleanup."""

import contextlib
import io
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from door_measurement import artifact_manifest, GateStop, Ledger, sha
from verification import (
    Blocked, CaseRunner, overall_status, run_bounded, StopCases, stop_processes,
)


class VerificationTest(unittest.TestCase):
    """Require explicit outcomes and bounded cleanup without running a mission."""

    def test_blocked_and_failed_cases_stop_immediately(self):
        for error, expected in ((Blocked('missing transition'), 'BLOCKED'),
                                (AssertionError('duration too short'), 'FAIL')):
            calls = []
            measurement = {}
            runner = CaseRunner(['first', 'fault', 'downstream'], measurement)

            def fault():
                measurement['source_status'] = expected
                raise error

            with contextlib.redirect_stdout(io.StringIO()):
                runner.run('first', lambda: {'ok': True})
                with self.assertRaises(StopCases):
                    runner.run('fault', fault)
                    calls.append('incorrect continuation')
                with self.assertRaises(StopCases):
                    runner.run('downstream', lambda: calls.append('downstream'))
            records = runner.finish()
            self.assertEqual([r['status'] for r in records], ['PASS', expected, 'NOT RUN'])
            self.assertEqual(overall_status(records), expected)
            self.assertEqual(records[1]['observations']['source_status'], expected)
            self.assertEqual(calls, [])

    def test_real_verifier_propagates_blocked_and_marks_remaining_cases(self):
        try:
            import verify_m3
        except ModuleNotFoundError as error:
            if error.name in ('action_msgs', 'rclpy'):
                self.skipTest('ROS imports require the pinned controls container')
            raise
        calls = []

        def interrupted(probe, processes, runs, only_case, comparison, case, measurement):
            def operation():
                measurement['source_door_assessment'] = {'status': 'BLOCKED'}
                raise Blocked('overlapping duration bounds')
            case('nominal_docking_01', operation)
            calls.append('incorrect continuation')

        with patch.object(verify_m3, '_verify_cases', side_effect=interrupted):
            with contextlib.redirect_stdout(io.StringIO()):
                records = verify_m3.verify(None, {}, 10)
        self.assertEqual(len(records), 24)
        self.assertEqual(records[0]['status'], 'BLOCKED')
        self.assertTrue(all(r['status'] == 'NOT RUN' for r in records[1:]))
        self.assertEqual(calls, [])

    def test_failed_command_retains_provenance_and_hashes(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            ledger = Ledger(directory, ['fault', 'downstream'])
            command = [sys.executable, '-c', 'print("failure evidence"); raise SystemExit(1)']
            with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(GateStop):
                ledger.run('fault', command, directory)
            records = json.loads(ledger.path.read_text())
            self.assertEqual([r['status'] for r in records], ['FAIL', 'NOT RUN'])
            self.assertEqual(records[0]['command'], command)
            self.assertEqual(records[0]['exit_code'], 1)
            self.assertIn('started_utc', records[0])
            self.assertIn('ended_utc', records[0])
            artifact_manifest(directory)
            self.assertIn(sha(directory / 'fault.log'),
                          (directory / 'artifact-sha256.txt').read_text())

    def test_timeout_kills_and_reaps_process_group_within_total_limit(self):
        command = [sys.executable, '-c',
                   'import signal, subprocess, sys, time; '
                   'signal.signal(signal.SIGINT, signal.SIG_IGN); '
                   'child = subprocess.Popen([sys.executable, "-c", '
                   '"import signal,time; signal.signal(signal.SIGINT, signal.SIG_IGN); '
                   'time.sleep(60)"]); print(child.pid, flush=True); time.sleep(60)']
        with tempfile.TemporaryFile(mode='w+') as output:
            result = run_bounded(command, output, total_seconds=4, cleanup_seconds=3)
            output.seek(0)
            child_pid = int(output.read().strip())
        self.assertTrue(result['timed_out'])
        self.assertEqual(result['exit_code'], -signal.SIGKILL)
        self.assertLess(result['elapsed_sec'], 4)
        state = Path(f'/proc/{child_pid}/stat')
        deadline = time.monotonic() + 0.5
        while state.exists() and state.read_text().split()[2] != 'Z':
            self.assertLess(time.monotonic(), deadline, 'descendant survived timeout cleanup')
            time.sleep(0.01)

    def test_cleanup_uses_one_shared_deadline_for_all_children(self):
        processes = []
        try:
            for _ in range(3):
                child = subprocess.Popen(
                    [sys.executable, '-c', 'import signal,time; '
                     'signal.signal(signal.SIGINT, signal.SIG_IGN); '
                     'print("ready", flush=True); time.sleep(60)'],
                    stdout=subprocess.PIPE, text=True, start_new_session=True)
                processes.append(child)
                self.assertEqual(child.stdout.readline().strip(), 'ready')
            started = time.monotonic()
            stop_processes(processes, grace_seconds=0.4, kill_seconds=1)
            self.assertLess(time.monotonic() - started, 1.0)
            self.assertTrue(all(p.returncode == -signal.SIGKILL for p in processes))
        finally:
            for child in processes:
                if child.poll() is None:
                    os.killpg(child.pid, signal.SIGKILL)
                    child.wait(timeout=1)
                child.stdout.close()


if __name__ == '__main__':
    unittest.main()
