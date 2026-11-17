#!/usr/bin/env python3
"""Custom S10 (team scenario): parking request retry after a lost acknowledgement.

Situation: vehicle C1 asks for a parking space, the reservation is made, but the
client never processes the reply (lost acknowledgement) and resends the identical
request. The hub must hand back the original reservation, not a second space.

Reuses the existing M4 graph (`m4.launch.py`) and the real `/parking/reserve_slot`
service; no production code is involved beyond what S4 already uses. S4/T07 verifies
request-ID idempotency in general; S10 is the end-to-end client-retry situation.

PASS requires: the first request succeeds; the retry returns the same reservation ID
and slot; exactly one RESERVED slot belongs to C1 in /parking/state; the number of
available slots dropped by exactly one; a different request ID for C1 is refused
(no second allocation). Anything else is FAIL; missing graph is BLOCKED.
"""

import argparse
import json
from pathlib import Path
import subprocess
import time

import rclpy
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile
from rosidl_runtime_py.convert import message_to_ordereddict
from smart_hub_interfaces.msg import ParkingState
from smart_hub_interfaces.srv import ReserveParking
from verification import signal_group


class Probe(Node):
    """Act as the parking client and watch the published parking state."""

    def __init__(self):
        super().__init__('s10_parking_retry_probe')
        self.state = None
        self.create_subscription(ParkingState, '/parking/state', self._state,
                                 QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL))
        self.reserve = self.create_client(ReserveParking, '/parking/reserve_slot')

    def _state(self, message):
        self.state = message

    def wait(self, predicate, seconds):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if predicate():
                return True
            rclpy.spin_once(self, timeout_sec=0.05)
        return bool(predicate())

    def call(self, request_id, vehicle):
        future = self.reserve.call_async(ReserveParking.Request(
            request_id=request_id, vehicle_id=vehicle, preferred_slot='', ttl_sec=60.0))
        assert self.wait(future.done, 3), 'reserve_slot did not answer within 3 s'
        return future.result()


def slots(state):
    return {s.slot_id: (s.state, s.vehicle_id, s.reservation_id) for s in state.slots}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    report = {'schema': 'smart-mobility-hub/s10-verification-v1',
              'scenario': 'S10 parking request retry after lost acknowledgement (team scenario)',
              'graph': 'ros2 launch smart_hub_bringup m4.launch.py seed:=17',
              'status': 'BLOCKED', 'checks': {}, 'steps': []}
    started = time.monotonic()
    log = output.with_suffix('.launch.log').open('w')
    launch = subprocess.Popen(['ros2', 'launch', 'smart_hub_bringup', 'm4.launch.py', 'seed:=17'],
                              stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    rclpy.init()
    probe = Probe()

    def step(text, **data):
        entry = {'t': round(time.monotonic() - started, 3), 'step': text, **data}
        report['steps'].append(entry)
        print(f"[{entry['t']:6.2f} s] {text}" + (f'  {json.dumps(data)}' if data else ''),
              flush=True)

    try:
        ready = probe.wait(lambda: probe.reserve.service_is_ready() and probe.state is not None
                           and slots(probe.state).get('P2', ('',))[0] == 'FREE', 25)
        if not ready:
            raise RuntimeError('parking graph not ready within 25 s')
        before = slots(probe.state)
        free_before = probe.state.available_count
        step('parking ready', slots={k: v[0] for k, v in before.items()},
             available=free_before)

        first = probe.call('s10-C1-req-001', 'C1')
        step('1. C1 sends reservation request s10-C1-req-001')
        step('   reply arrives but the client DISCARDS it (lost acknowledgement)',
             hidden_reply={'success': first.success, 'slot': first.slot_id,
                           'reservation_id': first.reservation_id, 'reason': first.reason})

        retry = probe.call('s10-C1-req-001', 'C1')
        step('2. C1 retries the identical request (same request ID)',
             reply={'success': retry.success, 'slot': retry.slot_id,
                    'reservation_id': retry.reservation_id, 'reason': retry.reason})

        other = probe.call('s10-C1-req-002', 'C1')
        step('3. control: C1 asks again with a NEW request ID',
             reply={'success': other.success, 'slot': other.slot_id, 'reason': other.reason})

        probe.wait(lambda: False, 1.5)   # let /parking/state reflect the reservation
        after = slots(probe.state)
        held = [k for k, (state, vehicle, _) in after.items()
                if vehicle == 'C1' and state == 'RESERVED']
        free_after = probe.state.available_count
        step('4. /parking/state after the retry', slots={k: list(v) for k, v in after.items()},
             available=free_after)

        checks = {
            'first_request_succeeded': first.success,
            'retry_same_reservation_id': retry.reservation_id == first.reservation_id != '',
            'retry_same_slot': retry.slot_id == first.slot_id != '',
            'exactly_one_slot_reserved_for_C1': held == [first.slot_id],
            'available_dropped_by_exactly_one': free_before - free_after == 1,
            'new_request_id_refused_no_second_space': (not other.success and
                                                       other.reason == 'VEHICLE_ALREADY_RESERVED'),
        }
        report['checks'] = checks
        report['status'] = 'PASS' if all(checks.values()) else 'FAIL'
        report['parking_state_after'] = message_to_ordereddict(probe.state)
    except Exception as error:
        report['status'] = 'BLOCKED' if 'not ready' in str(error) else 'FAIL'
        report['error'] = repr(error)
    finally:
        probe.destroy_node()
        rclpy.shutdown()
        signal_group(launch, 2)
        try:
            launch.wait(timeout=8)
        except subprocess.TimeoutExpired:
            signal_group(launch, 9)
        log.close()
        report['elapsed_sec'] = round(time.monotonic() - started, 2)
        output.write_text(json.dumps(report, indent=2) + '\n')
    print('\nChecks:')
    for name, ok in report['checks'].items():
        print(f"  {'PASS' if ok else 'FAIL'}  {name}")
    print(f"\nS10 {report['status']}  ({report['elapsed_sec']} s)  report: {output}", flush=True)
    raise SystemExit({'PASS': 0, 'FAIL': 1, 'BLOCKED': 2}[report['status']])


if __name__ == '__main__':
    main()
