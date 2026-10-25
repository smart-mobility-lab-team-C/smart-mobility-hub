#!/usr/bin/env python3
"""Run the 40-second image counting fixture against real ROS nodes."""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import signal
import subprocess
import time

import rclpy
from rclpy.node import Node
from smart_hub_interfaces.msg import CrossingState, QueueState
from smart_hub_interfaces.srv import ResetScenario
from std_msgs.msg import Bool


class Probe(Node):
    """Observe image-derived queue and crossing state without evaluator truth."""

    def __init__(self):
        """Create external E-stop heartbeat and reset client."""
        super().__init__('s1_acceptance_probe')
        self.samples = []
        self.crossing = []
        self.started = None
        self.estop = self.create_publisher(Bool, '/hub/estop', 1)
        self.create_timer(0.1, lambda: self.estop.publish(Bool(data=False)))
        self.create_subscription(QueueState, '/hub/queue', self.on_queue, 10)
        qos = rclpy.qos.QoSProfile(
            depth=1, durability=rclpy.qos.DurabilityPolicy.TRANSIENT_LOCAL)
        self.create_subscription(CrossingState, '/crossing/state',
                                 self.on_crossing, qos)
        self.reset = self.create_client(ResetScenario, '/scenario/reset')

    def on_queue(self, message):
        """Retain receipt time and unmodified acquisition stamp."""
        if self.started is not None:
            self.samples.append({
                'elapsed_sec': time.monotonic() - self.started,
                'source_stamp_ns': message.header.stamp.sec * 1_000_000_000 +
                message.header.stamp.nanosec,
                'count': message.count, 'valid': message.valid,
                'crossing_occupied': message.crossing_occupied,
            })

    def on_crossing(self, message):
        """Retain observed crossing state transitions."""
        if self.started is not None:
            self.crossing.append({
                'elapsed_sec': time.monotonic() - self.started,
                'state': message.state, 'valid': message.valid,
                'pedestrian_present': message.pedestrian_present,
            })


def spin_until(node, predicate, seconds):
    """Spin subscriptions and heartbeats while waiting for a bounded condition."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        rclpy.spin_once(node, timeout_sec=0.05)
        if predicate():
            return True
    return False


def check(samples):
    """Apply the T01/T02 stable-count, occlusion and frozen-feed bounds."""
    intervals = ((1.0, 4.5, 0), (6.0, 9.5, 3),
                 (11.0, 14.5, 5), (16.0, 19.5, 4))
    outcomes = []
    for start, end, expected in intervals:
        found = [item for item in samples if start <= item['elapsed_sec'] < end]
        outcomes.append({'interval': [start, end], 'expected': expected,
                         'samples': len(found),
                         'pass': bool(found) and all(item['valid'] and
                                                     item['count'] == expected
                                                     for item in found)})
    crossing = [item for item in samples if 20.5 <= item['elapsed_sec'] <= 23.8]
    occupied = bool(crossing) and all(item['crossing_occupied'] for item in crossing)
    invalid = next((item for item in samples
                    if 30.0 <= item['elapsed_sec'] <= 31.2 and not item['valid']), None)
    frozen = [item for item in samples if 30.0 <= item['elapsed_sec'] <= 31.2]
    stamps_frozen = bool(frozen) and len({item['source_stamp_ns'] for item in frozen}) == 1
    return {'counts': outcomes, 'crossing_occupied': occupied,
            'invalid_by_31_2_sec': invalid is not None,
            'acquisition_stamp_frozen': stamps_frozen,
            'status': 'PASS' if all(item['pass'] for item in outcomes) and
            occupied and invalid is not None and stamps_frozen else 'FAIL'}


def main():
    """Launch real nodes, reset the run and save raw observed samples."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    command = ['ros2', 'launch', 'smart_hub_bringup', 's1_counting.launch.py']
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    log_path = output.with_suffix('.launch.log')
    log = log_path.open('w')
    process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT,
                               start_new_session=True)
    report = {'status': 'BLOCKED', 'command': command, 'log': str(log_path),
              'started_utc': datetime.now(timezone.utc).isoformat(),
              'ros_domain_id': os.environ.get('ROS_DOMAIN_ID')}
    rclpy.init()
    node = Probe()
    try:
        if not spin_until(node, node.reset.service_is_ready, 15):
            raise TimeoutError('public reset service unavailable')
        request = ResetScenario.Request()
        request.scenario_id = 'm2_baseline'
        request.seed = 117
        request.preserve_logs = True
        reset = None
        for _ in range(10):
            future = node.reset.call_async(request)
            if not spin_until(node, future.done, 1.25):
                raise TimeoutError('reset response missing')
            reset = future.result()
            if reset.success:
                break
            spin_until(node, lambda: False, 0.5)
        if reset is None or not reset.success:
            raise RuntimeError('reset rejected: ' + (reset.reason if reset else 'unknown'))
        node.started = time.monotonic()
        spin_until(node, lambda: False, 40.5)
        report.update(check(node.samples))
        report['run_id'] = reset.run_id
        report['samples'] = node.samples
        report['crossing_states'] = node.crossing
    except Exception as error:
        report['status'] = 'BLOCKED'
        report['reason'] = repr(error)
    finally:
        report['ended_utc'] = datetime.now(timezone.utc).isoformat()
        output.write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
        node.destroy_node()
        rclpy.shutdown()
        os.killpg(process.pid, signal.SIGINT)
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGTERM)
        log.close()
    print(json.dumps({'status': report['status'], 'output': str(output)}))
    raise SystemExit(0 if report['status'] == 'PASS' else 1)


if __name__ == '__main__':
    main()
