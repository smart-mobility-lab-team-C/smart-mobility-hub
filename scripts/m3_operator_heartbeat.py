#!/usr/bin/env python3
"""Publish the M3 verifier's operator E-stop from an isolated ROS process."""

import argparse
from collections import deque
import json
import os
from pathlib import Path
import sys
import time

import rclpy
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile
from std_msgs.msg import Bool


def operator_state(current, parent_state, parent_alive, command=None):
    """Apply parent-fault precedence and explicit operator commands."""
    if not parent_alive:
        return True, True
    if parent_state in ('T', 't'):
        return True, False
    if command is not None:
        return bool(command), False
    return current, False


def read_process_state(pid):
    """Read Linux process state while handling spaces and parentheses in comm."""
    try:
        stat = Path(f'/proc/{pid}/stat').read_text()
    except OSError:
        return None
    closing_paren = stat.rfind(')')
    fields = stat[closing_paren + 1:].split()
    return fields[0] if closing_paren >= 0 and fields else None


class OperatorHeartbeat(Node):
    """Own the sole `/hub/estop` publisher and its fail-closed parent guard."""

    def __init__(self, parent_pid, output):
        """Start asserted, then retain bounded monotonic publication records."""
        super().__init__('m3_operator_heartbeat')
        qos = QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL)
        self.publisher = self.create_publisher(Bool, '/hub/estop', qos)
        self.parent_pid = parent_pid
        self.input_fd = sys.stdin.fileno()
        os.set_blocking(self.input_fd, False)
        self.input_buffer = b''
        self.records = deque(maxlen=30000)
        self.value = True
        self.exit_requested = False
        self.parent_lost_at = None
        self.command = None
        self.command_reply = None
        self.timer = self.create_timer(0.1, self.tick)

    def publish(self):
        """Publish current authority state and retain timing without file I/O."""
        started = time.monotonic()
        self.publisher.publish(Bool(data=self.value))
        returned = time.monotonic()
        self.records.append({
            'started': started,
            'returned': returned,
            'stop': self.value,
        })

    def reply(self, message):
        """Write one small command acknowledgement to the parent pipe."""
        sys.stdout.write(json.dumps(message, separators=(',', ':')) + '\n')
        sys.stdout.flush()

    def read_commands(self):
        """Read available commands without blocking the ROS heartbeat timer."""
        while True:
            try:
                chunk = os.read(self.input_fd, 4096)
            except BlockingIOError:
                break
            if not chunk:
                self.parent_lost_at = self.parent_lost_at or time.monotonic()
                self.command = True
                break
            self.input_buffer += chunk
        while b'\n' in self.input_buffer:
            line, self.input_buffer = self.input_buffer.split(b'\n', 1)
            if not line:
                continue
            request = json.loads(line)
            operation = request.get('operation')
            if operation == 'set' and isinstance(request.get('value'), bool):
                self.command = request['value']
                self.command_reply = {'id': request['id'], 'ok': True}
            elif operation == 'shutdown':
                self.command = True
                self.command_reply = {'id': request['id'], 'ok': True}
                self.exit_requested = True
            else:
                self.command_reply = {
                    'id': request.get('id'),
                    'ok': False,
                    'error': 'invalid operator command',
                }

    def tick(self):
        """Refresh E-stop and stop authority if the verifier is suspended or gone."""
        self.read_commands()
        parent_state = read_process_state(self.parent_pid)
        parent_alive = (
            os.getppid() == self.parent_pid and parent_state not in (None, 'Z', 'X')
        )
        self.value, parent_exited = operator_state(
            self.value, parent_state, parent_alive, self.command
        )
        self.command = None
        self.publish()
        if self.command_reply is not None:
            self.command_reply['published'] = self.value
            self.reply(self.command_reply)
            self.command_reply = None
        if parent_exited:
            self.parent_lost_at = self.parent_lost_at or time.monotonic()
        if self.parent_lost_at is not None:
            if time.monotonic() - self.parent_lost_at >= 1.0:
                self.exit_requested = True

    def write_records(self, output_path):
        """Flush retained records only after the publisher has stopped."""
        Path(output_path).write_text(
            ''.join(json.dumps(record, separators=(',', ':')) + '\n'
                    for record in self.records)
        )


def main():
    """Run the independent publisher until explicit shutdown or parent loss."""
    parser = argparse.ArgumentParser()
    parser.add_argument('--parent-pid', required=True, type=int)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    rclpy.init()
    node = OperatorHeartbeat(args.parent_pid, args.output)
    try:
        node.publish()
        node.reply({'event': 'ready', 'published': True})
        while rclpy.ok() and not node.exit_requested:
            rclpy.spin_once(node, timeout_sec=0.02)
    finally:
        node.destroy_node()
        node.write_records(args.output)
        rclpy.shutdown()


if __name__ == '__main__':
    main()
