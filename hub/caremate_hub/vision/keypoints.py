"""COCO-17 keypoint indices (the layout YOLOv8-pose / MoveNet emit).

A pose is 17 ``(x, y, confidence)`` triples in image coordinates where **y grows
downward** (standard image convention). Kept in one place so the classifier and
any backend agree on ordering.
"""

from __future__ import annotations

NOSE = 0
LEFT_EYE = 1
RIGHT_EYE = 2
LEFT_EAR = 3
RIGHT_EAR = 4
LEFT_SHOULDER = 5
RIGHT_SHOULDER = 6
LEFT_ELBOW = 7
RIGHT_ELBOW = 8
LEFT_WRIST = 9
RIGHT_WRIST = 10
LEFT_HIP = 11
RIGHT_HIP = 12
LEFT_KNEE = 13
RIGHT_KNEE = 14
LEFT_ANKLE = 15
RIGHT_ANKLE = 16

NUM_KEYPOINTS = 17
