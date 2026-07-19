"""Scripted stand-in for the YOLOv8 pose + Analyze-space layer.

Models the camera as a *stream*: it holds the current activity and re-emits it
with a fresh timestamp every ``emit_period_ms`` (so the fusion staleness window
behaves realistically). The real VisionSource is Aryan's on-device inference.
"""

from __future__ import annotations

from typing import List, Optional, Tuple

from ..events import Activity, SpaceAnalysis, VisionEvidence
from ..interfaces import VisionSource

# A state-change entry: (at_ms, activity, motion, confidence, available)
Change = Tuple[int, Activity, bool, float, bool]


class MockVision(VisionSource):
    def __init__(
        self,
        timeline: List[Change],
        analysis_result: Optional[SpaceAnalysis] = None,
        emit_period_ms: int = 400,
    ) -> None:
        self._changes = sorted(timeline, key=lambda e: e[0])
        self._i = 0
        self._current: Optional[Change] = None
        self._last_emit: Optional[int] = None
        self._period = emit_period_ms
        self._analysis = analysis_result

    def pump(self, now_ms: int, controller) -> None:
        while self._i < len(self._changes) and now_ms >= self._changes[self._i][0]:
            self._current = self._changes[self._i]
            self._i += 1
        if self._current is None:
            return
        if self._last_emit is None or now_ms - self._last_emit >= self._period:
            self._last_emit = now_ms
            _, activity, motion, conf, avail = self._current
            controller.ingest_vision(
                VisionEvidence(
                    at_ms=now_ms,
                    activity=activity,
                    motion=motion,
                    confidence=conf,
                    available=avail,
                )
            )

    def analyze_space(self, request_id: str, now_ms: int) -> SpaceAnalysis:
        if self._analysis is not None:
            # Re-stamp with the requested id so records line up.
            a = self._analysis
            return SpaceAnalysis(
                request_id=request_id,
                captured_at=a.captured_at,
                person_state=a.person_state,
                room_summary=a.room_summary,
                risk_observations=list(a.risk_observations),
                alert_recommendation=a.alert_recommendation,
                uncertain=a.uncertain,
            )
        return SpaceAnalysis(
            request_id=request_id,
            captured_at="",
            person_state="uncertain",
            room_summary="No model wired.",
            risk_observations=[],
            alert_recommendation="check",
            uncertain=True,
        )
