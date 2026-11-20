"""Publish thirty-second demand forecasts from sixty seconds of valid observations."""

from collections import deque
import hashlib
import json
import math
from pathlib import Path
import time

from ament_index_python.packages import get_package_share_directory
import rclpy
from rclpy.node import Node
from smart_hub_interfaces.msg import DemandPrediction, HubEvent, QueueState
from std_msgs.msg import String

from .model import FEATURE_SPAN, features, predict


class DemandPredictor(Node):
    """Keep forecast features grounded in received queue and track events."""

    def __init__(self):
        """Load the pinned local model and start the one-hertz publication timer."""
        super().__init__('demand_predictor')
        self.declare_parameter('prediction_horizon_sec', 30)
        self.declare_parameter('queue_confidence_min', 0.5)
        # A section 9.4: the persistence baseline must remain selectable if the model is worse.
        self.declare_parameter('forecast_model', 'ridge')
        horizon = int(self.get_parameter('prediction_horizon_sec').value)
        self.confidence_min = float(self.get_parameter('queue_confidence_min').value)
        self.forecast_model = str(self.get_parameter('forecast_model').value)
        if horizon != 30 or not math.isfinite(self.confidence_min) or not (
                0 <= self.confidence_min <= 1) or self.forecast_model not in (
                'ridge', 'persistence'):
            raise ValueError('invalid demand forecast parameters')
        path = Path(get_package_share_directory('smart_hub_prediction')) / 'models/ridge.json'
        raw = path.read_bytes()
        self.model = json.loads(raw)
        if (self.model['horizon_sec'] != horizon or self.model['history_sec'] != 60 or
                self.model.get('feature_span_sec') != FEATURE_SPAN):
            raise ValueError('model horizon/history mismatch')
        self.model_id = ('ridge-' + hashlib.sha256(raw).hexdigest()[:16]
                         if self.forecast_model == 'ridge' else 'persistence')
        self.queue = None
        self.samples = deque(maxlen=61)
        self.events = deque()        # (source stamp, kind) of accepted track transitions
        self.seen_events = set()     # (entity_id, event) already counted in this run
        self.last_sample_stamp = None
        self.rejected = {'old_run': 0, 'duplicate': 0, 'future': 0, 'late': 0,
                         'late_shifted': 0}
        self.ages = deque(maxlen=600)   # (source age, receipt age) of used queue samples
        self.inference_ms = deque(maxlen=600)
        self.run_id = ''
        self.publisher = self.create_publisher(DemandPrediction, '/hub/demand', 10)
        self.create_subscription(QueueState, '/hub/queue', self.on_queue, 10)
        self.create_subscription(HubEvent, '/hub/events', self.on_event, 100)
        run_qos = rclpy.qos.QoSProfile(
            depth=1, durability=rclpy.qos.DurabilityPolicy.TRANSIENT_LOCAL)
        self.create_subscription(String, '/sim/run_id', self.on_run_id, run_qos)
        self.create_timer(1.0, self.tick)

    def on_run_id(self, message):
        """Reset model history on a new seeded run."""
        if message.data != self.run_id:
            self.run_id = message.data
            self.queue = None
            self.samples.clear()
            self.events.clear()
            self.seen_events.clear()
            self.last_sample_stamp = None

    def on_queue(self, message):
        """Retain source stamp and monotonic receipt separately."""
        self.queue = (message, time.monotonic())

    def on_event(self, message):
        """Keep each track transition once, by source time, for the current run only."""
        if message.scenario_id != 'perception' or message.event not in (
                'TRACK_ENTRY', 'TRACK_EXIT'):
            return
        if message.run_id != self.run_id:
            self.rejected['old_run'] += 1
            return
        key = (message.entity_id, message.event)
        if key in self.seen_events:
            self.rejected['duplicate'] += 1
            return
        stamp = message.header.stamp.sec + message.header.stamp.nanosec * 1e-9
        if stamp > self.get_clock().now().nanoseconds * 1e-9:
            self.rejected['future'] += 1
            return
        if self.last_sample_stamp is not None and stamp <= self.last_sample_stamp:
            # Late-event policy: history is never rewritten. A transition at most 1 s
            # late counts in the next sample; anything older is counted and dropped.
            if stamp <= self.last_sample_stamp - 1.0:
                self.rejected['late'] += 1
                return
            self.rejected['late_shifted'] += 1
            stamp = self.last_sample_stamp + 1e-6
        self.seen_events.add(key)
        self.events.append((stamp, message.event))

    def tick(self):
        """Publish explicit invalidity until a contiguous history is available."""
        now = time.monotonic()
        message = DemandPrediction()
        message.header.stamp = self.get_clock().now().to_msg()
        message.header.frame_id = 'map'
        message.horizon_sec = 30
        message.model_id = self.model_id
        message.predicted_count = -1.0
        message.baseline_count = -1.0
        sample = self.queue
        valid = False
        if sample:
            queue, received = sample
            stamp = queue.header.stamp.sec + queue.header.stamp.nanosec * 1e-9
            age = self.get_clock().now().nanoseconds * 1e-9 - stamp
            valid = (queue.valid and queue.zone_id == 'Q' and
                     queue.header.frame_id == 'map' and
                     math.isfinite(queue.confidence) and
                     self.confidence_min <= queue.confidence <= 1 and
                     0 <= age <= 1.0 and now - received <= 0.5)
        # Contiguous one-second history (A section 9.2): each sample needs a new source
        # stamp 0.5-1.5 s after the previous one; a repeat, reorder or gap restarts warm-up.
        if valid and self.last_sample_stamp is not None and not (
                0.5 <= stamp - self.last_sample_stamp <= 1.5):
            valid = False
        if not valid:
            self.samples.clear()
            self.last_sample_stamp = None
            self.publisher.publish(message)
            return
        previous = self.last_sample_stamp if self.last_sample_stamp is not None else stamp - 1.0
        entries = sum(previous < at <= stamp and kind == 'TRACK_ENTRY'
                      for at, kind in self.events)
        exits = sum(previous < at <= stamp and kind == 'TRACK_EXIT'
                    for at, kind in self.events)
        while self.events and self.events[0][0] <= stamp:
            self.events.popleft()
        self.last_sample_stamp = stamp
        self.ages.append((age, now - received))
        self.samples.append((int(queue.count), entries, exits))
        # The forecast carries the acquisition stamp of the queue sample it is based on.
        message.header.stamp = queue.header.stamp
        if len(self.samples) < FEATURE_SPAN:
            self.publisher.publish(message)
            return
        started = time.perf_counter()
        counts, arrivals, departures = zip(*self.samples)
        if self.forecast_model == 'ridge':
            forecast = predict(self.model['coefficients'],
                               features(counts, arrivals, departures))
        else:
            forecast = float(counts[-1])
        self.inference_ms.append((time.perf_counter() - started) * 1000.0)
        message.predicted_count = float(forecast)
        message.baseline_count = float(queue.count)
        message.valid = True
        self.publisher.publish(message)
        if len(self.inference_ms) % 30 == 0:
            ordered = sorted(self.inference_ms)
            self.get_logger().info(json.dumps({
                'event': 'inference_latency', 'clock': 'perf_counter',
                'model_id': self.model_id, 'samples': len(ordered),
                'p50_ms': ordered[len(ordered) // 2],
                'p95_ms': ordered[int(0.95 * (len(ordered) - 1))],
                'max_ms': ordered[-1],
                'source_age_p95_sec': sorted(a for a, _ in self.ages)[
                    int(0.95 * (len(self.ages) - 1))] if self.ages else None,
                'receipt_age_p95_sec': sorted(r for _, r in self.ages)[
                    int(0.95 * (len(self.ages) - 1))] if self.ages else None,
                'rejected_events': dict(self.rejected)}))


def main(args=None):
    """Run the demand predictor."""
    rclpy.init(args=args)
    node = DemandPredictor()
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, rclpy.executors.ExternalShutdownException):
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
