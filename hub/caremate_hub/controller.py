"""MainController — the abstracted fusion brain of the vision hub.

It owns the fall-fusion state machine and drives the local alert output and the
app, talking only through the four interfaces. It is the single place the
"confirmed fall" decision is made, combining wearable candidates, streamed
vision evidence, recency, and (advisory) Analyze-space output.

Design invariants:
- A wearable candidate is never treated as a confirmed fall.
- Vision / model output is evidence, never the sole alert authority.
- Missing or stale evidence yields "uncertain — check user", never silence.
- All timing is non-blocking and driven by ``tick(now_ms)``.
"""

from __future__ import annotations

from typing import Callable, Optional

from .clock import Clock
from .config import FusionConfig
from .events import (
    AlertLevel,
    CandidateFall,
    FusionState,
    SpaceAnalysis,
    VisionEvidence,
)
from .fusion import VisionVerdict, classify_vision
from .interfaces import AlertSink, AppBus, VisionSource


class MainController:
    def __init__(
        self,
        alert_sink: AlertSink,
        app_bus: AppBus,
        vision_source: VisionSource,
        clock: Clock,
        config: Optional[FusionConfig] = None,
        logger: Optional[Callable[[str], None]] = None,
    ) -> None:
        self.alert = alert_sink
        self.app = app_bus
        self.vision = vision_source
        self.clock = clock
        self.cfg = config or FusionConfig()
        self.log = logger or (lambda m: print(f"[controller] {m}"))

        self.state: FusionState = FusionState.READY
        self._candidate: Optional[CandidateFall] = None
        self._awaiting_since: Optional[int] = None
        self._confirming_since: Optional[int] = None
        self._latest_vision: Optional[VisionEvidence] = None
        self._analysis_seq = 0

    # ------------------------------------------------------------------ #
    # Inbound from sources
    # ------------------------------------------------------------------ #
    def ingest_candidate(self, cf: CandidateFall) -> None:
        if cf.confidence < self.cfg.min_candidate_confidence:
            self.log(f"candidate below threshold ({cf.confidence:.2f}); ignoring")
            return
        # Don't disturb an in-progress confirmed alert; a fresh candidate
        # otherwise (re)opens the awaiting-vision window.
        if self.state in (FusionState.ALERTING, FusionState.CONFIRMED_FALL):
            return

        self._candidate = cf
        self._awaiting_since = cf.received_at_ms
        self._confirming_since = None
        self._enter(FusionState.AWAITING_VISION)
        # CLAUDE.md: forward the candidate to the app as a visible "possible
        # fall" while vision confirmation is pending.
        self.app.publish_status(self.state, AlertLevel.POSSIBLE)
        self.alert.set_status(self.state, AlertLevel.POSSIBLE)
        self.alert.show("Possible fall", "checking camera")

    def ingest_vision(self, ev: VisionEvidence) -> None:
        self._latest_vision = ev

    # ------------------------------------------------------------------ #
    # App actions
    # ------------------------------------------------------------------ #
    def request_analysis(self, request_id: Optional[str] = None) -> SpaceAnalysis:
        """Handle the app-triggered **Analyze space** action."""
        self._analysis_seq += 1
        rid = request_id or f"analysis-{self._analysis_seq}"
        now = self.clock.now_ms()
        try:
            analysis = self.vision.analyze_space(rid, now)
        except Exception as exc:  # defense in depth; adapter should not raise
            self.log(f"analyze_space raised ({exc!r}); treating as uncertain")
            analysis = SpaceAnalysis(
                request_id=rid,
                captured_at="",
                person_state="uncertain",
                room_summary="Analysis unavailable.",
                risk_observations=[],
                alert_recommendation="check",
                uncertain=True,
            )
        # Recorded separately from fall confirmation; no raw frame stored.
        self.app.publish_analysis(analysis)
        self._consider_analysis(analysis)
        return analysis

    def acknowledge(self) -> None:
        """App acknowledges an active alert. Recorded separately from confirmation."""
        if self.state in (FusionState.ALERTING, FusionState.UNCERTAIN):
            self.log("alert acknowledged")
            self.alert.set_status(FusionState.READY, AlertLevel.NONE)
            self.alert.show("Acknowledged", "")
            self.app.publish_status(FusionState.READY, AlertLevel.NONE)
            self._reset()

    def cancel(self) -> None:
        """Test / cancel mechanism — must exist before involving real recipients."""
        self.log("cancelled/test")
        self.alert.set_status(FusionState.READY, AlertLevel.NONE)
        self.alert.show("Ready", "")
        self.app.publish_status(FusionState.READY, AlertLevel.NONE)
        self._reset()

    # ------------------------------------------------------------------ #
    # Periodic
    # ------------------------------------------------------------------ #
    def tick(self, now_ms: int) -> None:
        if self.state is FusionState.AWAITING_VISION:
            self._tick_awaiting(now_ms)

    def _tick_awaiting(self, now: int) -> None:
        ev = self._fresh_vision(now)
        verdict = classify_vision(ev, self.cfg)

        if verdict is VisionVerdict.CONFIRMING:
            if self._confirming_since is None:
                self._confirming_since = now
            if now - self._confirming_since >= self.cfg.no_motion_confirm_ms:
                self._confirm_fall("vision: lying + sustained no-motion")
                return
        else:
            self._confirming_since = None

        if verdict is VisionVerdict.REJECTING:
            self._reject("vision: person upright / on bed")
            return

        # Window elapsed with no confirming evidence: prefer "uncertain — check
        # user" over discarding a credible wearable candidate.
        assert self._awaiting_since is not None
        if now - self._awaiting_since >= self.cfg.vision_window_ms:
            self._uncertain("vision window elapsed without confirmation")

    # ------------------------------------------------------------------ #
    # Transitions
    # ------------------------------------------------------------------ #
    def _confirm_fall(self, reason: str) -> None:
        self.log(f"CONFIRMED FALL: {reason}")
        self._enter(FusionState.ALERTING)
        self.alert.set_status(FusionState.ALERTING, AlertLevel.CONFIRMED)
        self.alert.show("FALL DETECTED", "ack on app")
        self.app.publish_alert(FusionState.CONFIRMED_FALL, AlertLevel.CONFIRMED, reason)

    def _reject(self, reason: str) -> None:
        self.log(f"rejected: {reason}")
        self.alert.set_status(FusionState.READY, AlertLevel.NONE)
        self.app.publish_status(FusionState.REJECTED, AlertLevel.NONE)
        self._reset()

    def _uncertain(self, reason: str) -> None:
        self.log(f"UNCERTAIN — check user: {reason}")
        self._enter(FusionState.UNCERTAIN)
        self.alert.set_status(FusionState.UNCERTAIN, AlertLevel.CHECK)
        self.alert.show("Check on user", "no cam confirm")
        self.app.publish_alert(FusionState.UNCERTAIN, AlertLevel.CHECK, reason)

    def _consider_analysis(self, analysis: SpaceAnalysis) -> None:
        """Fold Analyze-space output into fusion as advisory evidence only.

        It can raise a *check* but can never fabricate a confirmed fall on its
        own — confirmation still requires the wearable + vision path.
        """
        if analysis.uncertain:
            return
        if self.state is FusionState.READY and analysis.alert_recommendation in ("alert", "check"):
            self._uncertain(f"analysis recommended '{analysis.alert_recommendation}'")

    # ------------------------------------------------------------------ #
    # Internals
    # ------------------------------------------------------------------ #
    def _fresh_vision(self, now: int) -> Optional[VisionEvidence]:
        ev = self._latest_vision
        if ev is None:
            return None
        if now - ev.at_ms > self.cfg.vision_staleness_ms:
            return None  # stalled camera reads as absent, not as "no fall"
        return ev

    def _enter(self, state: FusionState) -> None:
        if state != self.state:
            self.log(f"state {self.state.value} -> {state.value}")
            self.state = state

    def _reset(self, state: FusionState = FusionState.READY) -> None:
        self._candidate = None
        self._awaiting_since = None
        self._confirming_since = None
        self._enter(state)
