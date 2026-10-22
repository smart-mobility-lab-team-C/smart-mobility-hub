"""Exercise side effects and failures; these tests do not verify ROS."""
import importlib.util
import io
import subprocess
import unittest
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('m0', ROOT / 'scripts/m0.py')
m0 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m0)


class BootstrapTests(unittest.TestCase):
    def test_check_never_builds_or_creates_evidence(self):
        report = {'checks': [{'name': 'docker', 'status': 'BLOCKED', 'detail': 'absent'}]}
        with patch.object(m0, 'diagnose', return_value=report), \
                patch.object(m0, 'command') as command, \
                patch.object(Path, 'mkdir') as mkdir, redirect_stdout(io.StringIO()):
            self.assertEqual(m0.bootstrap(SimpleNamespace(native=False, check=True,
                                                         install=False)), 2)
            command.assert_not_called()
            mkdir.assert_not_called()

    def test_install_missing_runtime_stops_before_mutation(self):
        report = {'checks': [{'name': 'docker_daemon', 'status': 'BLOCKED', 'detail': 'denied'}]}
        with patch.object(m0, 'diagnose', return_value=report), \
                patch.object(m0, 'command') as command, redirect_stderr(io.StringIO()):
            self.assertEqual(m0.bootstrap(SimpleNamespace(native=False, check=False,
                                                         install=True)), 2)
            command.assert_not_called()

    def test_native_rejected_before_diagnostics(self):
        with patch.object(m0, 'diagnose') as diagnose, redirect_stderr(io.StringIO()):
            self.assertEqual(m0.bootstrap(SimpleNamespace(native=True)), 2)
            diagnose.assert_not_called()

    def test_subprocess_failure_is_not_success(self):
        with patch.object(m0.subprocess, 'run', return_value=SimpleNamespace(returncode=9)):
            with self.assertRaises(RuntimeError):
                m0.command(['docker', 'build'], io.StringIO())

    def test_probe_timeout_becomes_blocker(self):
        with patch.object(m0, 'run', side_effect=subprocess.TimeoutExpired('docker', 20)):
            self.assertEqual(m0.probe(['docker', 'info']), (False, ''))


if __name__ == '__main__':
    unittest.main()
