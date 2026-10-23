#!/usr/bin/env python3
"""Test evidence classification with independent clocks and real process suspension."""

import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest

from gap_tools import analyze, timed


def timeline(layer, gap=False):
    """Create periodic samples with a known common interval."""
    return [{'t': t / 10, 'layer': layer, 'stage': 'sample', 'pid': layer}
            for t in range(31) if not gap or not 10 < t < 20]


class GapAnalysisTests(unittest.TestCase):
    """Distinguish timing layers without claiming physical host suspension."""

    def test_global_pause(self):
        """A host sampler stall prevents a stronger root-cause claim."""
        result = analyze(timeline('host', True) + timeline('container', True), 0, 3)
        self.assertIn('host_sampling_gap', result['windows'][0]['classification'])

    def test_publisher_pause(self):
        """Shared ROS gaps while samplers run point to delivery or publication."""
        rows = timeline('host') + timeline('container')
        rows += timeline('observer', True) + timeline('probe', True)
        result = analyze(rows, 0, 3)
        self.assertIn('ROS_delivery_or_publisher_gap', result['windows'][0]['classification'])

    def test_near_threshold_host_delay(self):
        """A correlated host delay just below threshold cannot exonerate the host."""
        host = [r for r in timeline('host') if not 11 < r['t'] * 10 < 15]
        result = analyze(host + timeline('container', True), 0, 3)
        self.assertIn('correlated_host_sampling_delay', result['windows'][0]['classification'])

    def test_probe_pause(self):
        """An independent observer separates a local probe pause."""
        rows = timeline('host') + timeline('container') + timeline('observer')
        result = analyze(rows + timeline('probe', True), 0, 3)
        self.assertIn('probe_local_gap', result['windows'][0]['classification'])

    def test_incomplete_coverage(self):
        """Missing independent evidence stays unresolved."""
        result = analyze(timeline('probe', True), 0, 3)
        self.assertIn('unresolved', result['windows'][0]['classification'])

    def test_active_interval_and_threshold(self):
        """Ignore startup intervals and ordinary 10 Hz cadence."""
        self.assertFalse(analyze(timeline('host', True), 2, 3)['windows'])
        self.assertFalse(analyze(timeline('host'), 0, 3)['windows'])

    def test_slow_contract_stream_is_context_only(self):
        """Jitter on a nominal 2 Hz stream cannot establish a half-second stall."""
        rows = [{'t': t, 'topic': 'arrival'} for t in (0, 0.51, 1.02, 1.53)]
        self.assertFalse(analyze(rows, 0, 2)['windows'])

    def test_source_clock_and_missing_headers(self):
        """Keep acquisition-clock jumps distinct from unstamped receipt gaps."""
        rows = [{'t': t, 'layer': 'observer', 'stage': 'odom', 'source_wall': t + 100}
                for t in (0, 0.1, 1.1)]
        result = analyze(rows, 0, 2)
        self.assertAlmostEqual(result['windows'][0]['gaps'][0]['source_delta_sec'], 1.0)
        for row in rows:
            row['source_wall'] = None
        self.assertIsNone(analyze(rows, 0, 2)['windows'][0]['gaps'][0]['source_delta_sec'])

    def test_callback_failure(self):
        """Failed callbacks retain matching entry and exit records."""
        class Sink:
            def __init__(self):
                self.rows = []

            def emit(self, stage, **values):
                self.rows.append(dict(stage=stage, **values))
        sink = Sink()

        def fail():
            raise ValueError('expected')
        with self.assertRaises(ValueError):
            timed(sink, 'callback', fail)()
        self.assertEqual([r['phase'] for r in sink.rows], ['start', 'end'])
        self.assertEqual(sink.rows[0]['call'], sink.rows[1]['call'])

    def test_real_sampler_suspension(self):
        """A paused process is localized while an independent process continues."""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            processes = []
            try:
                for layer in ('host', 'container'):
                    processes.append(subprocess.Popen([
                        sys.executable, str(Path(__file__).with_name('gap_tools.py')), 'sample',
                        '--layer', layer, '--output', str(root / (layer + '.jsonl'))]))
                time.sleep(0.4)
                os.kill(processes[1].pid, signal.SIGSTOP)
                time.sleep(0.8)
                os.kill(processes[1].pid, signal.SIGCONT)
                time.sleep(0.4)
            finally:
                for process in processes:
                    os.kill(process.pid, signal.SIGCONT)
                    process.terminate()
                    process.wait(timeout=5)
            rows = [json.loads(line) for path in root.glob('*.jsonl')
                    for line in path.read_text().splitlines()]
            result = analyze(rows, min(r['t'] for r in rows), max(r['t'] for r in rows))
            self.assertTrue(result['windows'])
            # A real VM pause may overlap the injected fault. Assert the measured layer,
            # rather than assuming that the test host remained continuously scheduled.
            target = [r for r in rows if r['layer'] == 'container']
            self.assertGreater(max(b['t'] - a['t'] for a, b in zip(target, target[1:])), 0.7)
            for window in result['windows']:
                host_delay = window['sampler_max_interval_sec']['host']
                if host_delay > 0.5:
                    self.assertIn('host_sampling_gap', window['classification'])
                elif host_delay > 0.25:
                    self.assertIn('correlated_host_sampling_delay', window['classification'])
                else:
                    self.assertIn('container_scheduling_gap', window['classification'])


if __name__ == '__main__':
    unittest.main()
