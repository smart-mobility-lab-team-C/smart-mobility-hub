#!/usr/bin/env python3
"""Evaluate local annotated camera frames with the pinned offline NanoDet model."""

import argparse
import csv
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

from smart_hub_perception.detector import homography, project, Tracker
from smart_hub_perception.nanodet import NanoDetPerson


def evaluate(annotations, calibration, model_path):
    """Report individual count errors and aggregate partially occluded results."""
    import cv2

    settings = json.loads(Path(calibration).read_text())
    matrix = homography(settings['image_points_px'], settings['map_points_m'])
    detector = NanoDetPerson(model_path)
    tracker = Tracker()
    rows = list(csv.DictReader(Path(annotations).open(newline='')))
    if len(rows) < 100:
        raise ValueError('at least 100 annotated frames required')
    results = []
    previous = float('-inf')
    for row in rows:
        at = float(row['timestamp_sec'])
        if at <= previous:
            raise ValueError('frame timestamps must strictly increase')
        previous = at
        frame_path = Path(annotations).parent / row['frame_path']
        frame = cv2.imread(str(frame_path))
        if frame is None:
            raise FileNotFoundError(frame_path)
        height, width = frame.shape[:2]
        image = SimpleNamespace(width=width, height=height, step=width * 3,
                                data=frame.tobytes())
        feet = detector.foot_points(image)
        points = [project(matrix, point) for point in feet]
        tracker.update(points, at)
        count, crossing = tracker.occupancy(at)
        truth = int(row['count'])
        results.append({
            'frame_path': row['frame_path'], 'timestamp_sec': at,
            'truth_count': truth, 'observed_count': count,
            'absolute_error': abs(count - truth),
            'partial_occlusion': row['partial_occlusion'].lower() in ('1', 'true', 'yes'),
            'crossing_occupied': crossing,
        })
    def aggregate(group):
        return {'samples': len(group),
                'mae': sum(item['absolute_error'] for item in group) / len(group)
                if group else None}
    raw = Path(annotations).read_bytes()
    return {
        'status': 'PASS' if aggregate(results)['mae'] <= 1 else 'FAIL',
        'annotation_sha256': hashlib.sha256(raw).hexdigest(),
        'model_sha256': hashlib.sha256(Path(model_path).read_bytes()).hexdigest(),
        'all': aggregate(results),
        'partial_occlusion': aggregate([item for item in results
                                        if item['partial_occlusion']]),
        'frames': results,
    }


def main():
    """Read local frames and write a reproducible JSON result."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('annotations', help='CSV: frame_path,timestamp_sec,count,partial_occlusion')
    parser.add_argument('calibration', help='JSON with four image/map point pairs')
    parser.add_argument('model', help='pinned offline ONNX asset')
    parser.add_argument('output')
    args = parser.parse_args()
    result = evaluate(args.annotations, args.calibration, args.model)
    Path(args.output).write_text(json.dumps(result, indent=2, sort_keys=True) + '\n')
    print(json.dumps({key: value for key, value in result.items() if key != 'frames'}))
    raise SystemExit(0 if result['status'] == 'PASS' else 1)


if __name__ == '__main__':
    main()
