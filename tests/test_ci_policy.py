"""Exercise CI routing and failures; these checks do not execute ROS acceptance."""

import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('ci_policy', ROOT / 'scripts/ci_policy.py')
policy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(policy)


class RoutingTests(unittest.TestCase):
    def test_draft_and_ready(self):
        for draft in (True, False):
            required, _ = policy.classify('pull_request', {'pull_request': {'draft': draft}},
                                          ['src/safety_supervisor/node.py'])
            self.assertEqual(required, not draft)

    def test_prose_evidence_contract_and_unknown(self):
        for paths, expected in [(['README.md', 'docs/m3.md', 'evidence/m3.json'], False),
                                (['docs/contracts/m1-fields.json'], True),
                                (['docs/new-config.yaml'], True),
                                (['src/new.py'], True), (['scripts/check_fast.sh'], True),
                                (['containers/Dockerfile'], True),
                                (['.github/workflows/verify.yml'], True),
                                (['new-unknown.md'], True), ([], True)]:
            with self.subTest(paths=paths):
                self.assertEqual(policy.classify('pull_request',
                                 {'pull_request': {'draft': False}}, paths)[0], expected)

    def test_manual(self):
        for value, expected in [('true', True), (True, True), ('false', False), (False, False)]:
            self.assertEqual(policy.classify('workflow_dispatch',
                             {'inputs': {'full_suite': value}}, [])[0], expected)

    def test_gate_failures_and_skips(self):
        self.assertTrue(policy.gate('success', 'success', 'true', 'success'))
        self.assertTrue(policy.gate('success', 'success', 'false', 'skipped'))
        for quick, classification, required, integration in [
                ('failure', 'success', 'false', 'skipped'),
                ('success', 'failure', '', 'skipped'),
                ('cancelled', 'success', 'true', 'skipped'),
                ('success', 'success', 'true', 'failure'),
                ('success', 'success', 'true', 'cancelled'),
                ('success', 'success', 'true', 'skipped'),
                ('success', 'success', '', 'skipped')]:
            self.assertFalse(policy.gate(quick, classification, required, integration))

    def test_cumulative_diff_and_contract_rename(self):
        # A later docs commit must not conceal earlier runtime changes. Renaming
        # a machine-readable contract into evidence must retain the deleted path.
        with tempfile.TemporaryDirectory() as work:
            def git(*args):
                return subprocess.check_output(['git', '-C', work, *args], text=True).strip()

            git('init', '-q')
            git('config', 'user.name', 'CI fixture')
            git('config', 'user.email', 'ci@example.invalid')
            root = Path(work)
            (root / 'docs/contracts').mkdir(parents=True)
            (root / 'docs/contracts/map.json').write_text('{}')
            git('add', '.')
            git('commit', '-qm', 'base')
            base = git('rev-parse', 'HEAD')
            (root / 'evidence').mkdir()
            git('mv', 'docs/contracts/map.json', 'evidence/map.json')
            git('commit', '-qm', 'rename contract')
            (root / 'README.md').write_text('prose')
            git('add', '.')
            git('commit', '-qm', 'docs tip')
            head = git('rev-parse', 'HEAD')
            # Invoke from the fixture without changing this test process cwd.
            result = subprocess.check_output([
                'python3', '-c',
                'import sys; sys.path.insert(0, sys.argv[1]); '
                'from ci_policy import changed_paths; '
                'print(changed_paths("pull_request", {"pull_request": '
                '{"base": {"sha": sys.argv[2]}, "head": {"sha": sys.argv[3]}}}))',
                str(ROOT / 'scripts'), base, head], cwd=work, text=True)
            self.assertIn('docs/contracts/map.json', result)
            self.assertIn('evidence/map.json', result)
            self.assertIn('README.md', result)
