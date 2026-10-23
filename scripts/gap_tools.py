#!/usr/bin/env python3
"""Independent timing capture and conservative gap analysis; no ROS dependency."""

import argparse
from collections import defaultdict
from functools import wraps
import json
import os
from pathlib import Path
import signal
import threading
import time


class Recorder:
    """Buffer local records and flush from an independently scheduled thread."""

    def __init__(self, path, layer):
        """Start a process-local heartbeat; it shares the interpreter GIL."""
        self.output = Path(path).open('x')
        self.layer = layer
        self.lock = threading.Lock()
        self.stop = threading.Event()
        self.sequence = 0
        self.thread = threading.Thread(target=self._heartbeat, daemon=True)
        self.thread.start()

    def emit(self, stage, **values):
        """Record monotonic receipt time and wall time without ROS clock conversion."""
        with self.lock:
            self.sequence += 1
            self.output.write(json.dumps(dict(
                t=time.monotonic(), wall=time.time(), pid=os.getpid(),
                sequence=self.sequence, layer=self.layer, stage=stage, **values)) + '\n')

    def _heartbeat(self):
        """Flush at 10 Hz; a missing heartbeat is evidence, never proof of suspension."""
        while not self.stop.is_set():
            self.emit('thread_heartbeat')
            with self.lock:
                self.output.flush()
            self.stop.wait(0.1)

    def close(self):
        """Join the writer before closing its file."""
        self.stop.set()
        self.thread.join()
        self.output.close()


def timed(recorder, stage, function):
    """Record callback entry/exit, including failures, with matching identifiers."""
    @wraps(function)
    def invoke(*args, **kwargs):
        call = time.monotonic_ns()
        recorder.emit(stage, phase='start', call=call)
        start = time.monotonic()
        cpu_start = time.thread_time()
        try:
            return function(*args, **kwargs)
        finally:
            recorder.emit(stage, phase='end', call=call, duration=time.monotonic() - start,
                          cpu_duration=time.thread_time() - cpu_start)
    return invoke


def read_optional(path):
    """Represent unavailable Linux measurements explicitly."""
    try:
        return Path(path).read_text()
    except OSError:
        return None


def sample(output, registry, layer):
    """Sample scheduling and Linux process/cgroup counters without ROS or Docker calls."""
    stopped = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stopped.set())
    signal.signal(signal.SIGINT, lambda *_: stopped.set())
    with Path(output).open('x', buffering=1) as stream:
        sequence = 0
        while not stopped.is_set():
            processes = {}
            if registry and Path(registry).exists():
                for line in Path(registry).read_text().splitlines():
                    try:
                        item = json.loads(line)
                        pid = int(item['pid'])
                        stat = read_optional(f'/proc/{pid}/stat')
                        if stat is None:
                            continue
                        processes[item['name']] = {
                            'pid': pid, 'stat': stat,
                            'status': '\n'.join(
                                line for line in (
                                    read_optional(f'/proc/{pid}/status') or '').splitlines()
                                if line.startswith(('State:', 'VmRSS:', 'Threads:',
                                                    'voluntary_ctxt_switches:',
                                                    'nonvoluntary_ctxt_switches:'))),
                            'schedstat': read_optional(f'/proc/{pid}/schedstat'),
                        }
                    except (ValueError, KeyError):
                        continue
            sequence += 1
            stream.write(json.dumps({
                't': time.monotonic(), 'wall': time.time(), 'pid': os.getpid(),
                'boottime': time.clock_gettime(time.CLOCK_BOOTTIME),
                'sequence': sequence, 'layer': layer, 'stage': 'sample', 'processes': processes,
                'load': read_optional('/proc/loadavg'),
                'uptime': read_optional('/proc/uptime'),
                'cpu_totals': '\n'.join(
                    line for line in (read_optional('/proc/stat') or '').splitlines()
                    if line.startswith('cpu')),
                'memory': '\n'.join(
                    line for line in (read_optional('/proc/meminfo') or '').splitlines()
                    if line.startswith(('MemAvailable:', 'SwapFree:'))),
                'pressure': {k: read_optional('/proc/pressure/' + k)
                             for k in ('cpu', 'memory', 'io')},
                'cgroup_cpu': read_optional('/sys/fs/cgroup/cpu.stat'),
                'cgroup_cpu_max': read_optional('/sys/fs/cgroup/cpu.max'),
                'cgroup_memory': read_optional('/sys/fs/cgroup/memory.events'),
                'clock_ticks': os.sysconf('SC_CLK_TCK'),
            }) + '\n')
            stopped.wait(0.1)


def load_records(directory, start=float('-inf'), end=float('inf')):
    """Read complete records; retain truncated-tail warnings after interrupted capture."""
    records, warnings = [], []
    for path in sorted(Path(directory).rglob('*.jsonl')):
        if path.name.startswith('gap-'):
            continue  # Generated context is a copy, never an additional acquisition.
        for number, line in enumerate(path.open(), 1):
            try:
                record = json.loads(line)
                if 't' in record and start <= record['t'] <= end:
                    record['_file'] = str(path.relative_to(directory))
                    records.append(record)
            except ValueError:
                warnings.append(f'{path.name}:{number}: incomplete/invalid JSON')
    return sorted(records, key=lambda r: r['t']), warnings


def stream_key(record):
    """Keep callback phases, processes and topic streams distinct."""
    return (record.get('layer', 'probe'), record.get('pid', 0),
            record.get('stage', record.get('topic', 'unknown')), record.get('phase', ''))


def source_time(record):
    """Read acquisition time without substituting receipt time for missing headers."""
    if 'source_wall' in record:
        return record['source_wall']
    stamp = record.get('message', {}).get('header', {}).get('stamp')
    return stamp['sec'] + stamp['nanosec'] * 1e-9 if stamp else None


def analyze(records, start, end, threshold=0.5):
    """Localize gaps with overlapping independent evidence, never infer a root cause."""
    streams = defaultdict(list)
    for record in records:
        streams[stream_key(record)].append(record)
    gaps = []
    for key, rows in streams.items():
        # Only periodic streams establish gaps; on-change events and callbacks do not.
        layer, _, stage, phase = key
        periodic = stage in ('sample', 'thread_heartbeat', 'executor_heartbeat',
                             'truth', 'odom', 'safety', 'crossing', 'queue',
                             'command', 'door', 'vehicles')
        periodic |= stage in ('sim.step', 'safety.tick') and phase == 'start'
        if not periodic:
            continue
        for a, b in zip(rows, rows[1:]):
            if start <= a['t'] < b['t'] <= end and b['t'] - a['t'] > threshold:
                source_a, source_b = source_time(a), source_time(b)
                gaps.append({'stream': list(key), 'start': a['t'], 'end': b['t'],
                             'duration': b['t'] - a['t'],
                             'source_delta_sec': source_b - source_a
                             if source_a is not None and source_b is not None else None})
    # Combine overlapping intervals rather than counting each topic as a separate stall.
    windows = []
    for gap in sorted(gaps, key=lambda g: g['start']):
        if windows and gap['start'] <= windows[-1]['end']:
            windows[-1]['end'] = max(windows[-1]['end'], gap['end'])
            windows[-1]['gaps'].append(gap)
        else:
            windows.append({'start': gap['start'], 'end': gap['end'], 'gaps': [gap]})
    for window in windows:
        layers = {g['stream'][0] for g in window['gaps']}
        sampler_intervals = {}
        for layer in ('host', 'container'):
            intervals = [b['t'] - a['t'] for key, rows in streams.items()
                         if key[0] == layer and key[2] == 'sample'
                         for a, b in zip(rows, rows[1:])
                         if a['t'] <= window['end'] and b['t'] >= window['start']]
            sampler_intervals[layer] = max(intervals) if intervals else None
        window['sampler_max_interval_sec'] = sampler_intervals
        observer_coverage = any(k[0] == 'observer' and rows[0]['t'] <= window['start']
                                and rows[-1]['t'] >= window['end']
                                for k, rows in streams.items())
        host_coverage = any(k[0] == 'host' and rows[0]['t'] <= window['start']
                            and rows[-1]['t'] >= window['end'] for k, rows in streams.items())
        container_coverage = any(k[0] == 'container' and rows[0]['t'] <= window['start']
                                 and rows[-1]['t'] >= window['end']
                                 for k, rows in streams.items())
        if 'host' in layers:
            classification = 'host_sampling_gap; VM/host scheduling cause unresolved'
        elif (host_coverage and sampler_intervals['host'] is not None
              and sampler_intervals['host'] > threshold / 2):
            classification = 'correlated_host_sampling_delay; timing layer unresolved'
        elif 'container' in layers and host_coverage:
            classification = 'container_scheduling_gap; host sampler continued'
        elif host_coverage and container_coverage:
            if 'observer' in layers and 'probe' in layers:
                classification = 'ROS_delivery_or_publisher_gap; system samplers continued'
            elif 'probe' in layers and observer_coverage:
                classification = 'probe_local_gap; independent observer continued'
            elif 'probe' in layers:
                classification = 'unresolved; independent observer coverage incomplete'
            elif 'observer' in layers:
                classification = 'observer_local_gap; system samplers continued'
            else:
                classification = 'process_callback_gap; system samplers continued'
        else:
            classification = 'unresolved; independent coverage incomplete'
        window['classification'] = classification
        window['slow_callbacks'] = [r for r in records
                                    if r.get('duration', 0) > threshold
                                    and r['t'] >= window['start']
                                    and r['t'] - r['duration'] <= window['end']]
    durations = defaultdict(list)
    for record in records:
        if record.get('phase') == 'end' and start <= record['t'] <= end:
            durations[record['stage']].append(record['duration'])
    callback_metrics = {}
    for stage, values in durations.items():
        values.sort()
        callback_metrics[stage] = {
            'count': len(values), 'max_sec': max(values),
            'p95_sec': values[int((len(values) - 1) * 0.95)],
        }
    cadence = {}
    for key, rows in streams.items():
        values = sorted(b['t'] - a['t'] for a, b in zip(rows, rows[1:])
                        if start <= a['t'] < b['t'] <= end)
        if values and key[2] in ('odom', 'executor_heartbeat'):
            cadence['/'.join(map(str, key))] = {
                'count': len(values), 'p95_sec': values[int((len(values) - 1) * 0.95)],
                'max_sec': max(values),
            }
    stops = [r for r in records if start <= r['t'] <= end
             and r.get('topic') == 'event'
             and r.get('message', {}).get('event') == 'SAFE_STOP']
    return {'threshold_sec': threshold, 'windows': windows, 'callback_metrics': callback_metrics,
            'cadence': cadence, 'protective_stops': stops,
            'status': 'GAP_OBSERVED' if windows else 'NOT_REPRODUCED'}


def report(directory):
    """Analyze only declared active intervals and export five-second context windows."""
    directory = Path(directory)
    metadata = json.loads((directory / 'run.json').read_text())
    records, warnings = load_records(
        directory, metadata['active_start'] - 5, metadata['active_end'] + 5)
    if metadata.get('active_interval_established', True):
        result = analyze(records, metadata['active_start'], metadata['active_end'])
    else:
        result = {'status': 'INCOMPLETE_STARTUP', 'windows': [], 'cadence': {},
                  'callback_metrics': {}, 'protective_stops': []}
    result['warnings'] = warnings
    for index, window in enumerate(result['windows']):
        path = directory / f'gap-{index:03d}.jsonl'
        with path.open('w') as stream:
            for row in records:
                if window['start'] - 5 <= row['t'] <= window['end'] + 5:
                    stream.write(json.dumps(row) + '\n')
        window['context'] = path.name
    (directory / 'analysis.json').write_text(json.dumps(result, indent=2) + '\n')
    return result


def main():
    """Run an independent sampler or analyze an existing diagnostic attempt."""
    parser = argparse.ArgumentParser()
    subs = parser.add_subparsers(dest='command', required=True)
    sampler = subs.add_parser('sample')
    sampler.add_argument('--output', required=True)
    sampler.add_argument('--registry')
    sampler.add_argument('--layer', required=True)
    analysis = subs.add_parser('analyze')
    analysis.add_argument('directory')
    pause = subs.add_parser('pause')
    pause.add_argument('--pid', required=True, type=int)
    pause.add_argument('--output', required=True)
    pause.add_argument('--seconds', type=float, default=0.8)
    args = parser.parse_args()
    if args.command == 'sample':
        sample(args.output, args.registry, args.layer)
    elif args.command == 'analyze':
        print(json.dumps(report(args.directory), indent=2))
    else:
        # The diagnostic runner supplies only one of its own simulator/observer/probe PIDs.
        with Path(args.output).open('x', buffering=1) as stream:
            try:
                stream.write(json.dumps({'t': time.monotonic(), 'layer': 'injection',
                                         'stage': 'SIGSTOP', 'target_pid': args.pid}) + '\n')
                os.kill(args.pid, signal.SIGSTOP)
                time.sleep(args.seconds)
            finally:
                os.kill(args.pid, signal.SIGCONT)
                stream.write(json.dumps({'t': time.monotonic(), 'layer': 'injection',
                                         'stage': 'SIGCONT', 'target_pid': args.pid}) + '\n')


if __name__ == '__main__':
    main()
