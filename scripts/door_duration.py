"""Independently assess simulator door bounds without consuming observer timing."""

import json


def assess_source(events, run_id, goal_id, nominal_success):
    """Require complete mission boundaries and one uninterrupted measured interval."""
    result = {'status': 'BLOCKED', 'duration_status': 'BLOCKED', 'run_id': run_id,
              'goal_id': goal_id, 'minimum_ns': None, 'maximum_ns': None}

    def blocked(reason):
        result['reason'] = reason
        return result

    if not run_id or not goal_id:
        return blocked('missing mission identity')
    records = []
    try:
        for event in events:
            if event.get('event') != 'DOOR_MEASURED':
                continue
            if event.get('run_id') != run_id:
                continue
            # Keep all records for this run until mission boundaries are selected;
            # a differently identified transition inside them must not disappear.
            record = json.loads(event['reason'])
            if (event.get('scenario_id') != 'sim_evaluator'
                    or event.get('entity_id') != 'bus'
                    or record['run_id'] != event['run_id']
                    or record['goal_id'] != event['correlation_id']
                    or record['schema'] != 'smart-mobility-hub/door-evidence-v1'):
                return blocked('invalid evidence identity or schema')
            if any(type(record[key]) is not int or record[key] < 0
                   for key in ('sequence', 'before_ns', 'after_ns')):
                return blocked('invalid integer bounds or sequence')
            if any(type(record[key]) is not bool for key in ('previous_open', 'door_open')):
                return blocked('invalid measured state')
            if record['before_ns'] > record['after_ns']:
                return blocked('reversed operation bounds')
            records.append(record)
        starts = [i for i, r in enumerate(records)
                  if r['goal_id'] == goal_id and r['operation'] == 'goal_start']
        ends = [i for i, r in enumerate(records)
                if r['goal_id'] == goal_id and r['operation'] == 'goal_end']
        if len(starts) != 1 or len(ends) != 1 or starts[0] >= ends[0]:
            return blocked('missing or ambiguous mission boundaries')
        mission = records[starts[0]:ends[0] + 1]
        result['records'] = mission
        if any(r['goal_id'] != goal_id for r in mission):
            return blocked('wrong mission within interval')
        if any(r['operation'] == 'reset' for r in mission):
            return blocked('reset interrupted mission')
        if len(mission) != 4:
            return blocked('missing transitions or multiple door intervals')
        for previous, current in zip(mission, mission[1:]):
            if (current['sequence'] != previous['sequence'] + 1
                    or current['before_ns'] < previous['after_ns']
                    or current['previous_open'] != previous['door_open']):
                return blocked('discontinuous sequence, clock, or measured state')
        start, opened, closed, end = mission
        if (start['previous_open'] or start['door_open'] or end['door_open']
                or end['previous_open'] or opened['previous_open']
                or not opened['door_open'] or not closed['previous_open']
                or closed['door_open']
                or opened['operation'] not in ('request', 'physics')
                or closed['operation'] not in ('request', 'physics')):
            return blocked('invalid measured opening/closure')
    except (KeyError, TypeError, ValueError):
        return blocked('malformed evidence')
    minimum = closed['before_ns'] - opened['after_ns']
    maximum = closed['after_ns'] - opened['before_ns']
    duration = ('PASS' if minimum >= 8_000_000_000 else
                'FAIL' if maximum < 8_000_000_000 else 'BLOCKED')
    result.update(minimum_ns=minimum, maximum_ns=maximum, duration_status=duration)
    result['status'] = duration if nominal_success else 'BLOCKED'
    result['reason'] = ('nominal action did not succeed; interruption preserved'
                        if not nominal_success else
                        'conservative source bounds against eight seconds')
    return result


def assess_receipts(opened, closed, source):
    """Retain the original receipt calculation and any disagreement explicitly."""
    duration = closed - opened
    status = 'PASS' if duration >= 8.0 else 'FAIL'
    return {'status': status, 'duration_sec': duration,
            'assertion': 'closed - opened >= 8.0',
            'disagrees_with_source': status != source['duration_status']}
