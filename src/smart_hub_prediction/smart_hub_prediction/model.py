"""Episode-split ridge forecasting from observed queue and track events (A section 9.2)."""

import hashlib
import json
import math
from pathlib import Path
import random


HORIZON_SEC = 30
HISTORY_SEC = 60
FEATURE_SPAN = 31  # q_{t-10} and the 30 s entry/exit sums need 31 one-second samples
EPISODE_SEC = 360
FEATURE_NAMES = (['intercept', 'q_t'] + [f'q_t-{lag}' for lag in range(9, -1, -1)] +
                 ['q_t - q_t-10', 'entries_t-29:t', 'exits_t-29:t'])
TRAIN_SEEDS = list(range(1000, 1030))
VALIDATION_SEEDS = list(range(2000, 2010))
TEST_SEEDS = list(range(3000, 3010))


def features(counts, entries, exits):
    """Build x_t = [q_t, q_{t-9:t}, q_t - q_{t-10}, a_{t-29:t}, d_{t-29:t}] from the past only."""
    if len(counts) < FEATURE_SPAN or len(entries) < 30 or len(exits) < 30:
        raise ValueError('31 seconds of history required')
    current = counts[-1]
    return ([1.0, current] + [float(value) for value in counts[-10:]] +
            [current - counts[-11], sum(entries[-30:]), sum(exits[-30:])])


def episode(seed):
    """Generate one independent six-minute episode with varied arrivals and boardings."""
    # Each seed draws its own base rate, one or two rush periods and boarding times and
    # capacities, so no fixed timetable is shared across episodes.
    rng = random.Random(seed)
    base = rng.uniform(0.005, 0.03)
    rushes = [(start, start + rng.uniform(40, 120), rng.uniform(2.0, 4.0))
              for start in sorted(rng.uniform(0, 300) for _ in range(rng.randint(1, 2)))]
    boardings, at = {}, rng.uniform(30, 120)
    while at < EPISODE_SEC:
        boardings[int(at)] = rng.randint(4, 10)
        at += rng.uniform(60, 150)
    counts, entries, exits = [], [], []
    count = rng.randrange(0, 4)
    for second in range(EPISODE_SEC + 1):
        rate = base * max([factor for start, end, factor in rushes
                           if start <= second < end], default=1.0)
        arrivals = sum(rng.random() < rate for _ in range(3))
        leaving = sum(rng.random() < 0.002 for _ in range(count))
        departures = min(count + arrivals, boardings.get(second, 0) + leaving)
        count += arrivals - departures
        counts.append(count)
        entries.append(arrivals)
        exits.append(departures)
    return counts, entries, exits


def windows(episodes):
    """Window only after complete episodes have been assigned to a split."""
    output = []
    for counts, entries, exits in episodes:
        for second in range(FEATURE_SPAN - 1, EPISODE_SEC + 1 - HORIZON_SEC):
            start = second - FEATURE_SPAN + 1
            x = features(counts[start:second + 1], entries[start:second + 1],
                         exits[start:second + 1])
            output.append((x, counts[second + HORIZON_SEC], counts[second]))
    return output


def predict(coefficients, x):
    """Return the non-negative ridge forecast for one feature vector."""
    return max(0.0, sum(a * b for a, b in zip(coefficients, x)))


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
        errors.append(predict(coefficients, x) - target)
        baselines.append(current - target)

    def metrics(values):
        return {'mae': sum(abs(value) for value in values) / len(values),
                'rmse': math.sqrt(sum(value * value for value in values) / len(values))}
    return {'model': metrics(errors), 'persistence': metrics(baselines),
            'samples': len(rows)}


def train(path):
    """Fit on 30 episodes, tune on ten, and evaluate ten unseen episodes (60/20/20)."""
    train_rows = windows([episode(seed) for seed in TRAIN_SEEDS])
    validation_rows = windows([episode(seed) for seed in VALIDATION_SEEDS])
    test_rows = windows([episode(seed) for seed in TEST_SEEDS])
    candidates = [(evaluate(validation_rows, fit_ridge(train_rows, penalty))
                   ['model']['mae'], penalty) for penalty in (0.01, 0.1, 1.0, 10.0, 100.0)]
    penalty = min(candidates)[1]
    coefficients = fit_ridge(train_rows, penalty)
    test = evaluate(test_rows, coefficients)
    result = {
        'schema': 'smart-hub-ridge-v2', 'horizon_sec': HORIZON_SEC,
        'history_sec': HISTORY_SEC, 'feature_span_sec': FEATURE_SPAN,
        'features': FEATURE_NAMES, 'train_seeds': TRAIN_SEEDS,
        'validation_seeds': VALIDATION_SEEDS, 'test_seeds': TEST_SEEDS,
        'penalty': penalty, 'coefficients': coefficients,
        'validation': evaluate(validation_rows, coefficients), 'test': test,
        'model_no_worse_than_persistence': test['model']['mae'] <= test['persistence']['mae'],
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
    print(json.dumps({'sha256': digest, 'penalty': summary['penalty'],
                      'validation': summary['validation'], 'test': summary['test']},
                     sort_keys=True))
