"""Opt-in diagnostic boundaries; never loaded by production ROS entry points."""

import time

from gap_tools import timed


def source_seconds(message):
    """Return the computation stamp carried by a crossing state."""
    stamp = message.header.stamp
    return stamp.sec + stamp.nanosec * 1e-9


def install(kind, role, recorder):
    """Instrument crossing publication, DDS take and subscriber execution unchanged."""
    from rclpy.executors import Executor
    from rclpy.publisher import Publisher

    original_publish = Publisher.publish

    def publish(self, message):
        if self.topic_name != '/crossing/state':
            return original_publish(self, message)
        started = time.monotonic()
        cpu = time.thread_time()
        recorder.emit('crossing.publish', phase='start', source_wall=source_seconds(message))
        try:
            return original_publish(self, message)
        finally:
            recorder.emit('crossing.publish', phase='end', source_wall=source_seconds(message),
                          duration=time.monotonic() - started, cpu=time.thread_time() - cpu)

    Publisher.publish = publish
    original_ready = Executor.wait_for_ready_callbacks

    def ready(self, *args, **kwargs):
        result = original_ready(self, *args, **kwargs)
        _, entity, _ = result
        topic = getattr(entity, 'topic_name', None)
        period = getattr(entity, 'timer_period_ns', None)
        if topic == '/crossing/state' or period is not None:
            recorder.emit('executor.ready', topic=topic, timer_period_ns=period,
                          entity=id(entity))
        return result

    Executor.wait_for_ready_callbacks = ready
    original_take = Executor._take_subscription

    def take(self, subscription):
        if subscription.topic_name != '/crossing/state':
            return original_take(self, subscription)
        recorder.emit('crossing.take', phase='start', entity=id(subscription))
        try:
            return original_take(self, subscription)
        finally:
            recorder.emit('crossing.take', phase='end', entity=id(subscription))

    Executor._take_subscription = take
    original_init = kind.__init__

    def initialize(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        if role == 'safety_supervisor':
            for subscription in self.subscriptions:
                if subscription.topic_name == '/crossing/state':
                    original_callback = subscription.callback

                    def receive(message, info):
                        recorder.emit('crossing.receive', source_wall=source_seconds(message),
                                      middleware_info={key: info.get(key) for key in (
                                          'source_timestamp', 'received_timestamp',
                                          'publication_sequence_number',
                                          'reception_sequence_number')})
                        return original_callback(message)

                    subscription.callback = receive

    kind.__init__ = initialize
    method = 'tick' if role == 'crossing_arbiter' else '_tick'
    setattr(kind, method, timed(recorder, role + '.tick', getattr(kind, method)))
    if role == 'safety_supervisor':
        original_fresh = kind._fresh_record

        def fresh(self, key, limit, stamped=True):
            result = original_fresh(self, key, limit, stamped)
            if key == 'crossing':
                sample = self._data.get(key)
                recorder.emit('crossing.freshness', reason=result[1], limit=limit,
                              receipt_age=time.monotonic() - sample[1] if sample else None,
                              source_age=self._now_ros() - source_seconds(sample[0])
                              if sample else None,
                              source_wall=source_seconds(sample[0]) if sample else None)
            return result

        kind._fresh_record = fresh
