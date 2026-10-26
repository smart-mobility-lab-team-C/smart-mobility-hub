#!/usr/bin/env python3
"""Show or extract hub events for demo recordings (no control authority).

  demo_events.py view START_NS          print /hub/events and /hub/safety as they arrive
  demo_events.py cues BAG_DIR OUT_CSV   write a cue sheet from a recorded bag

Times are seconds since START_NS (the bag start), taken from message header stamps,
so the on-screen log and the cue sheet use the same clock. Safety lines appear on every
state change; an event line seen less than REPEAT_SEC earlier (periodic renewals) is skipped.
"""
import csv
import sys

REPEAT_SEC = 1.0
VIEW_WIDTH = 58   # on-screen lines are cut to fit; the cue sheet keeps them whole


class RepeatFilter:
    """Pass safety changes, and event lines not seen in the last REPEAT_SEC."""

    def __init__(self):
        self.seen, self.safety = {}, None

    def __call__(self, topic, line, t):
        if topic == '/hub/safety':
            changed, self.safety = line != self.safety, line
            return changed
        previous = self.seen.get(line)
        self.seen[line] = t
        return previous is None or t - previous >= REPEAT_SEC


def describe(topic, msg):
    """One-line summary of an event or safety message."""
    if topic == '/hub/events':
        text = f'{msg.entity_id} {msg.event}'
        return text + (f' ({msg.reason})' if msg.reason else '')
    state = 'LATCHED' if msg.stop_latched else ('MOTION OK' if msg.motion_permitted else 'HOLD')
    return f'safety {state}' + (f' ({msg.reason})' if msg.reason else '')


def seconds(stamp, start_ns):
    return (stamp.sec * 1_000_000_000 + stamp.nanosec - start_ns) / 1e9


def view(start_ns):
    import rclpy
    from rclpy.node import Node
    from rclpy.qos import DurabilityPolicy, QoSProfile
    from smart_hub_interfaces.msg import HubEvent, SafetyState

    rclpy.init()
    node = Node('demo_event_view')
    keep = RepeatFilter()

    def show(topic, msg):
        line, t = describe(topic, msg), seconds(msg.header.stamp, start_ns)
        if keep(topic, line, t):
            text = line if len(line) <= VIEW_WIDTH else line[:VIEW_WIDTH - 3] + '...'
            print(f'{t:7.2f} s  {text}', flush=True)

    transient = QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL)
    node.create_subscription(HubEvent, '/hub/events', lambda m: show('/hub/events', m), 100)
    node.create_subscription(SafetyState, '/hub/safety', lambda m: show('/hub/safety', m), transient)
    print('Smart Mobility Hub events\n', flush=True)
    rclpy.spin(node)


def cues(bag_dir, out_csv):
    import rosbag2_py
    from rclpy.serialization import deserialize_message
    from smart_hub_interfaces.msg import HubEvent, SafetyState

    reader = rosbag2_py.SequentialReader()
    reader.open(rosbag2_py.StorageOptions(uri=bag_dir), rosbag2_py.ConverterOptions('', ''))
    start_ns = reader.get_metadata().starting_time.nanoseconds
    kinds = {'/hub/events': HubEvent, '/hub/safety': SafetyState}
    keep = RepeatFilter()
    with open(out_csv, 'w', newline='') as handle:
        writer = csv.writer(handle)
        writer.writerow(['t_sec', 'topic', 'description'])
        while reader.has_next():
            topic, data, _ = reader.read_next()
            if topic not in kinds:
                continue
            msg = deserialize_message(data, kinds[topic])
            line, t = describe(topic, msg), seconds(msg.header.stamp, start_ns)
            if keep(topic, line, t):
                writer.writerow([f'{t:.2f}', topic, line])
    print(start_ns)


if __name__ == '__main__':
    if len(sys.argv) == 3 and sys.argv[1] == 'view':
        view(int(sys.argv[2]))
    elif len(sys.argv) == 4 and sys.argv[1] == 'cues':
        cues(sys.argv[2], sys.argv[3])
    else:
        sys.exit(__doc__)
