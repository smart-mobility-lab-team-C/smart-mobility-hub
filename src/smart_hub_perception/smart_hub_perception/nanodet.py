"""
Offline OpenCV NanoDet 416 person inference for local video frames.

Decoder follows OpenCV Zoo's Apache-2.0 NanoDet implementation at commit
25f423d0e04c31a17254620e58febd7386da523b.
"""

import hashlib
from pathlib import Path


MODEL_SHA256 = '4b82da9944b88577175ee23a459dce2e26e6e4be573def65b1055dc2d9720186'


class NanoDetPerson:
    """Decode class-zero person boxes from the pinned local ONNX model."""

    def __init__(self, model_path, confidence=0.35):
        """Verify the offline asset before loading it through OpenCV DNN."""
        import cv2
        import numpy as np

        path = Path(model_path)
        if hashlib.sha256(path.read_bytes()).hexdigest() != MODEL_SHA256:
            raise ValueError('NanoDet model checksum mismatch')
        self.cv2 = cv2
        self.np = np
        self.confidence = confidence
        self.net = cv2.dnn.readNetFromONNX(str(path))
        self.mean = np.array([103.53, 116.28, 123.675], dtype=np.float32)
        self.std = np.array([57.375, 57.12, 58.395], dtype=np.float32)
        self.anchors = []
        for stride in (8, 16, 32, 64):
            grid = np.arange(416 // stride) * stride + 0.5 * (stride - 1)
            x, y = np.meshgrid(grid, grid)
            self.anchors.append(np.column_stack((x.ravel(), y.ravel())))

    def foot_points(self, image):
        """Return person-box bottom centres in original image pixels."""
        cv2, np = self.cv2, self.np
        width, height = image.width, image.height
        frame = np.frombuffer(bytes(image.data), dtype=np.uint8)
        frame = frame.reshape(height, image.step)[:, :width * 3].reshape(height, width, 3)
        resized = cv2.resize(frame, (416, 416)).astype(np.float32)
        normalized = (resized - self.mean) / self.std
        self.net.setInput(cv2.dnn.blobFromImage(normalized))
        outputs = self.net.forward(self.net.getUnconnectedOutLayersNames())
        boxes, scores = [], []
        for stride, classes, regressions, anchors in zip(
                (8, 16, 32, 64), outputs[::2], outputs[1::2], self.anchors):
            classes = classes.reshape(-1, classes.shape[-1])
            regressions = regressions.reshape(-1, 4, 8)
            person = classes[:, 0]
            chosen = np.flatnonzero(person >= self.confidence)
            if not len(chosen):
                continue
            logits = regressions[chosen]
            exponent = np.exp(logits - logits.max(axis=2, keepdims=True))
            probabilities = exponent / exponent.sum(axis=2, keepdims=True)
            distances = (probabilities * np.arange(8)).sum(axis=2) * stride
            centres = anchors[chosen]
            x1 = np.clip(centres[:, 0] - distances[:, 0], 0, 416)
            y1 = np.clip(centres[:, 1] - distances[:, 1], 0, 416)
            x2 = np.clip(centres[:, 0] + distances[:, 2], 0, 416)
            y2 = np.clip(centres[:, 1] + distances[:, 3], 0, 416)
            boxes.extend(np.column_stack((x1, y1, x2 - x1, y2 - y1)).tolist())
            scores.extend(person[chosen].tolist())
        if not boxes:
            return []
        indices = cv2.dnn.NMSBoxes(boxes, scores, self.confidence, 0.6)
        return [((boxes[int(index)][0] + boxes[int(index)][2] / 2) * width / 416,
                 (boxes[int(index)][1] + boxes[int(index)][3]) * height / 416)
                for index in np.asarray(indices).reshape(-1)]
