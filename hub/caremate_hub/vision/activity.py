"""The vision brain: turn a pose (17 keypoints) into an activity label, and a
sequence of poses into a motion estimate.

Pure and deterministic — no camera, no model, no I/O — so the fall-relevant logic
is unit-tested on synthetic skeletons. Geometry is scale-invariant (normalized by
torso length) so thresholds hold regardless of how far the person is from the C270.

Duck-typed on ``pose``: anything with a ``keypoints`` sequence of ``(x, y, conf)``
triples in COCO-17 order works (see ``backends.Pose``).
"""

from __future__ import annotations

import math
from collections import deque
from typing import Deque, List, Optional, Sequence, Tuple

from ..events import Activity
from . import keypoints as K
from .config import VisionConfig

Point = Tuple[float, float]


def _pt(pose, idx: int, min_conf: float) -> Optional[Point]:
    x, y, c = pose.keypoints[idx]
    return (x, y) if c >= min_conf else None


def _center(pose, i: int, j: int, min_conf: float) -> Optional[Point]:
    """Midpoint of a symmetric joint pair, tolerating one missing side."""
    a = _pt(pose, i, min_conf)
    b = _pt(pose, j, min_conf)
    if a and b:
        return ((a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0)
    return a or b


def _dist(p: Point, q: Point) -> float:
    return math.hypot(p[0] - q[0], p[1] - q[1])


def _mean_conf(pose, min_conf: float) -> float:
    vals = [c for _, _, c in pose.keypoints if c >= min_conf]
    return sum(vals) / len(vals) if vals else 0.0


def _centroid(pose, min_conf: float) -> Optional[Point]:
    pts = [(x, y) for x, y, c in pose.keypoints if c >= min_conf]
    if not pts:
        return None
    n = len(pts)
    return (sum(p[0] for p in pts) / n, sum(p[1] for p in pts) / n)


def classify_activity(pose, moving: bool, cfg: VisionConfig) -> Tuple[Activity, float]:
    """Classify a single pose into standing / sitting / lying / walking.

    ``moving`` comes from :class:`MotionTracker` (whether the person is moving
    enough to count as walking rather than a standing sway). Returns
    ``(activity, confidence)``; confidence 0 means "don't trust this".

    Note: ON_BED is not decided here — it needs a configured bed region in the
    scene, layered on top of a LYING classification elsewhere.
    """
    mc = cfg.min_keypoint_confidence

    shoulder = _center(pose, K.LEFT_SHOULDER, K.RIGHT_SHOULDER, mc)
    hip = _center(pose, K.LEFT_HIP, K.RIGHT_HIP, mc)
    if shoulder is None or hip is None:
        return Activity.NOT_VISIBLE, 0.0

    torso_len = _dist(shoulder, hip)
    if torso_len < cfg.min_torso_px:
        return Activity.UNCERTAIN, 0.0

    conf = _mean_conf(pose, mc)

    # Torso tilt from vertical: |dx| vs |dy| of the hip->shoulder vector.
    dx = shoulder[0] - hip[0]
    dy = shoulder[1] - hip[1]
    tilt_deg = math.degrees(math.atan2(abs(dx), abs(dy)))
    if tilt_deg >= cfg.lying_tilt_deg:
        return Activity.LYING, conf

    # Upright: distinguish sitting from standing by how far the ankles drop below
    # the hips relative to torso length (folded legs -> small span -> sitting).
    ankle = _center(pose, K.LEFT_ANKLE, K.RIGHT_ANKLE, mc)
    if ankle is not None:
        leg_ratio = abs(ankle[1] - hip[1]) / torso_len
        if leg_ratio < cfg.sit_leg_ratio:
            return Activity.SITTING, conf

    # Upright with extended (or unobservable) legs.
    return (Activity.WALKING if moving else Activity.STANDING), conf


class MotionTracker:
    """Scale-invariant motion estimate from the person centroid over a short window.

    Returns motion in **torso-lengths per second**, so a value is comparable
    across camera distances. Feeds two decisions: ``motion`` for the fusion
    no-motion confirm (``> still_metric``) and walking (``> walk_metric``).
    """

    def __init__(self, cfg: VisionConfig) -> None:
        self.cfg = cfg
        self._hist: Deque[Tuple[int, Point, float]] = deque()  # (t_ms, centroid, torso_len)

    def update(self, pose, now_ms: int) -> float:
        mc = self.cfg.min_keypoint_confidence
        centroid = _centroid(pose, mc)
        shoulder = _center(pose, K.LEFT_SHOULDER, K.RIGHT_SHOULDER, mc)
        hip = _center(pose, K.LEFT_HIP, K.RIGHT_HIP, mc)
        if centroid is None or shoulder is None or hip is None:
            return 0.0
        torso_len = max(_dist(shoulder, hip), 1.0)

        self._hist.append((now_ms, centroid, torso_len))
        while self._hist and now_ms - self._hist[0][0] > self.cfg.motion_window_ms:
            self._hist.popleft()
        if len(self._hist) < 2:
            return 0.0

        t0, c0, l0 = self._hist[0]
        t1, c1, _ = self._hist[-1]
        dt = (t1 - t0) / 1000.0
        if dt <= 0:
            return 0.0
        return _dist(c0, c1) / max(l0, 1.0) / dt

    def is_moving(self, metric: float) -> bool:
        return metric > self.cfg.still_metric

    def is_walking(self, metric: float) -> bool:
        return metric > self.cfg.walk_metric

    def reset(self) -> None:
        self._hist.clear()
