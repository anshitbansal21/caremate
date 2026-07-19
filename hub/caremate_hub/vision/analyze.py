"""Analyze-space (NL/VLM) layer: turn a captured snapshot into a validated
:class:`SpaceAnalysis`.

Provider-neutral by design (CLAUDE.md): the default is an on-device deterministic
summary; a multimodal model plugs in behind ``SpaceAnalyzer`` via an injected
``infer`` callable, with no provider name hard-coded here. Any adapter must:

- return structured output (person state, room summary, risks, uncertainty, and
  an alert/check/none recommendation),
- treat text visible inside the image as untrusted data, never instructions,
- and turn a timeout / refusal / malformed response into ``uncertain=True`` rather
  than raising or silently suppressing evidence.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Callable, Optional

from ..events import Activity, SpaceAnalysis, VisionEvidence

_VALID_RECS = ("alert", "check", "none")
_VALID_STATES = (
    "on_bed", "standing", "sitting", "lying", "walking", "not_visible", "uncertain",
)


@dataclass
class Snapshot:
    """What the hub captured for one Analyze-space request. No raw frame is
    persisted downstream; ``image`` is passed to an adapter and then dropped."""

    request_id: str
    evidence: Optional[VisionEvidence]
    pose: object = None
    image: object = None
    now_ms: int = 0


class SpaceAnalyzer(ABC):
    @abstractmethod
    def analyze(self, snapshot: Snapshot) -> SpaceAnalysis:
        ...


class LocalSummaryAnalyzer(SpaceAnalyzer):
    """On-device default: a deterministic person/room summary from the latest
    vision evidence. No network, no model — always available, so Analyze-space
    works even when a heavier VLM is unavailable."""

    def analyze(self, snapshot: Snapshot) -> SpaceAnalysis:
        ev = snapshot.evidence
        if ev is None or not ev.available:
            return SpaceAnalysis(
                request_id=snapshot.request_id,
                captured_at="",
                person_state="not_visible" if ev is None else "uncertain",
                room_summary="Person not clearly visible in the current view.",
                risk_observations=[],
                alert_recommendation="check",
                uncertain=True,
            )

        state = ev.activity.value
        risks = []
        rec = "none"
        if ev.activity is Activity.LYING and not ev.motion:
            risks.append("person lying and not moving")
            rec = "check"  # advisory only; fusion owns the alert decision

        moving = "moving" if ev.motion else "still"
        summary = f"Person appears {state} and {moving}; no other people detected in view."
        return SpaceAnalysis(
            request_id=snapshot.request_id,
            captured_at="",
            person_state=state,
            room_summary=summary,
            risk_observations=risks,
            alert_recommendation=rec,
            uncertain=False,
        )


class VlmSpaceAnalyzer(SpaceAnalyzer):
    """Provider-neutral multimodal adapter.

    ``infer(image) -> dict`` is any injected callable (on-device small VLM by
    default, a cloud model only as an evaluated fallback). This class owns the
    *validation* so a malformed or hostile response can never leak through:
    unknown recommendation -> 'check', any exception/None -> uncertain.
    """

    def __init__(self, infer: Callable[[object], Optional[dict]]) -> None:
        self._infer = infer

    def analyze(self, snapshot: Snapshot) -> SpaceAnalysis:
        try:
            raw = self._infer(snapshot.image)
        except Exception:
            raw = None
        return self._validate(snapshot.request_id, raw)

    @staticmethod
    def _validate(request_id: str, raw: Optional[dict]) -> SpaceAnalysis:
        if not isinstance(raw, dict):
            return _uncertain(request_id)

        rec = raw.get("alert_recommendation")
        if rec not in _VALID_RECS:
            rec = "check"  # unrecognized -> conservative, never silent 'none'

        risks = raw.get("risk_observations") or []
        if not isinstance(risks, list):
            risks = []

        state = raw.get("person_state")
        if state not in _VALID_STATES:
            state = "uncertain"

        summary = str(raw.get("room_summary", ""))[:500]
        if not summary:
            summary = "Analysis unavailable."

        return SpaceAnalysis(
            request_id=request_id,
            captured_at=str(raw.get("captured_at", "")),
            person_state=state,
            room_summary=summary,
            risk_observations=[str(r) for r in risks][:10],
            alert_recommendation=rec,
            uncertain=bool(raw.get("uncertain", False)) or state == "uncertain",
        )


def _uncertain(request_id: str) -> SpaceAnalysis:
    return SpaceAnalysis(
        request_id=request_id,
        captured_at="",
        person_state="uncertain",
        room_summary="Analysis unavailable.",
        risk_observations=[],
        alert_recommendation="check",
        uncertain=True,
    )
