#!/usr/bin/env python3
"""Record S2 demand prediction (T03) and dispatch (T04) against real ROS nodes.

T03 runs the real demand_predictor on scripted /hub/queue input. T04 runs the real
hub_coordinator (crossing_arbiter executable); the probe publishes forecasts, queue and
bus availability and serves /bus/dock itself so goal timing is observable. The final
case chains the real predictor into the real coordinator.
"""

import argparse
from collections import deque
import hashlib
import json
import math
from pathlib import Path
import re
import subprocess
import time
import traceback
import uuid

from ament_index_python.packages import get_package_prefix, get_package_share_directory
import rclpy
from rclpy.action import ActionServer, CancelResponse, GoalResponse
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile
from rclpy.task import Future
from smart_hub_interfaces.action import DockBus
from smart_hub_interfaces.msg import BusArrival, DemandPrediction, HubEvent, QueueState
from smart_hub_prediction.model import episode, evaluate, features, predict, windows
from std_msgs.msg import String
from verification import CaseRunner, cleanup_error, overall_status, stop_processes, StopCases

PREDICTOR = ['smart_hub_prediction', 'demand_predictor']
COORDINATOR = ['smart_hub_control', 'crossing_arbiter']
HIGH, LOW = 7.0, 3.0


class Probe(Node):
    """Script inputs, serve the bus action and record outputs with monotonic receipt."""

    def __init__(self, directory):
        """Create publishers, recorders and the probe-owned /bus/dock server."""
        super().__init__('s2_acceptance_probe')
        self.output = (directory / 'trace.jsonl').open('w')
        self.queue_pub = self.create_publisher(QueueState, '/hub/queue', 10)
        self.demand_pub = self.create_publisher(DemandPrediction, '/hub/demand', 10)
        self.arrival_pub = self.create_publisher(BusArrival, '/hub/bus_arrival', 10)
        self.event_pub = self.create_publisher(HubEvent, '/hub/events', 100)
        transient = QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL)
        self.run_pub = self.create_publisher(String, '/sim/run_id', transient)
        self.forecasts, self.events = deque(), deque()
        self.create_subscription(DemandPrediction, '/hub/demand', self._on_demand, 10)
        self.create_subscription(HubEvent, '/hub/events', self._on_event, 100)
        self.queue_state = None   # (count, valid, confidence) published at 5 Hz, or None
        self.bus_state = None     # (state, door_open) published at 5 Hz, or None
        self.script = deque()     # forecasts published at 1 Hz; None leaves a gap
        self.scripted = deque()   # (monotonic time, value, valid) of published forecasts
        self.goals, self.finish = [], {}
        self.create_timer(0.2, self._publish_inputs)
        self.create_timer(1.0, self._publish_forecast)
        ActionServer(self, DockBus, '/bus/dock', execute_callback=self._execute,
                     goal_callback=self._goal, cancel_callback=lambda _: CancelResponse.ACCEPT)

    def trace(self, topic, **fields):
        """Append one verifier event with a monotonic observer time."""
        self.output.write(json.dumps({'t': time.monotonic(), 'topic': topic, **fields}) + '\n')

    def _on_demand(self, message):
        if message.model_id != 'probe-script':
            self.forecasts.append((time.monotonic(), message))
            self.trace('demand', valid=message.valid, predicted=message.predicted_count,
                       baseline=message.baseline_count, model_id=message.model_id)

    def _on_event(self, message):
        if message.entity_id == 'hub_coordinator' and message.event.startswith(
                ('BUS_DISPATCH', 'DISPATCH_')):
            self.events.append((time.monotonic(), message.event, message.reason))
            self.trace('event', event=message.event, reason=message.reason)

    def _goal(self, request):
        self.trace('goal_request', bus_id=request.bus_id, bay_id=request.bay_id)
        return GoalResponse.ACCEPT

    async def _execute(self, handle):
        goal_id = bytes(handle.goal_id.uuid).hex()
        self.goals.append((time.monotonic(), goal_id))
        self.trace('goal_accepted', goal_id=goal_id)
        future = Future()
        self.finish[goal_id] = future
        success = await future
        if success:
            handle.succeed()
        else:
            handle.abort()
        return DockBus.Result(success=success, final_state='DOCKED' if success else 'IDLE',
                              reason='PROBE_COMPLETE')

    def _stamp(self, age=0.0):
        stamp = self.get_clock().now().to_msg()
        if age:
            nanoseconds = stamp.sec * 1_000_000_000 + stamp.nanosec - int(age * 1e9)
            stamp.sec, stamp.nanosec = divmod(nanoseconds, 1_000_000_000)
        return stamp

    def _publish_inputs(self):
        if self.queue_state is not None:
            count, valid, confidence = self.queue_state
            message = QueueState(zone_id='Q', count=int(count), confidence=float(confidence),
                                 valid=valid, crossing_occupied=False)
            message.header.stamp, message.header.frame_id = self._stamp(), 'map'
            self.queue_pub.publish(message)
        if self.bus_state is not None:
            state, door_open = self.bus_state
            message = BusArrival(bus_id='bus', state=state, eta_sec=0.0, eta_valid=False,
                                 door_open=door_open)
            message.header.stamp, message.header.frame_id = self._stamp(), 'map'
            self.arrival_pub.publish(message)

    def _publish_forecast(self):
        if not self.script:
            return
        item = self.script.popleft()
        if item is None:
            return
        # An item is a value or a tuple (value[, valid[, horizon_sec[, stamp_age_sec]]]).
        item = item if isinstance(item, tuple) else (item,)
        value, valid, horizon, age = item + (True, 30, 0.0)[len(item) - 1:]
        message = DemandPrediction(horizon_sec=horizon, predicted_count=float(value),
                                   baseline_count=-1.0, model_id='probe-script', valid=valid)
        message.header.stamp, message.header.frame_id = self._stamp(age), 'map'
        self.demand_pub.publish(message)
        self.scripted.append((time.monotonic(), value, valid))
        self.trace('scripted_forecast', value=value, valid=valid, horizon=horizon, age=age)

    def track_entry(self):
        """Publish one observed queue entry as the perception pipeline would."""
        self.event_pub.publish(HubEvent(scenario_id='perception', entity_id='probe',
                                        event='TRACK_ENTRY'))

    def new_run(self):
        """Reset predictor history through the documented run-id topic."""
        self.run_pub.publish(String(data=str(uuid.uuid4())))
        self.forecasts.clear()

    def complete(self, goal_id, success=True):
        """Finish one held /bus/dock goal."""
        self.finish.pop(goal_id).set_result(success)

    def wait(self, predicate, seconds=5.0):
        """Spin real callbacks until a predicate holds or the deadline passes."""
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if predicate():
                return True
            rclpy.spin_once(self, timeout_sec=0.02)
        return bool(predicate())

    def pause(self, seconds):
        """Keep callbacks alive while observing."""
        self.wait(lambda: False, seconds)

    def play(self, items):
        """Publish a forecast script at 1 Hz and wait until it has been sent."""
        self.script.extend(items)
        assert self.wait(lambda: not self.script, len(items) + 3), 'forecast script stalled'

    def dispatches(self, since):
        """Coordinator dispatch requests observed after a monotonic time."""
        return [(t, reason) for t, event, reason in self.events
                if t >= since and event == 'BUS_DISPATCH_REQUESTED']


class Nodes:
    """Start and stop real node processes with per-start logs."""

    def __init__(self, directory):
        """Remember where logs go."""
        self.directory, self.processes, self.logs, self.starts = directory, {}, [], 0

    def start(self, name, command):
        """Start one installed executable in its own process group."""
        self.stop(name)
        self.starts += 1
        log = (self.directory / f'{self.starts:02}-{name}.log').open('w')
        self.logs.append(log)
        package, executable, *arguments = command
        installed = Path(get_package_prefix(package)) / 'lib' / package / executable
        self.processes[name] = subprocess.Popen(
            [str(installed), *arguments], stdout=log, stderr=subprocess.STDOUT,
            start_new_session=True)
        return log.name

    def stop(self, name):
        """Stop one process if running."""
        process = self.processes.pop(name, None)
        if process is not None:
            stop_processes([process])

    def close(self):
        """Stop everything and close logs."""
        try:
            stop_processes(self.processes.values())
        finally:
            self.processes.clear()
            for log in self.logs:
                log.close()


def offline_report():
    """Recompute held-out metrics from the installed model and time pure inference."""
    path = Path(get_package_share_directory('smart_hub_prediction')) / 'models/ridge.json'
    raw = path.read_bytes()
    model = json.loads(raw)
    rows = windows([episode(seed) for seed in model['test_seeds']])
    scores = evaluate(rows, model['coefficients'])
    assert scores == model['test'], 'installed model report does not reproduce'
    durations = []
    for x, _, _ in rows:
        started = time.perf_counter()
        predict(model['coefficients'], x)
        durations.append((time.perf_counter() - started) * 1000)
    durations.sort()
    p95 = durations[int(0.95 * (len(durations) - 1))]
    assert p95 < 100, f'offline inference p95 {p95} ms'
    splits = {name: len(model[name + '_seeds']) for name in ('train', 'validation', 'test')}
    assert sum(splits.values()) >= 30 and not (
        set(model['train_seeds']) & set(model['test_seeds'])), splits
    return {'model_sha256': hashlib.sha256(raw).hexdigest(), 'episodes': splits,
            'penalty': model['penalty'], 'features': model['features'],
            'validation': model['validation'], 'test': scores,
            'model_no_worse_than_persistence':
                scores['model']['mae'] <= scores['persistence']['mae'],
            'inference_ms': {'clock': 'perf_counter', 'samples': len(durations),
                             'p50': durations[len(durations) // 2], 'p95': p95,
                             'max': durations[-1]}}


def steady_forecast(count):
    """Offline model output for a constant queue with no track events."""
    model = json.loads((Path(get_package_share_directory('smart_hub_prediction')) /
                        'models/ridge.json').read_text())
    history = [count] * 31
    return predict(model['coefficients'], features(history, [0] * 31, [0] * 31))


def latency_lines(log_path):
    """Inference-latency summaries the predictor logged (JSON in INFO lines)."""
    lines = []
    for line in Path(log_path).read_text().splitlines():
        match = re.search(r'(\{"event": "inference_latency".*\})', line)
        if match:
            lines.append(json.loads(match.group(1)))
    return lines


def verify(probe, nodes, only_case):
    """Run every declared case through the fail-fast recorder."""
    names = ['t03_offline_held_out', 't03_warmup_then_valid_at_1hz', 't03_rising_demand',
             't03_noisy_around_threshold', 't03_feed_gap_after_warmup',
             't03_invalid_queue_input', 't03_inference_latency_in_node',
             't03_persistence_selectable', 't04_three_consecutive_required',
             't04_one_outstanding_goal_and_escalation', 't04_cooldown_30s',
             't04_invalid_forecast_never_dispatches', 't04_feed_gap_resets_count',
             't04_bus_unavailable', 't04_fallback_observed_queue',
             't04_end_to_end_predictive_dispatch']
    if only_case:
        names = [only_case]
    measurement = {}
    runner = CaseRunner(names, measurement)
    try:
        _cases(probe, nodes, runner.run, measurement)
    except StopCases:
        pass
    except (Exception, KeyboardInterrupt) as error:
        runner.results.append({'name': 'verifier_setup', 'status': 'BLOCKED',
                               'reason': repr(error), 'traceback': traceback.format_exc()})
    return runner.finish()


def _cases(probe, nodes, case, measurement):
    """Exercise T03 and T04."""
    case('t03_offline_held_out', offline_report)
    state = {}

    def predictor(model='ridge'):
        nodes.stop('coordinator')
        state['predictor_log'] = nodes.start(
            'predictor', PREDICTOR + ['--ros-args', '-p', f'forecast_model:={model}'])
        assert probe.wait(lambda: probe.count_subscribers('/hub/queue') > 0, 10)
        probe.pause(1.0)
        probe.new_run()

    def collect(seconds):
        start = time.monotonic()
        probe.pause(seconds)
        return [(t - start, m) for t, m in probe.forecasts if t >= start]

    def warmup():
        predictor()
        probe.queue_state = (5, True, 0.9)
        start = time.monotonic()
        probe.pause(36.0)
        seen = [(t - start, m) for t, m in probe.forecasts if t >= start]
        first_valid = next(t for t, m in seen if m.valid)
        before = [m for t, m in seen if t < first_valid]
        intervals = [b[0] - a[0] for a, b in zip(seen, seen[1:])]
        expected = steady_forecast(5)
        last = seen[-1][1]
        measurement.update(first_valid_sec=first_valid, messages=len(seen))
        assert all(not m.valid and m.predicted_count == -1.0 for m in before)
        assert 29.0 <= first_valid <= 34.0, first_valid
        assert all(m.horizon_sec == 30 and m.header.frame_id == 'map' for _, m in seen)
        assert 0.9 <= sorted(intervals)[len(intervals) // 2] <= 1.1, intervals
        assert last.valid and abs(last.predicted_count - expected) < 1e-3, (
            last.predicted_count, expected)
        assert last.model_id.startswith('ridge-')
        return {'first_valid_sec': first_valid, 'median_interval_sec':
                sorted(intervals)[len(intervals) // 2], 'invalid_during_warmup': len(before),
                'steady5_online': last.predicted_count, 'steady5_offline': expected}

    case('t03_warmup_then_valid_at_1hz', warmup)

    def rising():
        count, start, rows = 5, time.monotonic(), []
        while count < 12:
            probe.pause(3.0)
            count += 1
            probe.queue_state = (count, True, 0.9)
            probe.track_entry()
        probe.pause(2.0)
        seen = [(t - start, m) for t, m in probe.forecasts if t >= start]
        rows = [(round(t, 1), m.baseline_count, round(m.predicted_count, 2)) for t, m in seen]
        assert seen and all(m.valid and math.isfinite(m.predicted_count) and
                            m.predicted_count >= 0 for _, m in seen), rows
        final = seen[-1][1]
        assert final.predicted_count >= final.baseline_count, rows
        return {'forecasts': rows}

    case('t03_rising_demand', rising)

    def noisy():
        pattern, start = [5, 6, 7, 6, 5, 6, 7, 6], time.monotonic()
        for index in range(20):
            probe.queue_state = (pattern[index % len(pattern)], True, 0.9)
            probe.pause(1.0)
        seen = [(t - start, m) for t, m in probe.forecasts if t >= start]
        assert seen and all(m.valid and math.isfinite(m.predicted_count) for _, m in seen)
        values = [round(m.predicted_count, 2) for _, m in seen]
        return {'forecasts': values, 'at_or_above_6': sum(v >= 6 for v in values)}

    case('t03_noisy_around_threshold', noisy)

    def feed_gap():
        probe.queue_state = None
        gap = time.monotonic()
        assert probe.wait(lambda: any(t > gap and not m.valid for t, m in probe.forecasts),
                          2.5), 'no invalid forecast within 2.5 s of feed gap'
        invalid_after = next(t for t, m in probe.forecasts if t > gap and not m.valid) - gap
        probe.pause(3.0)
        probe.queue_state = (5, True, 0.9)
        resumed = time.monotonic()
        probe.pause(35.0)
        valid_again = next((t - resumed for t, m in probe.forecasts
                            if t > resumed and m.valid), None)
        assert valid_again is not None and valid_again >= 29.0, valid_again
        return {'invalid_after_gap_sec': invalid_after, 'valid_again_after_sec': valid_again}

    case('t03_feed_gap_after_warmup', feed_gap)

    def invalid_queue():
        results = {}
        for label, value in (('valid_false', (5, False, 0.9)), ('low_confidence', (5, True, 0.2))):
            probe.queue_state = (5, True, 0.9)
            probe.pause(1.5)
            probe.queue_state = value
            start = time.monotonic()
            assert probe.wait(lambda: any(t > start + 0.05 and not m.valid
                                          for t, m in probe.forecasts), 2.5), label
            probe.pause(2.0)
            later = [m for t, m in probe.forecasts if t > start + 1.2]
            assert later and all(not m.valid for m in later), label
            results[label] = 'invalid'
        return results

    case('t03_invalid_queue_input', invalid_queue)

    def latency():
        lines = latency_lines(state['predictor_log'])
        assert lines, 'predictor logged no inference_latency summary'
        assert all(line['p95_ms'] < 100 for line in lines), lines
        return lines[-1]

    case('t03_inference_latency_in_node', latency)

    def persistence():
        predictor('persistence')
        probe.queue_state = (4, True, 0.9)
        seen = collect(35.0)
        valid = [m for _, m in seen if m.valid]
        assert valid and all(m.model_id == 'persistence' and m.predicted_count == 4.0
                             for m in valid), [(m.model_id, m.predicted_count) for m in valid]
        return {'valid_forecasts': len(valid), 'model_id': 'persistence'}

    case('t03_persistence_selectable', persistence)

    def coordinator(queue=None):
        nodes.stop('predictor')
        probe.queue_state, probe.bus_state = queue, ('IDLE', False)
        probe.script.clear()
        nodes.start('coordinator', COORDINATOR)
        assert probe.wait(lambda: probe.count_subscribers('/hub/bus_arrival') > 0, 10)
        probe.pause(2.5)   # action-client discovery of the probe's /bus/dock server
        for goal_id in list(probe.finish):
            probe.complete(goal_id, False)
        probe.pause(0.5)
        return time.monotonic()

    def third_high_time(since):
        """Monotonic time the third consecutive valid high forecast was published."""
        run = 0
        for t, value, valid in probe.scripted:
            if t < since:
                continue
            run = run + 1 if valid and value >= 6 else 0
            if run == 3:
                return t
        return None

    def three_consecutive():
        since = coordinator()
        probe.play([HIGH, HIGH, 5.0] * 4)
        probe.pause(1.5)
        assert not probe.dispatches(since) and not [g for g in probe.goals if g[0] >= since], (
            'dispatched without three consecutive')
        phase = time.monotonic()
        probe.script.extend([HIGH] * 6)
        assert probe.wait(lambda: probe.dispatches(phase), 9), 'no dispatch after highs'
        requested, reason = probe.dispatches(phase)[0]
        third = third_high_time(phase)
        assert third is not None and requested >= third, (requested, third)
        assert 'decision=PREDICTIVE' in reason, reason
        probe.wait(lambda: not probe.script, 8)
        return {'dispatch_after_third_high_sec': requested - third, 'reason': reason}

    case('t04_three_consecutive_required', three_consecutive)

    def outstanding():
        since = coordinator()
        probe.script.extend([HIGH] * 4)
        assert probe.wait(lambda: [g for g in probe.goals if g[0] >= since], 8)
        first = [g for g in probe.goals if g[0] >= since]

        def accepted():
            return [r for t, e, r in probe.events if t >= since and e == 'BUS_DISPATCH_ACCEPTED']

        # The coordinator reports acceptance only after its goal-response callback runs.
        assert probe.wait(accepted, 3) and accepted()[0] == f'goal_id={first[0][1]}', (
            accepted(), first)
        probe.play([HIGH] * 10)
        probe.pause(1.5)
        held = [g for g in probe.goals if g[0] >= since]
        assert len(held) == 1, f'{len(held)} goals while one outstanding'
        probe.complete(first[0][1], True)
        assert probe.wait(lambda: any(e == 'BUS_DISPATCH_RESULT' and first[0][1] in r
                                      for t, e, r in probe.events if t >= since), 3)
        probe.play([HIGH] * 5)
        probe.play([LOW] * 4 + [HIGH] * 4)
        probe.pause(1.5)
        cleared = [t for t, e, _ in probe.events if t >= since and
                   e == 'DISPATCH_ESCALATION_CLEARED']
        assert not cleared, 'escalation cleared after only four low forecasts'
        assert len([g for g in probe.goals if g[0] >= since]) == 1, 'redispatch while escalated'
        probe.play([LOW] * 6)
        assert probe.wait(lambda: any(e == 'DISPATCH_ESCALATION_CLEARED'
                                      for t, e, _ in probe.events if t >= since), 3)
        return {'goal_id': first[0][1], 'goals': 1}

    case('t04_one_outstanding_goal_and_escalation', outstanding)

    def cooldown():
        since = coordinator()
        probe.script.extend([HIGH] * 4)
        assert probe.wait(lambda: [g for g in probe.goals if g[0] >= since], 8)
        first_time, first_id = [g for g in probe.goals if g[0] >= since][0]
        probe.complete(first_id, True)
        probe.play([LOW] * 6)
        assert any(e == 'DISPATCH_ESCALATION_CLEARED' for t, e, _ in probe.events
                   if t >= since)
        probe.script.extend([HIGH] * 40)
        assert probe.wait(lambda: len([g for g in probe.goals if g[0] >= since]) >= 2,
                          first_time + 36 - time.monotonic()), 'no dispatch after cooldown'
        second_time = [g for g in probe.goals if g[0] >= since][1][0]
        probe.script.clear()
        gap = second_time - first_time
        # Observer times; allow 0.1 s for differing goal-delivery latency.
        assert 29.9 <= gap <= 33.0, gap
        return {'seconds_between_dispatches': gap}

    case('t04_cooldown_30s', cooldown)

    def invalid_forecast():
        since = coordinator(queue=(2, True, 0.9))
        script = ([(20.0, False)] * 4 + [(float('nan'), True)] * 4 +
                  [(20.0, True, 10)] * 4 + [(20.0, True, 30, 3.0)] * 4)
        probe.play(script)
        probe.queue_state = None
        probe.play(script)
        probe.pause(1.5)
        assert not probe.dispatches(since) and not [g for g in probe.goals if g[0] >= since]
        return {'invalid_forecasts_published': 2 * len(script), 'dispatches': 0}

    case('t04_invalid_forecast_never_dispatches', invalid_forecast)

    def feed_gap_count():
        since = coordinator()
        probe.play([HIGH, HIGH, None, None, None, HIGH, HIGH, 5.0, 5.0])
        probe.pause(1.5)
        assert not probe.dispatches(since), 'gap did not reset the consecutive count'
        phase = time.monotonic()
        probe.script.extend([HIGH] * 6)
        assert probe.wait(lambda: probe.dispatches(phase), 9)
        probe.wait(lambda: not probe.script, 8)
        return {'dispatch_after_gap_reset': True}

    case('t04_feed_gap_resets_count', feed_gap_count)

    def unavailable():
        since = coordinator()
        observed = {}
        for label, bus in (('approaching', ('APPROACH', False)), ('door_open', ('IDLE', True)),
                           ('stale_arrival', None)):
            probe.bus_state = bus
            probe.play([HIGH] * 5)
            observed[label] = len(probe.dispatches(since))
            assert not probe.dispatches(since), label
        probe.bus_state = ('IDLE', False)
        probe.script.extend([HIGH] * 4)
        assert probe.wait(lambda: probe.dispatches(since), 6), 'no dispatch once available'
        probe.wait(lambda: not probe.script, 6)
        return {'dispatches_while_unavailable': observed, 'dispatch_when_available': True}

    case('t04_bus_unavailable', unavailable)

    def fallback():
        since = coordinator(queue=(7, False, 0.9))
        probe.pause(5.0)
        assert not probe.dispatches(since), 'dispatched on an invalid queue'
        probe.queue_state = (7, True, 0.2)
        probe.pause(5.0)
        assert not probe.dispatches(since), 'dispatched on a low-confidence queue'
        probe.queue_state = (7, True, 0.9)
        assert probe.wait(lambda: probe.dispatches(since), 6), 'no fallback dispatch'
        reason = probe.dispatches(since)[0][1]
        assert 'decision=FALLBACK' in reason, reason
        probe.pause(3.0)
        assert len([g for g in probe.goals if g[0] >= since]) == 1
        return {'reason': reason}

    case('t04_fallback_observed_queue', fallback)

    def end_to_end():
        since = coordinator(queue=(3, True, 0.9))
        state['predictor_log'] = nodes.start('predictor', PREDICTOR)
        assert probe.wait(lambda: probe.count_subscribers('/hub/queue') > 1, 10)
        probe.pause(1.0)
        probe.new_run()
        probe.pause(34.0)
        assert not probe.dispatches(since), 'dispatch before forecasts were valid'
        count = 3
        while count < 10 and not probe.dispatches(since):
            probe.pause(3.0)
            count += 1
            probe.queue_state = (count, True, 0.9)
            probe.track_entry()
        assert probe.wait(lambda: probe.dispatches(since), 5), 'no dispatch on rising demand'
        requested, reason = probe.dispatches(since)[0]
        assert 'decision=PREDICTIVE' in reason, reason
        before = [m for t, m in probe.forecasts if since <= t <= requested][-3:]
        assert len(before) == 3 and all(m.valid and m.predicted_count >= 6 for m in before), [
            (m.valid, m.predicted_count) for m in before]
        return {'reason': reason, 'queue_at_dispatch': count,
                'last_forecasts': [round(m.predicted_count, 2) for m in before]}

    case('t04_end_to_end_predictive_dispatch', end_to_end)


def main():
    """Start real nodes per case, record every case and report honest status."""
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True)
    parser.add_argument('--case', help='run exactly one named case (debugging)')
    args = parser.parse_args()
    directory = Path(args.output).resolve().parent / (Path(args.output).stem + '-raw')
    if directory.exists():
        raise SystemExit('Evidence directory already exists; choose a unique run ID')
    directory.mkdir(parents=True)
    report = {'schema': 'smart-mobility-hub/s2-verification-v1', 'status': 'FAIL',
              'only_case': args.case, 'cases': [],
              'commands': {'predictor': PREDICTOR, 'coordinator': COORDINATOR},
              'clocks': 'monotonic observer times; wall-backed ROS stamps for freshness',
              'harness': 'T04 probe publishes forecasts/queue/bus availability and serves '
                         '/bus/dock; t04_end_to_end uses the real predictor'}
    nodes, probe = Nodes(directory), None
    started = time.monotonic()
    try:
        rclpy.init()
        probe = Probe(directory)
        report['cases'] = verify(probe, nodes, args.case)
        report['status'] = overall_status(report['cases'])
    except (Exception, KeyboardInterrupt) as error:
        report['status'] = 'BLOCKED'
        report['error'] = repr(error)
        report['traceback'] = traceback.format_exc()
    finally:
        try:
            nodes.close()
        except Exception as error:
            cleanup_error(report, 'nodes', error)
        if probe is not None:
            probe.output.close()
            probe.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
        trace = directory / 'trace.jsonl'
        if trace.exists():
            report['trace_sha256'] = hashlib.sha256(trace.read_bytes()).hexdigest()
        report['elapsed_sec'] = time.monotonic() - started
        Path(args.output).write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'status': report['status'], 'output': args.output}), flush=True)
    raise SystemExit({'PASS': 0, 'FAIL': 1, 'BLOCKED': 2}[report['status']])


if __name__ == '__main__':
    main()
