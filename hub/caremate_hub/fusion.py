"""Pure fusion helpers.

Kept free of side effects and I/O so the alert decision is trivially testable and
auditable. The controller owns state and timing; this module only classifies
evidence. Deterministic policy only — no model is ever the alert authority.
"""

from __future__ import annotations

from enum import Enum
from typing import Optional

from .config import FusionConfig
from .events import Activity, VisionEvidence


class VisionVerdict(str, Enum):
    CONFIRMING = "confirming"     # lying + no motion — supports a fall
    REJECTING = "rejecting"       # clearly upright / on bed — refutes a fall
    INCONCLUSIVE = "inconclusive"  # visible but ambiguous / low confidence
    UNAVAILABLE = "unavailable"   # occluded, not visible, or camera down


def classify_vision(ev: Optional[VisionEvidence], cfg: FusionConfig) -> VisionVerdict:
    """Map one vision reading to its bearing on a pending fall candidate.

    ON_BED is horizontal but expected, so it *rejects* rather than confirms —
    the wearable would not normally emit a candidate for lying down in bed, and
    if it did we prefer not to alert on it.
    """

    if ev is None or not ev.available or ev.activity in (
        Activity.NOT_VISIBLE,
        Activity.UNCERTAIN,
    ):
        return VisionVerdict.UNAVAILABLE

    if ev.confidence < cfg.min_vision_confidence:
        return VisionVerdict.INCONCLUSIVE

    if ev.activity is Activity.LYING and not ev.motion:
        return VisionVerdict.CONFIRMING

    if ev.activity in (
        Activity.STANDING,
        Activity.WALKING,
        Activity.SITTING,
        Activity.ON_BED,
    ):
        return VisionVerdict.REJECTING

    return VisionVerdict.INCONCLUSIVE
