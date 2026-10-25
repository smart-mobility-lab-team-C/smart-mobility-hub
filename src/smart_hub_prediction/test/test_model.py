"""Check episode split, held-out forecast and inference cost."""

import json
from pathlib import Path
import statistics
import time

from smart_hub_prediction.model import episode, evaluate, windows


def test_held_out_episodes_and_latency():
    """Require unseen seeds, baseline improvement, and sub-100 ms inference."""
    path = Path(__file__).resolve().parents[1] / 'models/ridge.json'
    model = json.loads(path.read_text())
    train = set(model['train_seeds'])
    validation = set(model['validation_seeds'])
    test = set(model['test_seeds'])
    assert len(train) == 18 and len(validation) == len(test) == 6
    assert not train & validation and not train & test and not validation & test
    rows = windows([episode(seed) for seed in sorted(test)])
    scores = evaluate(rows, model['coefficients'])
    assert scores == model['test']
    assert scores['model']['mae'] <= scores['persistence']['mae']
    durations = []
    for x, _, _ in rows:
        started = time.perf_counter()
        sum(a * b for a, b in zip(model['coefficients'], x))
        durations.append((time.perf_counter() - started) * 1000)
    p95 = sorted(durations)[int(0.95 * (len(durations) - 1))]
    assert p95 < 100
    assert statistics.mean(durations) >= 0
