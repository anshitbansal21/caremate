"""Tunable vision thresholds.

Starting bench values — tune against synthetic / consenting-team footage, never a
real fall. All are scale-invariant where possible (normalized by torso length or
expressed in torso-lengths/second), so they hold across camera distances.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class VisionConfig:
    # A keypoint below this confidence is treated as not observed.
    min_keypoint_confidence: float = 0.3

    # Ignore poses whose torso projects to fewer than this many pixels (too far /
    # spurious detection to classify reliably).
    min_torso_px: float = 15.0

    # Torso tilt from vertical (degrees) at/above which the person is "lying".
    # 0 = upright, 90 = horizontal.
    lying_tilt_deg: float = 55.0

    # Hip->ankle vertical span / torso length. Below this the legs are folded ->
    # "sitting"; above it the legs are extended -> standing/walking.
    sit_leg_ratio: float = 1.2

    # Sliding window over which centroid motion is measured.
    motion_window_ms: int = 600

    # Motion in torso-lengths/second. Below `still_metric` the person is "still"
    # (feeds the fusion no-motion confirm); above `walk_metric` an upright person
    # is "walking" rather than "standing".
    still_metric: float = 0.15
    walk_metric: float = 0.6
