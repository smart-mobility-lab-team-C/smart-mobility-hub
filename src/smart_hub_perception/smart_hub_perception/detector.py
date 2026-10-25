"""Synthetic image pedestrian detector with calibrated foot-point tracking."""

import math
import time

from ament_index_python.packages import get_package_share_directory
import rclpy
from rclpy.node import Node
from sensor_msgs.msg import Image
from smart_hub_interfaces.msg import HubEvent, QueueState
from std_msgs.msg import String

from .nanodet import NanoDetPerson


def _solve(matrix, values):
    """Solve a small full-rank linear system by pivoted elimination."""
    rows = [list(row) + [value] for row, value in zip(matrix, values)]
    size = len(rows)
    for column in range(size):
        pivot = max(range(column, size), key=lambda index: abs(rows[index][column]))
        if abs(rows[pivot][column]) < 1e-12:
            raise ValueError('degenerate camera calibration')
        rows[column], rows[pivot] = rows[pivot], rows[column]
        scale = rows[column][column]
        rows[column] = [value / scale for value in rows[column]]
        for index in range(size):
            if index != column:
                scale = rows[index][column]
                rows[index] = [a - scale * b for a, b in zip(rows[index], rows[column])]
    return [row[-1] for row in rows]


def homography(image_points, map_points):
    """Fit image-to-map homography from four coplanar point pairs."""
    if len(image_points) != 4 or len(map_points) != 4:
        raise ValueError('four point pairs required')
    matrix, values = [], []
    for (u, v), (x, y) in zip(image_points, map_points):
        matrix.extend(([u, v, 1, 0, 0, 0, -x * u, -x * v],
                       [0, 0, 0, u, v, 1, -y * u, -y * v]))
        values.extend((x, y))
    return _solve(matrix, values)


def project(coefficients, point):
    """Map one detected image foot point into metres."""
    u, v = point
    denominator = coefficients[6] * u + coefficients[7] * v + 1
    return ((coefficients[0] * u + coefficients[1] * v + coefficients[2]) / denominator,
            (coefficients[3] * u + coefficients[4] * v + coefficients[5]) / denominator)


def synthetic_centers(image):
    """Return connected magenta marker centres from a BGR8 simulator image."""
    if image.encoding != 'bgr8' or image.step < image.width * 3:
        return []
    data = image.data
    width, height = image.width, image.height
    active = set()
    for y in range(height):
        for x in range(width):
            offset = y * image.step + x * 3
            if data[offset] > 150 and data[offset + 1] < 100 and data[offset + 2] > 150:
                active.add((x, y))
    found = []
    while active:
        seed = active.pop()
        pending = [seed]
        pixels = [seed]
        while pending:
            x, y = pending.pop()
            for neighbor in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                if neighbor in active:
                    active.remove(neighbor)
                    pending.append(neighbor)
                    pixels.append(neighbor)
        if len(pixels) >= 4:
            found.append((sum(x for x, _ in pixels) / len(pixels),
                          max(y for _, y in pixels)))
    return sorted(found)


class Track:
    """Retain an identity across brief camera occlusion."""

    def __init__(self, identity, point, now):
        """Start an unconfirmed track."""
        self.identity = identity
        self.point = point
        self.first = self.last = now
        self.confirmed = False
        self.counted = False


class Tracker:
    """Debounce entries and exits without counting cumulative detections."""

    def __init__(self):
        """Initialize an empty image track set."""
        self.tracks = []
        self.next_id = 0

    def update(self, points, now):
        """Associate nearest observations and return entry/exit transitions."""
        available = set(range(len(points)))
        events = []
        for track in self.tracks:
            match = min(available, key=lambda i: math.dist(track.point, points[i]),
                        default=None)
            if match is not None and math.dist(track.point, points[match]) <= 0.55:
                track.point = points[match]
                track.last = now
                available.remove(match)
                if not track.confirmed and now - track.first >= 0.4:
                    track.confirmed = True
                    events.append(('entry', track))
        for index in sorted(available):
            self.tracks.append(Track(self.next_id, points[index], now))
            self.next_id += 1
        kept = []
        for track in self.tracks:
            if now - track.last > 0.5:
                if track.confirmed:
                    events.append(('exit', track))
            else:
                kept.append(track)
        self.tracks = kept
        return events

    def occupancy(self, now):
        """Count confirmed identities retained at most 0.5 s after last sighting."""
        visible = [track for track in self.tracks
                   if track.confirmed and now - track.last <= 0.5]
        queue = sum(2 <= track.point[0] <= 6 and 5 <= track.point[1] <= 7
                    for track in visible)
        crossing = any(4.5 <= track.point[0] <= 5.5 and
                       1.25 <= track.point[1] <= 4.75 for track in visible)
        return queue, crossing


class PassengerDetector(Node):
    """Publish the observed queue from simulator pixels at 5 Hz."""

    def __init__(self):
        """Configure four-point calibration and source-stamp watchdog."""
        super().__init__('passenger_detector')
        self.declare_parameter('queue_confidence_min', 0.5)
        self.declare_parameter('backend', 'synthetic')
        self.declare_parameter('image_points_px', [0.0, 0.0, 159.0, 0.0,
                                                   159.0, 95.0, 0.0, 95.0])
        self.declare_parameter('map_points_m', [0.0, 8.0, 12.0, 8.0,
                                                12.0, 0.0, 0.0, 0.0])
        self.confidence_min = float(self.get_parameter('queue_confidence_min').value)
        if not math.isfinite(self.confidence_min) or not 0 <= self.confidence_min <= 1:
            raise ValueError('queue_confidence_min must be in [0,1]')
        image_points = self.get_parameter('image_points_px').value
        map_points = self.get_parameter('map_points_m').value
        if len(image_points) != 8 or len(map_points) != 8:
            raise ValueError('camera calibration requires four point pairs')
        self.calibration = homography(
            list(zip(image_points[::2], image_points[1::2])),
            list(zip(map_points[::2], map_points[1::2])))
        backend = self.get_parameter('backend').value
        if backend not in ('synthetic', 'nanodet'):
            raise ValueError('backend must be synthetic or nanodet')
        self.backend = backend
        self.model = None
        if backend == 'nanodet':
            model_path = (get_package_share_directory('smart_hub_perception') +
                          '/models/object_detection_nanodet_2022nov.onnx')
            self.model = NanoDetPerson(model_path)
        self.tracker = Tracker()
        self.source_stamp = None
        self.source_header_stamp = None
        self.source_received = None
        self.run_id = ''
        self.publisher = self.create_publisher(QueueState, '/hub/queue', 10)
        self.events = self.create_publisher(HubEvent, '/hub/events', 100)
        self.create_subscription(Image, '/camera/image_raw', self.on_image,
                                 rclpy.qos.qos_profile_sensor_data)
        run_qos = rclpy.qos.QoSProfile(
            depth=1, durability=rclpy.qos.DurabilityPolicy.TRANSIENT_LOCAL)
        self.create_subscription(String, '/sim/run_id', self.on_run_id, run_qos)
        self.create_timer(0.2, self.publish)

    def on_run_id(self, message):
        """Tag observed track transitions with the simulator run identifier."""
        if message.data != self.run_id:
            self.run_id = message.data
            self.tracker = Tracker()
            self.source_stamp = self.source_header_stamp = self.source_received = None

    def on_image(self, image):
        """Ignore repeated acquisition stamps instead of restamping a frozen image."""
        stamp = image.header.stamp.sec + image.header.stamp.nanosec * 1e-9
        now = time.monotonic()
        source_age = self.get_clock().now().nanoseconds * 1e-9 - stamp
        if (image.header.frame_id != 'camera_link' or
                not 0 <= source_age <= 1.0 or
                self.source_stamp is not None and stamp <= self.source_stamp):
            return
        self.source_stamp = stamp
        self.source_header_stamp = image.header.stamp
        self.source_received = now
        feet = (synthetic_centers(image) if self.model is None else
                self.model.foot_points(image))
        points = [project(self.calibration, point) for point in feet]
        for transition, track in self.tracker.update(points, now):
            event = HubEvent()
            event.header.stamp = image.header.stamp
            event.header.frame_id = 'map'
            event.run_id = self.run_id
            event.scenario_id = 'perception'
            event.entity_id = f'person-{track.identity}'
            event.event = 'TRACK_' + transition.upper()
            event.reason = f'{track.point[0]:.3f},{track.point[1]:.3f}'
            self.events.publish(event)

    def publish(self):
        """Use the original source timestamp; invalidate silence or frozen feeds."""
        now = time.monotonic()
        message = QueueState()
        if self.source_stamp is not None:
            message.header.stamp = self.source_header_stamp
        message.header.frame_id = 'map'
        message.zone_id = 'Q'
        message.valid = (self.source_received is not None and
                         now - self.source_received <= 1.0)
        if message.valid:
            message.count, message.crossing_occupied = self.tracker.occupancy(now)
            message.confidence = 1.0
        self.publisher.publish(message)


def main(args=None):
    """Run the image-derived queue source."""
    rclpy.init(args=args)
    node = PassengerDetector()
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, rclpy.executors.ExternalShutdownException):
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
