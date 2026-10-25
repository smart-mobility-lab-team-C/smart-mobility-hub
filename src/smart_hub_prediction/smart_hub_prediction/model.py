"""Episode-split ridge forecasting from observed queue and track events."""

import hashlib
import json
import math
from pathlib import Path
import random


HORIZON_SEC = 30
HISTORY_SEC = 60


def features(counts, entries, exits, elapsed):
    """Use only the previous sixty seconds of count and track transitions."""
    if len(counts) < 61:
        raise ValueError('sixty seconds of history required')
    current = counts[-1]
    return [1.0, current, current - counts[-11], current - counts[-31],
            sum(counts[-10:]) / 10, sum(counts[-30:]) / 30,
            sum(entries[-30:]), sum(exits[-30:]), elapsed / 360]


def episode(seed):
    """Generate one independent six-minute queue episode for offline fitting."""
    rng = random.Random(seed)
    counts, entries, exits = [], [], []
    count = rng.randrange(0, 4)
    rush = rng.uniform(0.8, 1.2)
    for second in range(361):
        rate = (0.07 if second < 60 else
                0.25 * rush if second < 150 else
                0.13 if second < 240 else 0.05)
        arrivals = sum(rng.random() < rate for _ in range(3))
        departures = min(count + arrivals, 4 if second in (90, 180, 270) else 0)
        count += arrivals - departures
        counts.append(count)
        entries.append(arrivals)
        exits.append(departures)
    return counts, entries, exits


def windows(episodes):
    """Window only after complete episodes have been assigned to a split."""
    output = []
    for counts, entries, exits in episodes:
        for second in range(HISTORY_SEC, 361 - HORIZON_SEC):
            x = features(counts[second - HISTORY_SEC:second + 1],
                         entries[second - HISTORY_SEC:second + 1],
                         exits[second - HISTORY_SEC:second + 1], second)
            output.append((x, counts[second + HORIZON_SEC], counts[second]))
    return output


def fit_ridge(rows, penalty):
    """Solve ridge normal equations, retaining an unpenalized intercept."""
    import numpy as np

    x = np.asarray([row[0] for row in rows], dtype=float)
    y = np.asarray([row[1] for row in rows], dtype=float)
    scale = np.maximum(x.std(axis=0), 1e-9)
    scale[0] = 1.0
    x_scaled = x / scale
    regularizer = np.eye(x.shape[1]) * penalty
    regularizer[0, 0] = 0.0
    coefficients = np.linalg.solve(x_scaled.T @ x_scaled + regularizer,
                                   x_scaled.T @ y) / scale
    return coefficients.tolist()


def evaluate(rows, coefficients):
    """Return MAE/RMSE for model and persistence on the same targets."""
    errors, baselines = [], []
    for x, target, current in rows:
        predicted = max(0.0, sum(a * b for a, b in zip(coefficients, x)))
        errors.append(predicted - target)
        baselines.append(current - target)

    def metrics(values):
        return {'mae': sum(abs(value) for value in values) / len(values),
                'rmse': math.sqrt(sum(value * value for value in values) / len(values))}
    return {'model': metrics(errors), 'persistence': metrics(baselines),
            'samples': len(rows)}


def train(path):
    """Fit on 18 episodes, tune on six, and evaluate six unseen episodes."""
    seeds = list(range(1000, 1030))
    train_rows = windows([episode(seed) for seed in seeds[:18]])
    validation_rows = windows([episode(seed) for seed in seeds[18:24]])
    test_rows = windows([episode(seed) for seed in seeds[24:]])
    candidates = [(evaluate(validation_rows, fit_ridge(train_rows, penalty))
                   ['model']['mae'], penalty) for penalty in (0.01, 0.1, 1.0, 10.0)]
    penalty = min(candidates)[1]
    coefficients = fit_ridge(train_rows, penalty)
    result = {
        'schema': 'smart-hub-ridge-v1', 'horizon_sec': HORIZON_SEC,
        'history_sec': HISTORY_SEC, 'train_seeds': seeds[:18],
        'validation_seeds': seeds[18:24], 'test_seeds': seeds[24:],
        'penalty': penalty, 'coefficients': coefficients,
        'validation': evaluate(validation_rows, coefficients),
        'test': evaluate(test_rows, coefficients),
    }
    raw = json.dumps(result, sort_keys=True, indent=2) + '\n'
    Path(path).write_text(raw)
    return result, hashlib.sha256(raw.encode()).hexdigest()


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument('output')
    args = parser.parse_args()
    summary, digest = train(args.output)
    print(json.dumps({'sha256': digest, 'test': summary['test']}, sort_keys=True))
