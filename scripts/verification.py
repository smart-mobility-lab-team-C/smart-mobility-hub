"""Preserve gate outcomes and bound verifier process cleanup."""

import json
import os
import signal
import subprocess
import time
import traceback


class Blocked(RuntimeError):
    """Identify incomplete evidence separately from a measured failure."""


class StopCases(Exception):
    """Stop the current verifier after its first unsuccessful case."""


def overall_status(records):
    """Return the first unsuccessful outcome without turning BLOCKED into FAIL."""
    for record in records:
        if record['status'] in ('FAIL', 'BLOCKED'):
            return record['status']
    return 'PASS' if records and all(r['status'] == 'PASS' for r in records) else 'BLOCKED'


class CaseRunner:
    """Record cases once and leave downstream cases explicitly NOT RUN."""

    def __init__(self, names, measurement):
        """Declare the complete intended case list before running any operation."""
        self.names = names
        self.measurement = measurement
        self.results = []
        self.stopped = False

    def run(self, name, operation):
        """Execute one selected case or immediately propagate a previous stop."""
        if self.stopped:
            raise StopCases()
        if name not in self.names:
            return True
        self.measurement.clear()
        started = time.monotonic()
        try:
            record = {'name': name, 'status': 'PASS', 'observations': operation()}
        except (Exception, KeyboardInterrupt) as error:
            record = {
                'name': name,
                'status': 'BLOCKED' if isinstance(error, (Blocked, KeyboardInterrupt)) else 'FAIL',
                'reason': repr(error),
                'traceback': traceback.format_exc(),
                'observations': dict(self.measurement),
            }
        record['elapsed_sec'] = time.monotonic() - started
        self.results.append(record)
        print(json.dumps(record), flush=True)
        if record['status'] != 'PASS':
            self.stopped = True
            raise StopCases()
        return True

    def finish(self):
        """Retain all attempted outcomes and enumerate the unexecuted remainder."""
        completed = {record['name'] for record in self.results}
        return self.results + [
            {'name': name, 'status': 'NOT RUN'} for name in self.names if name not in completed
        ]


def signal_group(process, signum):
    """Signal an owned process group, including descendants of an exited leader."""
    try:
        os.killpg(process.pid, signal.SIGCONT)
        os.killpg(process.pid, signum)
    except ProcessLookupError:
        pass


def stop_processes(processes, grace_seconds=5.0, kill_seconds=2.0):
    """Reap all child groups using shared deadlines instead of per-child waits."""
    processes = list(processes)
    deadline = time.monotonic() + grace_seconds
    for process in processes:
        signal_group(process, signal.SIGINT)
    for process in processes:
        try:
            process.wait(timeout=max(0, deadline - time.monotonic()))
        except subprocess.TimeoutExpired:
            pass
    # Kill every group, including surviving descendants of reaped leaders.
    for process in processes:
        signal_group(process, signal.SIGKILL)
    deadline = time.monotonic() + kill_seconds
    for process in processes:
        process.wait(timeout=max(0, deadline - time.monotonic()))


def run_bounded(command, output, total_seconds=240.0, cleanup_seconds=20.0,
                interrupt=None, kill=None):
    """Reserve cleanup inside one total deadline; never restart a timed-out run."""
    started = time.monotonic()
    deadline = started + total_seconds
    process = subprocess.Popen(
        command, stdout=output, stderr=subprocess.STDOUT, start_new_session=True)
    timed_out = False
    try:
        process.wait(timeout=max(0, started + total_seconds - cleanup_seconds - time.monotonic()))
    except subprocess.TimeoutExpired:
        timed_out = True
        if interrupt:
            interrupt(deadline)
        else:
            signal_group(process, signal.SIGINT)
        try:
            process.wait(timeout=max(0, deadline - time.monotonic() - 3.0))
        except subprocess.TimeoutExpired:
            pass
        finally:
            if kill:
                kill(deadline)
            signal_group(process, signal.SIGKILL)
            process.wait(timeout=max(0, deadline - time.monotonic()))
    return {
        'exit_code': process.returncode, 'timed_out': timed_out,
        'elapsed_sec': time.monotonic() - started,
        'total_limit_sec': total_seconds, 'cleanup_reserve_sec': cleanup_seconds,
    }
