#!/usr/bin/env python3
"""Inspect generated ROS Python fields after sourcing the M1 install."""
import json
from pathlib import Path
import subprocess

from rosidl_runtime_py.utilities import get_action, get_message, get_service

ROOT = Path(__file__).resolve().parents[1]


def normalize(value):
    """Normalize rosidl's qualified names without weakening field type checks."""
    value = value.replace('/msg/', '/')
    if value == 'bool':
        value = 'boolean'
    if value.endswith('[]'):
        value = 'sequence<' + value[:-2] + '>'
    if value in ('VehicleState', 'SlotObservation', 'ParkingSlot', 'EdgeState'):
        value = 'smart_hub_interfaces/' + value
    if value.startswith('sequence<'):
        value = 'sequence<' + normalize(value[9:-1]) + '>'
    return value.replace('float32', 'float').replace('float64', 'double')


def main():
    """Show every interface and verify every generated section's fields/types."""
    contracts = json.loads((ROOT / 'docs/contracts/m1-fields.json').read_text())
    for path, fields in contracts.items():
        kind, filename = path.split('/')
        name = filename.split('.')[0]
        target = f'smart_hub_interfaces/{kind}/{name}'
        subprocess.run(['ros2', 'interface', 'show', target], check=True)
        groups = [[]]
        for field in fields:
            if field == '---':
                groups.append([])
            else:
                groups[-1].append(field)
        if kind == 'msg':
            classes = [get_message(target)]
        elif kind == 'srv':
            service = get_service(target)
            classes = [service.Request, service.Response]
        else:
            action = get_action(target)
            classes = [action.Goal, action.Result, action.Feedback]
        for cls, group in zip(classes, groups):
            expected = {f.split()[1]: normalize(f.split()[0]) for f in group}
            observed = {k: normalize(v) for k, v in cls.get_fields_and_field_types().items()}
            assert observed == expected, (target, expected, observed)
            cls()  # Exercise generated Python construction as well as imports.
        print('PASS generated fields/import: ' + target)


if __name__ == '__main__':
    main()
