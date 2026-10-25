"""Bounded diagnostic events; no recorder I/O, threads or timers while ROS runs."""

from collections import deque
from functools import wraps
import importlib
import json
from pathlib import Path
import threading
import time


class Ring:
    """Keep per-thread history, including callback entry before a blocking acquire."""

    def __init__(self, path, layer, capacity=16384):
        """Bound both thread count and records; serialize only after node shutdown."""
        self.path, self.layer, self.capacity = Path(path), layer, capacity
        self.buffers, self.overwritten, self.triggers = {}, {}, deque(maxlen=16)
        self.thread_overflow = 0
        self.trigger_overflow = 0

    def add(self, stage, *values):
        """Append a monotonic tuple without locks, formatting or system calls for I/O."""
        tid = threading.get_native_id()
        if tid not in self.buffers:
            if len(self.buffers) >= 16:
                self.thread_overflow += 1
                return
            self.buffers[tid], self.overwritten[tid] = deque(maxlen=self.capacity), 0
        buffer = self.buffers[tid]
        if len(buffer) == self.capacity:
            self.overwritten[tid] += 1
        buffer.append((time.monotonic_ns(), tid, stage, values))

    def trigger(self, reason):
        """Mark failures without freezing away records when blocked callbacks resume."""
        if len(self.triggers) == self.triggers.maxlen:
            self.trigger_overflow += 1
        self.triggers.append((time.monotonic_ns(), reason))
        self.add('trigger', reason)

    def close(self):
        """Flush bounded history only after executor shutdown or probe spin ends."""
        records = sorted(record for buffer in self.buffers.values() for record in buffer)
        header = {'layer': self.layer, 'clock': 'monotonic_ns',
                  'capacity_per_thread': self.capacity,
                  'triggers': list(self.triggers), 'overwritten': self.overwritten,
                  'thread_overflow': self.thread_overflow,
                  'trigger_overflow': self.trigger_overflow,
                  'thread_ranges': {tid: [b[0][0], b[-1][0]] for tid, b in self.buffers.items()
                                    if b}}
        with self.path.open('w') as stream:
            stream.write(json.dumps(header) + '\n')
            for record in records:
                stream.write(json.dumps(record) + '\n')


class TracedLock:
    """Delegate the original RLock, retaining its reentrancy and acquisition semantics."""

    def __init__(self, original, ring):
        """Keep diagnostic ownership separate from the actual lock authority."""
        self.original, self.ring = original, ring
        self.owner, self.depth = None, 0
        self.local = threading.local()

    def acquire(self, *args, **kwargs):
        """Measure the acquire call; its wall duration also includes descheduling."""
        token = time.monotonic_ns()
        self.ring.add('lock.request', token, self.owner)
        acquired = self.original.acquire(*args, **kwargs)
        if acquired:
            self.owner, self.depth = threading.get_native_id(), self.depth + 1
            if not hasattr(self.local, 'tokens'):
                self.local.tokens = []
            self.local.tokens.append(token)
        self.ring.add('lock.acquired', token, acquired)
        return acquired

    def release(self):
        """Record before/after release; avoid attributing scheduling time solely to waiting."""
        if not getattr(self.local, 'tokens', None):
            return self.original.release()
        token = self.local.tokens.pop()
        self.ring.add('lock.release_start', token)
        self.depth -= 1
        if not self.depth:
            self.owner = None
        self.original.release()
        self.ring.add('lock.released', token)

    def __enter__(self):
        """Preserve context manager locking."""
        return self.acquire()

    def __exit__(self, *_):
        """Release once for each successful context entry."""
        self.release()


def around(kind, name, ring, stage):
    """Retain callback entry and return around the original, unchanged function."""
    original = getattr(kind, name)

    @wraps(original)
    def invoke(*args, **kwargs):
        token = time.monotonic_ns()
        ring.add(stage + '.enter', token)
        try:
            return original(*args, **kwargs)
        finally:
            ring.add(stage + '.exit', token)

    setattr(kind, name, invoke)


def worker(args):
    """Load production classes with opt-in diagnostic wrappers only in this child."""
    from rclpy.publisher import Publisher

    modules = {'bus_manager': ('smart_hub_control.bus', 'BusManager'),
               'crossing_arbiter': ('smart_hub_control.crossing', 'CrossingArbiter'),
               'safety_supervisor': ('smart_hub_safety.supervisor', 'SafetySupervisor'),
               'scenario_runner': ('smart_hub_sim.scenario_runner', 'ScenarioRunner')}
    module_name, class_name = modules[args.worker]
    module = importlib.import_module(module_name)
    kind, ring = getattr(module, class_name), Ring(args.output, args.worker)
    topics = {'scenario_runner': ('/bus/door_open',), 'crossing_arbiter': ('/crossing/state',),
              'bus_manager': ('/bus/cmd_vel_candidate', '/bus/door_request'),
              'safety_supervisor': ()}[args.worker]
    original_publish = Publisher.publish

    def publish(self, message):
        if self.topic_name not in topics:
            return original_publish(self, message)
        token = time.monotonic_ns()
        stamp = getattr(getattr(message, 'header', None), 'stamp', None)
        source = stamp.sec * 10**9 + stamp.nanosec if stamp else None
        ring.add('publish.enter', token, self.topic_name, source)
        try:
            return original_publish(self, message)
        finally:
            ring.add('publish.exit', token, self.topic_name)

    Publisher.publish = publish
    original_init = kind.__init__

    def initialize(self, *positional, **keywords):
        original_init(self, *positional, **keywords)
        if args.worker == 'bus_manager':
            self.lock = TracedLock(self.lock, ring)
        if args.worker == 'safety_supervisor':
            for subscription in self.subscriptions:
                if subscription.topic_name == '/crossing/state':
                    original = subscription.callback

                    def receive(message):
                        stamp = message.header.stamp
                        ring.add('crossing.receive', stamp.sec * 10**9 + stamp.nanosec)
                        return original(message)

                    subscription.callback = receive

    kind.__init__ = initialize
    if args.worker == 'bus_manager':
        around(kind, 'tick', ring, 'control.callback')
        around(kind, 'control_tick', ring, 'control.body')
        around(kind, 'publish_state', ring, 'executor.heartbeat')
        original_record, original_state, original_stop = kind.record, kind.state, kind.begin_stop

        def record(self, key, message):
            ring.add('input.enter', key)
            result = original_record(self, key, message)
            if key == 'door':
                ring.add('door.cache', self.samples[key][1], message.data)
            ring.add('input.exit', key)
            return result

        def state(self, key, ttl=1.0):
            result = original_state(self, key, ttl)
            if key == 'door':
                sample = self.samples.get(key)
                ring.add('door.check', sample[1] if sample else None, ttl, result is not None)
            return result

        def stop(self, reason):
            if not self.stop_reason:
                ring.trigger(reason)
            return original_stop(self, reason)

        kind.record, kind.state, kind.begin_stop = record, state, stop
    elif args.worker == 'safety_supervisor':
        original_fresh = kind._fresh_record

        def fresh(self, key, limit, stamped=True):
            result = original_fresh(self, key, limit, stamped)
            if key == 'crossing':
                sample = self._data.get(key)
                ring.add('crossing.check', sample[1] if sample else None, result[1])
                if result[1] == 'crossing_stale':
                    ring.trigger(result[1])
            return result

        kind._fresh_record = fresh
    try:
        module.main(args=['--ros-args', '-p', 'm3_mode:=true']
                    if args.worker == 'scenario_runner' else [])
    finally:
        ring.close()


def prepare_probe(ring):
    """Reuse the existing mission client with memory-only observations and operator input."""
    import math
    from smart_hub_interfaces.action import DockBus
    from std_msgs.msg import Bool
    import verify_m3

    class Sink:
        name = str(ring.path.parent / 'trace.jsonl')

        def write(self, value):
            return len(value)

        def close(self):
            pass

    class NoJson:
        @staticmethod
        def dumps(*args, **kwargs):
            return ''

    verify_m3.json = NoJson
    original_init = verify_m3.Probe.__init__

    def initialize(self, directory):
        original_init(self, directory)
        self.output.close()
        self.output = Sink()

    def record(self, name, message):
        now = time.monotonic()
        self.samples[name] = message
        self.history[name].append((now, message))
        if name == 'door':
            ring.add('observer.door', message.data)
        elif name == 'safety':
            ring.add('observer.safety', message.reason)
        elif name == 'event':
            ring.add('observer.event', message.entity_id, message.event, message.reason)

    def heartbeat(self):
        next_publish = time.monotonic()
        while not self.heartbeat_stop.is_set() and self.context.ok():
            try:
                self.heartbeat.publish(Bool(data=self.estop))
            except Exception:
                if not self.context.ok():
                    return
                raise
            next_publish += .1
            now = time.monotonic()
            if next_publish <= now:
                next_publish += (math.floor((now - next_publish) / .1) + 1) * .1
            self.heartbeat_stop.wait(max(0., next_publish - now))

    def send(self, duration=180.0):
        goal = DockBus.Goal(bus_id='bus', bay_id='B', max_duration_sec=float(duration))
        handle = self.future(self.action.send_goal_async(goal))
        assert handle.accepted, 'goal unexpectedly rejected'
        ring.add('goal.accepted')
        return handle, handle.get_result_async()

    verify_m3.Probe.__init__ = initialize
    verify_m3.Probe.record = record
    verify_m3.Probe.operator_heartbeat = heartbeat
    verify_m3.Probe.send = send
