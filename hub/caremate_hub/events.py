"""Event and value types exchanged inside the vision hub.

Wire-facing shapes (CandidateFall, SpaceAnalysis) mirror the versioned contracts
in ``docs/architecture.md`` so the same fields survive JSON serialization to the
wearable transport and to Anshit's API layer.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import List


class Activity(str, Enum):
    """Visible activity labels produced by the vision layer (YOLOv8 pose)."""

    STANDING = "standing"
    SITTING = "sitting"
    LYING = "lying"          # lying on the floor — fall-relevant
    ON_BED = "on_bed"        # horizontal but expected — NOT a fall
    WALKING = "walking"
    NOT_VISIBLE = "not_visible"
    UNCERTAIN = "uncertain"


class FusionState(str, Enum):
    """States of the main controller's fusion machine.

        candidate ─▶ AWAITING_VISION ─▶ CONFIRMED_FALL ─▶ ALERTING
                                    ╲─▶ REJECTED
                                    ╲─▶ UNCERTAIN (check user)
    """

    READY = "ready"
    AWAITING_VISION = "awaiting_vision"
    CONFIRMED_FALL = "confirmed_fall"
    ALERTING = "alerting"
    UNCERTAIN = "uncertain"
    REJECTED = "rejected"
    FAULT = "fault"


class AlertLevel(str, Enum):
    """What the local alert output and the app should convey."""

    NONE = "none"
    POSSIBLE = "possible"    # wearable candidate, awaiting vision
    CHECK = "check"          # uncertain — check on the user
    CONFIRMED = "confirmed"  # fusion-confirmed fall


@dataclass(frozen=True)
class CandidateFall:
    """A candidate-fall event from the wearable. Never a confirmed fall.

    Mirrors the ``event=candidate_fall, source=wearable`` contract; the ESP32
    heuristic and its transport live behind ``WearableSource`` and produce this.
    """

    source: str
    uptime_ms: int         # wearable-side monotonic time (from its heuristic)
    confidence: float      # 0..1 heuristic confidence
    received_at_ms: int    # hub-side receive time (fusion correlates on this)
    version: int = 1


@dataclass(frozen=True)
class VisionEvidence:
    """One reading from the vision layer. Streamed; the fusion machine samples
    the freshest reading each tick."""

    at_ms: int
    activity: Activity
    motion: bool           # True = motion present in the frame
    confidence: float
    available: bool = True  # False on occlusion / camera outage


@dataclass(frozen=True)
class SpaceAnalysis:
    """Result of the app-triggered **Analyze space** action.

    Mirrors the ``event=space_analysis`` contract in ``docs/architecture.md``.
    ``alert_recommendation`` is advisory evidence, never the alert authority.
    """

    request_id: str
    captured_at: str            # ISO-8601, or "" when unavailable
    person_state: str           # on_bed / standing / sitting / lying / walking / not_visible / uncertain
    room_summary: str
    risk_observations: List[str]
    alert_recommendation: str   # "alert" | "check" | "none"
    uncertain: bool
    version: int = 1
