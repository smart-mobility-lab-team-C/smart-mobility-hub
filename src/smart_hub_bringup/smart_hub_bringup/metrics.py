"""metrics_logger: per-run JSON/CSV records from events and evaluator truth (A section 21.2)."""

import csv
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import time

import rclpy
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile
from rosidl_runtime_py.convert import message_to_ordereddict
from smart_hub_interfaces.msg import CrossingState, HubEvent, SafetyState, VehicleStateArray
from smart_hub_sim.geometry import intersects_crossing
from std_msgs.msg import String

RADIUS = {'robot': 0.2, 'bus': 0.3, 'car': 0.3}


def physical_conflict(vehicles):
    """Two or more mobile footprints inside C at once (A section 21.2 crossing conflict)."""
    inside = [v for v in vehicles
              if v.kind in RADIUS and intersects_crossing(v.pose.x, v.pose.y, RADIUS[v.kind])]
    return len(inside) > 1


def collisions(vehicles):
    """Pairs whose ground-truth footprints overlap."""
    hits = []
    for index, a in enumerate(vehicles):
        for b in vehicles[index + 1:]:
            if a.kind in RADIUS and b.kind in RADIUS and math.hypot(
                    a.pose.x - b.pose.x, a.pose.y - b.pose.y) < RADIUS[a.kind] + RADIUS[b.kind]:
                hits.append((a.vehicle_id, b.vehicle_id))
    return hits


def file_hash(path):
    """SHA-256 of a file, or an empty string when absent."""
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError:
        return ''


class MetricsLogger(Node):
    """Observe only; this node publishes nothing and has no control authority."""

    def __init__(self):
        """Declare record metadata and subscribe to decisions, safety and evaluator truth."""
        super().__init__('metrics_logger')
        for name, value in (('output_dir', 'evidence/runs/metrics'), ('scenario_id', ''),
                            ('seed', -1), ('commit', ''), ('config_path', ''),
                            ('model_path', '')):
            self.declare_parameter(name, value)
        self.value = {name: self.get_parameter(name).value for name in (
            'output_dir', 'scenario_id', 'seed', 'commit', 'config_path', 'model_path')}
        self.run = None
        transient = QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL)
        self.create_subscription(String, '/sim/run_id', self.on_run, transient)
        self.create_subscription(HubEvent, '/hub/events', self.on_event, 100)
        self.create_subscription(SafetyState, '/hub/safety', self.on_safety, transient)
        self.create_subscription(CrossingState, '/crossing/state', self.on_crossing, transient)
        self.create_subscription(VehicleStateArray, '/sim/evaluator/ground_truth',
                                 self.on_truth, 10)
        self.safety = self.crossing = None
        self.last_sample = 0.0

    def on_run(self, message):
        """Close the previous record and open a new one for each simulator run ID."""
        if self.run and self.run['run_id'] == message.data:
            return
        self.close()
        directory = Path(self.value['output_dir']) / message.data
        directory.mkdir(parents=True, exist_ok=True)
        self.run = {
            'run_id': message.data, 'directory': directory,
            'events': (directory / 'events.jsonl').open('a'),
            'csv': (directory / 'metrics.csv').open('a', newline=''),
            'summary': {
                'run_id': message.data, 'scenario_id': self.value['scenario_id'],
                'seed': self.value['seed'], 'commit': self.value['commit'],
                'config_sha256': file_hash(self.value['config_path']),
                'model_sha256': file_hash(self.value['model_path']),
                'start_utc': datetime.now(timezone.utc).isoformat(),
                'machine': {'platform': platform.platform(), 'cpus': os.cpu_count(),
                            'ros_distro': os.environ.get('ROS_DISTRO', '')},
                'accepted_goals': 0, 'rejected_goals': 0, 'results': [],
                'failure_reasons': {}, 'protective_stops': 0,
                'crossing_conflict_samples': 0, 'collision_samples': 0,
                'min_separation_m': None, 'truth_samples': 0,
            },
        }
        self.run['writer'] = csv.writer(self.run['csv'])
        self.run['writer'].writerow(['monotonic', 'safety_reason', 'stop_latched',
                                     'crossing_state', 'crossing_owner',
                                     'crossing_conflict', 'collision', 'min_separation_m'])

    def on_event(self, message):
        """Append every event and count goal outcomes and failure reasons."""
        if not self.run:
            return
        self.run['events'].write(json.dumps(
            {'t': time.monotonic(), **message_to_ordereddict(message)}) + '\n')
        summary = self.run['summary']
        if message.event == 'GOAL_REJECTED':
            summary['rejected_goals'] += 1
        elif message.event in ('APPROACH', 'TO_PICKUP', 'MOVING') and \
                message.reason.startswith('PLANNING'):
            summary['accepted_goals'] += 1
        elif message.event == 'protective_stop':
            summary['protective_stops'] += 1
        elif message.event == 'RESULT':
            try:
                result = json.loads(message.reason)
            except ValueError:
                result = {'raw': message.reason}
            result['entity'] = message.entity_id
            summary['results'].append(result)
            if not result.get('success', True):
                reason = str(result.get('reason', 'UNKNOWN'))
                summary['failure_reasons'][reason] = summary['failure_reasons'].get(
                    reason, 0) + 1

    def on_safety(self, message):
        """Keep the latest supervisor state for sampling."""
        self.safety = message

    def on_crossing(self, message):
        """Keep the latest crossing state for sampling."""
        self.crossing = message

    def on_truth(self, message):
        """Count physical conflicts and collisions on every truth sample; log about 1 Hz."""
        if not self.run:
            return
        summary = self.run['summary']
        vehicles = list(message.vehicles)
        conflict = physical_conflict(vehicles)
        hits = collisions(vehicles)
        summary['truth_samples'] += 1
        summary['crossing_conflict_samples'] += int(conflict)
        summary['collision_samples'] += int(bool(hits))
        distances = [math.hypot(a.pose.x - b.pose.x, a.pose.y - b.pose.y)
                     for i, a in enumerate(vehicles) for b in vehicles[i + 1:]]
        if distances:
            low = min(distances)
            if summary['min_separation_m'] is None or low < summary['min_separation_m']:
                summary['min_separation_m'] = low
        now = time.monotonic()
        if now - self.last_sample >= 1.0 or conflict or hits:
            self.last_sample = now
            self.run['writer'].writerow([
                f'{now:.3f}', self.safety.reason if self.safety else '',
                self.safety.stop_latched if self.safety else '',
                self.crossing.state if self.crossing else '',
                self.crossing.owner_id if self.crossing else '',
                int(conflict), int(bool(hits)), f'{min(distances):.3f}' if distances else ''])

    def close(self):
        """Write the summary and close files for the current run."""
        if not self.run:
            return
        self.run['summary']['end_utc'] = datetime.now(timezone.utc).isoformat()
        (self.run['directory'] / 'summary.json').write_text(
            json.dumps(self.run['summary'], indent=2) + '\n')
        self.run['events'].close()
        self.run['csv'].close()
        self.run = None


def main(args=None):
    """Spin until shutdown, then flush the open run record."""
    rclpy.init(args=args)
    node = MetricsLogger()
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, rclpy.executors.ExternalShutdownException):
        pass
    finally:
        node.close()
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
