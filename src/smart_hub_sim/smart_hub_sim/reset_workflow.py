"""Public scenario reset workflow owned by the simulator node."""

import json
import math
import time

from rcl_interfaces.msg import ParameterDescriptor
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.qos import DurabilityPolicy, QoSProfile
from rclpy.task import Future
from smart_hub_interfaces.msg import CrossingState, SafetyState
from smart_hub_interfaces.srv import ResetScenario


class ResetWorkflow:
    """Coordinate participant acknowledgements under one monotonic deadline."""

    def configure_reset(self, include_bus=False, include_m4=False, include_robot=False):
        """Register the public service and internal participant clients."""
        self.include_bus = include_bus
        self.include_m4 = include_m4
        # Design choice D11: 0.9 s keeps M2 inside the 1 s client timeout (A 7.1); the
        # assignment fixes no reset deadline, and mission graphs need ~1.2 s on the dev VM.
        default = 2.0 if include_bus or include_robot else 0.9
        self.declare_parameter('reset_deadline_sec', default,
                               ParameterDescriptor(read_only=True))
        self._reset_deadline_sec = float(self.get_parameter('reset_deadline_sec').value)
        if not math.isfinite(self._reset_deadline_sec) or not (
                0.0 < self._reset_deadline_sec <= 2.0):
            raise ValueError('reset_deadline_sec must be in (0, 2.0]')
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
        # Ordered stages; endpoints within one stage are independent and run concurrently.
        stages = [['/safety/reset_state'], ['/crossing/reset_state'], ['/sim/reset_world'],
                  ['/safety/finish_reset']]
        prepare = [name for name, enabled in (('/robot/prepare_reset', include_robot),
                                              ('/bus/prepare_reset', include_bus)) if enabled]
        finish = [name for name, enabled in (('/bus/finish_reset', include_bus),
                                             ('/robot/finish_reset', include_robot)) if enabled]
        if include_m4:
            stages.insert(2, ['/parking/reset_state', '/traffic/reset_state'])
        if finish:
            stages.insert(-1, finish)
        if prepare:
            stages.insert(0, prepare)
        self._stages = [
            [self.create_client(ResetScenario, endpoint, callback_group=self._reset_group)
             for endpoint in stage]
            for stage in stages]
        self._participants = [client for stage in self._stages for client in stage]
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
        deadline = started + self._reset_deadline_sec
        pending = []
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
            if time.monotonic() < deadline:
                return
            for client, future in pending:
                if not future.done():
                    if client is not None:
                        client.remove_pending_request(future)
                    future.set_exception(TimeoutError('RESET_DEADLINE'))

        async def observe(waiter_name, observed_phase):
            nonlocal phase
            future = Future(executor=self.executor)
            setattr(self, waiter_name, future)
            pending.append((None, future))
            phase = observed_phase
            trace('wait_for_observation')
            await future
            trace('observation_received')
            setattr(self, waiter_name, None)

        timer = self.create_timer(0.02, expire, callback_group=self._reset_group)
        trace('start', participants=[[c.srv_name for c in stage] for stage in self._stages])
        try:
            for stage in self._stages:
                phase = '+'.join(client.srv_name for client in stage)
                if time.monotonic() >= deadline:
                    raise TimeoutError('RESET_DEADLINE')
                requested_at = time.monotonic()
                trace('request')
                calls = [(client, None if client.srv_name == '/sim/reset_world'
                          else client.call_async(request)) for client in stage]
                pending[:] = [call for call in calls if call[1] is not None]
                for client, future in calls:
                    if future is None:
                        # This node owns the world reset; call its handler without a DDS hop.
                        acknowledgement = self._reset_scenario(
                            request, ResetScenario.Response())
                    else:
                        acknowledgement = await future
                    phase = client.srv_name
                    trace('acknowledgement', success=acknowledgement.success,
                          reason=acknowledgement.reason,
                          service_sec=time.monotonic() - requested_at)
                    if not acknowledgement.success:
                        response.reason = client.srv_name + ':' + acknowledgement.reason
                        trace('rejected', reason=response.reason)
                        return response
                    if acknowledgement.run_id:
                        response.run_id = acknowledgement.run_id
                if time.monotonic() >= deadline:
                    raise TimeoutError('RESET_DEADLINE')
                names = {client.srv_name for client in stage}
                if '/safety/reset_state' in names:
                    snapshot = self._reset_safety
                    if not (snapshot and snapshot[1] >= requested_at and
                            not snapshot[0].stop_latched and
                            snapshot[0].reason == 'reset_in_progress'):
                        await observe('_hold_waiter', '/hub/safety:reset_hold')
                if '/crossing/reset_state' in names:
                    snapshot = self._reset_crossing
                    if not (snapshot and snapshot[1] >= requested_at and
                            snapshot[0].valid and not snapshot[0].owner_id and
                            snapshot[0].state == 'CLEAR'):
                        await observe('_clear_waiter', '/crossing/state:clear')
            response.success = True
            response.reason = ('ALL_M4_PARTICIPANTS_ACKNOWLEDGED' if self.include_m4 else
                               'ALL_M3_PARTICIPANTS_ACKNOWLEDGED' if self.include_bus else
                               'ALL_M2_PARTICIPANTS_ACKNOWLEDGED')
            trace('complete', reason=response.reason)
        except Exception as error:
            response.reason = str(error)
            trace('failed', reason=response.reason)
        finally:
            for client, future in pending:
                if client is not None and not future.done():
                    client.remove_pending_request(future)
            self._hold_waiter = None
            self._clear_waiter = None
            self.destroy_timer(timer)
            with self._lock:
                self.busy = False
        return response
