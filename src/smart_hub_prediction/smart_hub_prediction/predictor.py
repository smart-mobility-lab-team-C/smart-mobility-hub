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

from .model import features


class DemandPredictor(Node):
    """Keep forecast features grounded in received queue and track events."""

    def __init__(self):
        """Load the pinned local model and start the one-hertz publication timer."""
        super().__init__('demand_predictor')
        self.declare_parameter('prediction_horizon_sec', 30)
        self.declare_parameter('queue_confidence_min', 0.5)
        horizon = int(self.get_parameter('prediction_horizon_sec').value)
        self.confidence_min = float(self.get_parameter('queue_confidence_min').value)
        if horizon != 30 or not math.isfinite(self.confidence_min) or not (
                0 <= self.confidence_min <= 1):
            raise ValueError('invalid demand forecast parameters')
        path = Path(get_package_share_directory('smart_hub_prediction')) / 'models/ridge.json'
        raw = path.read_bytes()
        self.model = json.loads(raw)
        if self.model['horizon_sec'] != horizon or self.model['history_sec'] != 60:
            raise ValueError('model horizon/history mismatch')
        self.model_id = 'ridge-' + hashlib.sha256(raw).hexdigest()[:16]
        self.started = time.monotonic()
        self.queue = None
        self.samples = deque(maxlen=61)
        self.events = deque()
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
            self.started = time.monotonic()
            self.queue = None
            self.samples.clear()
            self.events.clear()

    def on_queue(self, message):
        """Retain source stamp and monotonic receipt separately."""
        self.queue = (message, time.monotonic())

    def on_event(self, message):
        """Store only observed track transitions within the current history span."""
        if message.scenario_id == 'perception' and message.event in (
                'TRACK_ENTRY', 'TRACK_EXIT'):
            self.events.append((time.monotonic(), message.event))

    def tick(self):
        """Publish explicit invalidity until a contiguous history is available."""
        now = time.monotonic()
        while self.events and now - self.events[0][0] > 61:
            self.events.popleft()
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
        if not valid:
            self.samples.clear()
            self.publisher.publish(message)
            return
        second_start = now - 1.0
        entries = sum(second_start < at <= now and kind == 'TRACK_ENTRY'
                      for at, kind in self.events)
        exits = sum(second_start < at <= now and kind == 'TRACK_EXIT'
                    for at, kind in self.events)
        self.samples.append((int(queue.count), entries, exits))
        if len(self.samples) < 61:
            self.publisher.publish(message)
            return
        counts, arrivals, departures = zip(*self.samples)
        values = features(counts, arrivals, departures, now - self.started)
        forecast = sum(coefficient * value for coefficient, value in
                       zip(self.model['coefficients'], values))
        message.predicted_count = float(max(0.0, forecast))
        message.baseline_count = float(queue.count)
        message.valid = True
        self.publisher.publish(message)


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
