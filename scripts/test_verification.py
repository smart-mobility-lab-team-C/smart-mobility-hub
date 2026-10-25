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

from door_measurement import (
    artifact_manifest, CACHE, copy_owned, GateStop, installation_manifest, Ledger,
    prepare_cache, sha, tree_manifest, writable_tree, write_json,
)
from verification import (
    Blocked, CaseRunner, cleanup_error, overall_status, run_bounded, stop_processes, StopCases,
)


class VerificationTest(unittest.TestCase):
    """Require explicit outcomes and bounded cleanup without running a mission."""

    def test_read_only_copy_preserves_original_and_executable_contents(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, target = root / 'source', root / 'target'
            source.mkdir()
            (source / 'readonly').write_text('prerequisite')
            (source / 'readonly').chmod(0o444)
            (source / 'executable').write_text('#!/bin/sh\nexit 0\n')
            (source / 'executable').chmod(0o555)
            for name in ('log', '__pycache__', '.pytest_cache'):
                (source / name).mkdir()
                (source / name / 'old').write_text('disposable')
            before = tree_manifest(source, metadata=True)
            copy_owned(source, target)
            self.assertEqual(before, tree_manifest(source, metadata=True))
            self.assertEqual((target / 'readonly').read_text(), 'prerequisite')
            self.assertEqual((target / 'readonly').stat().st_uid, os.getuid())
            self.assertTrue(os.access(target / 'readonly', os.W_OK))
            self.assertEqual((target / 'executable').stat().st_mode & 0o111, 0o111)
            self.assertEqual({p.name for p in target.iterdir()}, {'readonly', 'executable'})
            writable_tree(target)

    def test_preparation_discards_only_copied_affected_outputs(self):
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            source, results = repo / CACHE, repo / 'results'
            results.mkdir()
            for root in ('src', 'build', 'install'):
                for package in ('smart_hub_interfaces', 'smart_hub_sim', 'smart_hub_control'):
                    path = source / root / package
                    path.mkdir(parents=True)
                    (path / 'fixture').write_text(package)
                    (path / 'fixture').chmod(0o444)
            relative = '.cache/door-validation/fixture'
            write_json(results / 'attempt.json', {'cache_relative': relative})
            before = tree_manifest(source, metadata=True)
            prepare_cache(repo, results)
            self.assertEqual(before, tree_manifest(source, metadata=True))
            cache = repo / relative
            for root in ('build', 'install'):
                self.assertEqual([p.name for p in (cache / root).iterdir()],
                                 ['smart_hub_interfaces'])
            self.assertTrue((cache / 'src/smart_hub_sim/fixture').exists())
            self.assertIn('mount_identity', json.loads((results / 'attempt.json').read_text()))

    def test_unwritable_destination_blocks_before_build(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            blocked = root / 'blocked'
            blocked.mkdir()
            blocked.chmod(0o555)
            ledger = Ledger(root, ['preparation', 'build'])
            command = [sys.executable, '-c',
                       'from pathlib import Path; from door_measurement import writable_tree; '
                       f'writable_tree(Path({str(blocked)!r}))']
            try:
                with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(GateStop):
                    ledger.run('preparation', command, Path(__file__).parent, setup=True)
                with self.assertRaises(GateStop):
                    ledger.run('build', [sys.executable, '-c', 'raise Exception()'], root)
                self.assertEqual([r['status'] for r in ledger.records], ['BLOCKED', 'NOT RUN'])
                self.assertIn('not effectively writable', (root / 'preparation.log').read_text())
            finally:
                blocked.chmod(0o755)

    def test_fingerprint_covers_installed_data_and_ignores_python_caches(self):
        with tempfile.TemporaryDirectory() as temporary:
            cache = Path(temporary)
            for name in ('src', 'scripts', 'install'):
                (cache / name).mkdir()
                (cache / name / 'data').write_text(name)
            before = installation_manifest(cache)
            (cache / 'install/__pycache__').mkdir()
            (cache / 'install/__pycache__/test.pyc').write_bytes(b'generated')
            self.assertEqual(before, installation_manifest(cache))
            (cache / 'install/data').write_text('different installation')
            self.assertNotEqual(before, installation_manifest(cache))

    def test_shared_deadline_exhaustion_never_starts_subprocess(self):
        with tempfile.TemporaryFile(mode='w+') as output:
            with patch('verification.subprocess.Popen') as launch:
                result = run_bounded(['unused'], output, deadline=time.monotonic() + 1,
                                     cleanup_seconds=2)
            launch.assert_not_called()
        self.assertTrue(result['timed_out'])
        self.assertIsNone(result['exit_code'])

    def test_cleanup_failure_keeps_primary_failure_and_downstream_not_run(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            ledger = Ledger(directory, ['fault', 'downstream'])

            def failed_cleanup(deadline):
                raise RuntimeError('cleanup fault')

            with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(GateStop):
                ledger.run('fault', [sys.executable, '-c', 'raise SystemExit(2)'], directory,
                           bounded={'kill': failed_cleanup})
            record = json.loads(ledger.path.read_text())[0]
            self.assertEqual(record['status'], 'FAIL')
            self.assertEqual(record['exit_code'], 2)
            self.assertIn('cleanup fault', record['cleanup_errors'][0]['error'])
            self.assertEqual(ledger.records[1]['status'], 'NOT RUN')
        for status in ('FAIL', 'BLOCKED', 'PASS'):
            record = {'status': status}
            cleanup_error(record, 'nodes', RuntimeError('cleanup'))
            self.assertEqual(record['status'], 'BLOCKED' if status == 'PASS' else status)

    def test_keyboard_interruption_cleans_up_and_records_original_interruption(self):
        child = subprocess.Popen(
            [sys.executable, '-c', 'import signal,time; '
             'signal.signal(signal.SIGINT, signal.SIG_IGN); '
             'print("ready", flush=True); time.sleep(60)'],
            stdout=subprocess.PIPE, text=True, start_new_session=True)
        try:
            self.assertEqual(child.stdout.readline().strip(), 'ready')
            original_wait = child.wait
            calls = []

            def wait(timeout):
                calls.append(timeout)
                if len(calls) == 1:
                    raise KeyboardInterrupt()
                return original_wait(timeout=timeout)

            with patch('verification.subprocess.Popen', return_value=child):
                with patch.object(child, 'wait', side_effect=wait):
                    result = run_bounded(['fixture'], None, total_seconds=60, cleanup_seconds=3)
            self.assertTrue(result['interrupted'])
            self.assertFalse(result['timed_out'])
            self.assertEqual(result['exit_code'], -signal.SIGKILL)
            self.assertLess(result['elapsed_sec'], 3)
        finally:
            if child.poll() is None:
                os.killpg(child.pid, signal.SIGKILL)
                child.wait(timeout=1)
            child.stdout.close()

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
