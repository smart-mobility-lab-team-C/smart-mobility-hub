#!/usr/bin/env python3
"""Classify cumulative changes and enforce explicit CI outcomes (not ROS evidence)."""

import argparse
import json
import os
from pathlib import Path
import subprocess


def documentation_only(path):
    """Allow only known prose/evidence paths; contracts and unknowns require ROS."""
    if path.startswith('docs/contracts/'):
        return False
    return (path.startswith('evidence/') or
            (path.startswith('docs/') and path.endswith('.md')) or
            path in {'README.md', 'AGENTS.md', 'CONTRIBUTING.md', 'LICENSE'})


def classify(event_name, event, paths):
    """Return a decision and reason without treating a skip as acceptance."""
    if event_name == 'pull_request' and event['pull_request']['draft']:
        return False, 'Draft PR: quick checks only; ROS acceptance NOT RUN'
    if event_name == 'workflow_dispatch':
        full = str(event.get('inputs', {}).get('full_suite', 'false')).lower() == 'true'
        return full, ('Manual full suite requested' if full else
                      'Manual quick checks only; ROS acceptance NOT RUN')
    if not paths or any(not documentation_only(path) for path in paths):
        return True, 'Runtime, tooling, contract, unknown or unavailable change set'
    return False, 'Documentation/evidence only; ROS acceptance NOT RUN'


def gate(quick, classification, required, integration):
    """Fail closed on failed prerequisites or an unexecuted required suite."""
    return (quick == 'success' and classification == 'success' and
            ((required == 'true' and integration == 'success') or
             (required == 'false' and integration == 'skipped')))


def changed_paths(event_name, event):
    """Diff PR base through head cumulatively, including both sides of renames."""
    if event_name == 'pull_request':
        pr = event['pull_request']
        revision = f"{pr['base']['sha']}...{pr['head']['sha']}"
    elif event_name == 'push':
        before, after = event['before'], event['after']
        if not before.strip('0'):
            return []  # Unknown change set fails toward integration.
        revision = f'{before}..{after}'
    else:
        return []
    result = subprocess.run(['git', 'diff', '--name-only', '--no-renames', '-z', revision],
                            check=True, capture_output=True)
    return [os.fsdecode(p) for p in result.stdout.split(b'\0') if p]


def main():
    """Write auditable routing outputs or evaluate the final gate."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=['classify', 'gate'])
    args = parser.parse_args()
    if args.mode == 'gate':
        state = {key: os.environ.get(key, '') for key in
                 ('QUICK', 'CLASSIFICATION', 'REQUIRED', 'INTEGRATION')}
        print(json.dumps(state, sort_keys=True))
        passed = gate(state['QUICK'], state['CLASSIFICATION'], state['REQUIRED'],
                      state['INTEGRATION'])
        print('PASS: verification policy' if passed else 'FAIL: verification policy')
        return 0 if passed else 1
    event = json.loads(Path(os.environ['GITHUB_EVENT_PATH']).read_text())
    event_name = os.environ['GITHUB_EVENT_NAME']
    paths = changed_paths(event_name, event)
    required, reason = classify(event_name, event, paths)
    record = {'integration_required': str(required).lower(), 'reason': reason,
              'changed_paths': paths}
    print(json.dumps(record, indent=2))
    with open(os.environ['GITHUB_OUTPUT'], 'a') as output:
        output.write(f'integration_required={str(required).lower()}\n')
    with open(os.environ['GITHUB_STEP_SUMMARY'], 'a') as summary:
        summary.write(f'### Verification routing\n\n{reason}\n\n')
        summary.write(f'Integration required: `{str(required).lower()}`\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
