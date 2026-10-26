"""Check episode split, held-out forecast, leakage and inference cost."""

import json
from pathlib import Path
import time

from smart_hub_prediction.model import (
    episode, evaluate, FEATURE_SPAN, features, predict, windows)


def load():
    """Read the checked-in training report."""
    path = Path(__file__).resolve().parents[1] / 'models/ridge.json'
    return json.loads(path.read_text())


def test_held_out_episodes_reproduce_report():
    """Whole episodes split 60/20/20 with unseen seeds; recorded scores reproduce."""
    model = load()
    train = set(model['train_seeds'])
    validation = set(model['validation_seeds'])
    test = set(model['test_seeds'])
    assert len(train) + len(validation) + len(test) >= 30
    assert len(train) == 3 * len(validation) == 3 * len(test)
    assert not train & validation and not train & test and not validation & test
    rows = windows([episode(seed) for seed in sorted(test)])
    scores = evaluate(rows, model['coefficients'])
    assert scores == model['test']
    assert model['model_no_worse_than_persistence'] == (
        scores['model']['mae'] <= scores['persistence']['mae'])


def test_features_use_only_the_past():
    """Changing every sample after t changes the target but not the features at t."""
    counts, entries, exits = episode(3000)
    index = 90
    second = FEATURE_SPAN - 1 + index

    def shifted(values):
        return values[:second + 1] + [value + 50 for value in values[second + 1:]]

    original = windows([(counts, entries, exits)])[index]
    altered = windows([(shifted(counts), shifted(entries), shifted(exits))])[index]
    assert original[0] == altered[0] and original[2] == altered[2]
    assert original[1] != altered[1]
    assert original[0] == features(counts[:second + 1], entries[:second + 1],
                                   exits[:second + 1])
    assert len(original[0]) == len(load()['features'])


def test_inference_latency():
    """One forecast is far below the 100 ms p95 budget."""
    model = load()
    rows = windows([episode(seed) for seed in model['test_seeds'][:2]])
    durations = []
    for x, _, _ in rows:
        started = time.perf_counter()
        predict(model['coefficients'], x)
        durations.append((time.perf_counter() - started) * 1000)
    assert sorted(durations)[int(0.95 * (len(durations) - 1))] < 100
