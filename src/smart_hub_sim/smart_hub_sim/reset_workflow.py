"""Public scenario reset workflow owned by the simulator node."""

import json
import time

from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.qos import DurabilityPolicy, QoSProfile
from rclpy.task import Future
from smart_hub_interfaces.msg import CrossingState, SafetyState
from smart_hub_interfaces.srv import ResetScenario


class ResetWorkflow:
    """Coordinate participant acknowledgements under one monotonic deadline."""

    def configure_reset(self, include_bus=False, include_m4=False):
        """Register the public service and internal participant clients."""
        self.include_bus = include_bus
        self.include_m4 = include_m4
        self.busy = False
        self._reset_crossing = None
        self._reset_safety = None
        self._hold_waiter = None
        self._clear_waiter = None
        qos = QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL)
        # Reset observations must not queue behind simulator stepping callbacks.
        self._reset_group = ReentrantCallbackGroup()
        self.create_subscription(CrossingState, '/crossing/state',
                                 self._reset_on_crossing, qos,
                                 callback_group=self._reset_group)
        self.create_subscription(SafetyState, '/hub/safety', self._reset_on_safety, qos,
                                 callback_group=self._reset_group)
        endpoints = ('/safety/reset_state', '/crossing/reset_state',
                     '/sim/reset_world', '/safety/finish_reset')
        if include_bus:
            endpoints = ('/bus/prepare_reset', *endpoints[:-1],
                         '/bus/finish_reset', endpoints[-1])
        if include_m4:
            index = endpoints.index('/sim/reset_world')
            endpoints = (*endpoints[:index], '/parking/reset_state',
                         '/traffic/reset_state', *endpoints[index:])
        self._participants = [
            self.create_client(ResetScenario, endpoint, callback_group=self._reset_group)
            for endpoint in endpoints]
        self.create_service(ResetScenario, '/scenario/reset', self.reset,
                            callback_group=self._reset_group)

    def _reset_on_crossing(self, message):
        """Observe the published clear state after participant acknowledgment."""
        self._reset_crossing = (message, time.monotonic())
        self._crossing_state(message)
        if self._clear_waiter is not None and not self._clear_waiter.done():
            if message.valid and not message.owner_id and message.state == 'CLEAR':
                self._clear_waiter.set_result(True)

    def _reset_on_safety(self, message):
        """Observe the published supervisor reset hold."""
        self._reset_safety = (message, time.monotonic())
        self._safety_state(message)
        if self._hold_waiter is not None and not self._hold_waiter.done():
            if not message.stop_latched and message.reason == 'reset_in_progress':
                self._hold_waiter.set_result(True)

    async def reset(self, request, response):
        """Acknowledge all launched participants before returning success."""
        response.success = False
        if request.scenario_id != 'm2_baseline':
            response.reason = 'UNKNOWN_SCENARIO'
            return response
        with self._lock:
            if self.busy:
                response.reason = 'RESET_BUSY'
                return response
            if not all(client.service_is_ready() for client in self._participants):
                response.reason = 'PARTICIPANT_UNAVAILABLE'
                return response
            self.busy = True
        started = time.monotonic()
        # Leave response margin inside the 1 s client timeout (assignment section 7.1).
        deadline = started + 0.9
        future = None
        active_client = None
        phase = 'start'

        def trace(event, **fields):
            print(json.dumps({
                'event': 'scenario_reset_' + event,
                'phase': phase,
                'elapsed_sec': time.monotonic() - started,
                'seed': request.seed,
                **fields,
            }, sort_keys=True), flush=True)

        def expire():
            if future is not None and not future.done() and time.monotonic() >= deadline:
                if active_client is not None:
                    active_client.remove_pending_request(future)
                future.set_exception(TimeoutError('RESET_DEADLINE'))

        timer = self.create_timer(0.02, expire, callback_group=self._reset_group)
        trace('start', participants=[client.srv_name for client in self._participants])
        try:
            for client in self._participants:
                phase = client.srv_name
                if time.monotonic() >= deadline:
                    raise TimeoutError('RESET_DEADLINE')
                requested_at = time.monotonic()
                active_client = client
                trace('request')
                future = client.call_async(request)
                acknowledgement = await future
                trace('acknowledgement', success=acknowledgement.success,
                      reason=acknowledgement.reason,
                      service_sec=time.monotonic() - requested_at)
                if time.monotonic() >= deadline:
                    raise TimeoutError('RESET_DEADLINE')
                if not acknowledgement.success:
                    response.reason = client.srv_name + ':' + acknowledgement.reason
                    trace('rejected', reason=response.reason)
                    return response
                if client.srv_name == '/safety/reset_state':
                    snapshot = self._reset_safety
                    if not (snapshot and snapshot[1] >= requested_at and
                            not snapshot[0].stop_latched and
                            snapshot[0].reason == 'reset_in_progress'):
                        active_client = None
                        future = Future(executor=self.executor)
                        self._hold_waiter = future
                        phase = '/hub/safety:reset_hold'
                        trace('wait_for_observation')
                        await future
                        trace('observation_received')
                        self._hold_waiter = None
                if client.srv_name == '/crossing/reset_state':
                    snapshot = self._reset_crossing
                    if not (snapshot and snapshot[1] >= requested_at and
                            snapshot[0].valid and not snapshot[0].owner_id and
                            snapshot[0].state == 'CLEAR'):
                        active_client = None
                        future = Future(executor=self.executor)
                        self._clear_waiter = future
                        phase = '/crossing/state:clear'
                        trace('wait_for_observation')
                        await future
                        trace('observation_received')
                        self._clear_waiter = None
                if acknowledgement.run_id:
                    response.run_id = acknowledgement.run_id
            response.success = True
            response.reason = ('ALL_M4_PARTICIPANTS_ACKNOWLEDGED' if self.include_m4 else
                               'ALL_M3_PARTICIPANTS_ACKNOWLEDGED' if self.include_bus else
                               'ALL_M2_PARTICIPANTS_ACKNOWLEDGED')
            trace('complete', reason=response.reason)
        except Exception as error:
            response.reason = str(error)
            trace('failed', reason=response.reason)
        finally:
            self._hold_waiter = None
            self._clear_waiter = None
            self.destroy_timer(timer)
            with self._lock:
                self.busy = False
        return response
