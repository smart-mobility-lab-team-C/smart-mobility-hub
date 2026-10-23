#!/usr/bin/env python3
"""Render measured M4 traces into standalone plots for reproducible evidence."""

import argparse
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt  # noqa: E402


def plot(trace, destination):
    """Plot recorded edge estimates, parking sensing and measured barrier response."""
    records = [json.loads(line) for line in trace.read_text().splitlines() if line.strip()]
    if not records:
        raise ValueError('empty trace')
    origin = min(record['t'] for record in records)
    fig, axes = plt.subplots(4, 1, figsize=(12, 10), sharex=True, constrained_layout=True)
    edges = [(record['t'] - origin, edge)
             for record in records if record.get('topic') == 'edges'
             for edge in record['message']['edges'] if edge['edge_id'] == 'Cs-J']
    if not edges:
        raise ValueError('no Cs-J observations in trace')
    t = [stamp for stamp, _ in edges]
    axes[0].plot(t, [edge['mean_speed_mps'] if edge['valid'] else float('nan')
                     for _, edge in edges], label='observed median speed')
    axes[0].axhline(.14, color='gray', linestyle='--', label='40% free flow')
    axes[0].set_ylabel('Speed (m/s)')
    axes[1].step(t, [edge['density_ratio'] for _, edge in edges], where='post', label='density')
    axes[1].step(t, [int(edge['valid']) for _, edge in edges], where='post', label='valid')
    axes[1].step(t, [int(edge['blocked']) for _, edge in edges], where='post', label='blocked')
    axes[1].axhline(.7, color='gray', linestyle='--', label='density threshold')
    axes[1].set_ylabel('Ratio / flag')
    states = {'UNKNOWN': 0, 'FREE': 1, 'RESERVED': 2, 'OCCUPIED': 3}
    for key in ('P1', 'P2', 'P3'):
        points = [(record['t'] - origin, states[slot['state']])
                  for record in records if record.get('topic') == 'parking'
                  for slot in record['message']['slots'] if slot['slot_id'] == key]
        if points:
            axes[2].step(*zip(*points), where='post', label=key)
    axes[2].set_yticks(list(states.values()), list(states))
    for topic in ('request', 'barrier'):
        points = [(record['t'] - origin, int(record['message']['data']))
                  for record in records if record.get('topic') == topic]
        if points:
            axes[3].step(*zip(*points), where='post', label=topic)
    axes[3].set_ylabel('Barrier open')
    axes[3].set_xlabel('Observer monotonic time since first record (s)')
    for axis in axes:
        axis.grid(alpha=.3)
        axis.legend(loc='upper right')
    fig.suptitle('M4 recorded measurements (Cs-J traffic, parking and barrier)')
    fig.savefig(destination)
    plt.close(fig)


def main():
    """Accept only an existing trace and an explicit output artifact path."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('trace', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    plot(args.trace, args.output)


if __name__ == '__main__':
    main()
