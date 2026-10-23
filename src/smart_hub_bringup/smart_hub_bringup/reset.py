"""Coordinate explicit M2 reset acknowledgements with one bounded deadline."""
import json
import time

import rclpy
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile
from rclpy.task import Future
from smart_hub_interfaces.msg import CrossingState, SafetyState
from smart_hub_interfaces.srv import ResetScenario


class ResetCoordinator(Node):
    """Reset only the baseline participants; later milestones must extend this list."""

    def __init__(self):
        """Create asynchronous clients without blocking executor callbacks."""
        super().__init__('reset_coordinator')
        self.declare_parameter('include_bus', False)
        self.declare_parameter('include_m4', False)
        self.include_m4 = bool(self.get_parameter('include_m4').value)
        self.include_bus = bool(self.get_parameter('include_bus').value)
        self.busy = False
        self._crossing = None
        self._safety = None
        self._hold_waiter = None
        self._clear_waiter = None
        qos = QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL)
        self.create_subscription(CrossingState, '/crossing/state',
                                 self.on_crossing, qos)
        self.create_subscription(SafetyState, '/hub/safety', self.on_safety, qos)
        self.group = ReentrantCallbackGroup()
        endpoints = ('/safety/reset_state', '/crossing/reset_state',
                     '/sim/reset_world', '/safety/finish_reset')
        if self.include_bus:
            endpoints = ('/bus/prepare_reset', *endpoints[:-1],
                         '/bus/finish_reset', endpoints[-1])
        if self.include_m4:
            insert_at = endpoints.index('/sim/reset_world')
            endpoints = (*endpoints[:insert_at], '/parking/reset_state',
                         '/traffic/reset_state', *endpoints[insert_at:])
        self._participants = [
            self.create_client(ResetScenario, endpoint, callback_group=self.group)
            for endpoint in endpoints]
        self.create_service(ResetScenario, '/scenario/reset', self.reset,
                            callback_group=self.group)

    def on_crossing(self, message):
        """Observe acknowledgement publication independently of service delivery."""
        self._crossing = (message, time.monotonic())
        if self._clear_waiter is not None and not self._clear_waiter.done():
            if message.valid and not message.owner_id and message.state == 'CLEAR':
                self._clear_waiter.set_result(True)

    def on_safety(self, message):
        """Wait for an observed zero-output hold before resetting any peer."""
        self._safety = (message, time.monotonic())
        if self._hold_waiter is not None and not self._hold_waiter.done():
            if not message.stop_latched and message.reason == 'reset_in_progress':
                self._hold_waiter.set_result(True)

    async def reset(self, request, response):
        """Return success only after each safe-state acknowledgement arrives."""
        response.success = False
        if request.scenario_id != 'm2_baseline':
            response.reason = 'UNKNOWN_SCENARIO'
            return response
        if self.busy:
            response.reason = 'RESET_BUSY'
            return response
        if not all(client.service_is_ready() for client in self._participants):
            response.reason = 'PARTICIPANT_UNAVAILABLE'
            return response
        self.busy = True
        started = time.monotonic()
        deadline = started + 1.0
        timer = None
        future = None
        active_client = None
        phase = 'start'

        def trace(event, **fields):
            self.get_logger().info(json.dumps({
                'event': 'scenario_reset_' + event,
                'phase': phase,
                'elapsed_sec': time.monotonic() - started,
                'seed': request.seed,
                **fields,
            }, sort_keys=True))

        def expire():
            if future is not None and not future.done() and time.monotonic() >= deadline:
                if active_client is not None:
                    active_client.remove_pending_request(future)
                future.set_exception(TimeoutError('RESET_DEADLINE'))

        timer = self.create_timer(0.02, expire)
        trace('start', participants=[client.srv_name for client in self._participants])
        try:
            for index, client in enumerate(self._participants):
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
                    snapshot = self._safety
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
                    snapshot = self._crossing
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
            self.busy = False
        return response


def main(args=None):
    """Run the M2 reset coordinator."""
    rclpy.init(args=args)
    node = ResetCoordinator()
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, rclpy.executors.ExternalShutdownException):
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
