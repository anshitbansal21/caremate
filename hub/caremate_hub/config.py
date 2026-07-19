"""Tunable fusion thresholds and timing windows.

All values are configurable per CLAUDE.md. Defaults are bench starting points to
tune against synthetic / consenting-team telemetry — never against a real fall.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FusionConfig:
    # How long to await vision confirmation after a wearable candidate before
    # falling back to "uncertain — check user".
    vision_window_ms: int = 8000

    # Sustained "lying + no motion" required from vision to confirm a fall.
    no_motion_confirm_ms: int = 2500

    # Ignore vision evidence older than this (treat a stalled camera as absent).
    vision_staleness_ms: int = 3000

    # Reject candidates and vision readings below these confidences.
    min_candidate_confidence: float = 0.5
    min_vision_confidence: float = 0.5
