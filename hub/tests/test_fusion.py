"""Failure-path and happy-path tests for the fusion machine.

Run with pytest, or directly: ``python hub/tests/test_fusion.py``.
No hardware or third-party deps required.

Covers, per CLAUDE.md's "failure-path tests for alert changes":
- confirm path (wearable candidate + sustained lying/no-motion)
- reject path (vision shows the person upright)
- uncertain path when the vision window elapses with no confirmation
- uncertain path when the camera is unavailable/occluded
- sub-threshold candidate is ignored
- confirmed alert clears on acknowledge
- Analyze-space recommendation can raise a check but never confirms a fall
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from caremate_hub.clock import ManualClock
from caremate_hub.controller import MainController
from caremate_hub.events import (
    Activity,
    AlertLevel,
    CandidateFall,
    FusionState,
    SpaceAnalysis,
    VisionEvidence,
)
from caremate_hub.interfaces import AlertSink, AppBus, VisionSource


class RecordingAlert(AlertSink):
    def __init__(self):
        self.status = []

    def set_status(self, state, level):
        self.status.append((state, level))

    def show(self, line1, line2=""):
        pass


class RecordingApp(AppBus):
    def __init__(self):
        self.alerts = []
        self.statuses = []
        self.analyses = []

    def publish_status(self, state, level):
        self.statuses.append((state, level))

    def publish_alert(self, state, level, detail):
        self.alerts.append((state, level, detail))

    def publish_analysis(self, analysis):
        self.analyses.append(analysis)

    def pump(self, now_ms, controller):
        pass


class ProgrammableVision(VisionSource):
    """Returns whatever evidence/analysis the test sets, on demand."""

    def __init__(self):
        self.evidence = None
        self.analysis = None

    def pump(self, now_ms, controller):
        if self.evidence is not None:
            act, motion, conf, avail = self.evidence
            controller.ingest_vision(
                VisionEvidence(now_ms, act, motion, conf, avail)
            )

    def analyze_space(self, request_id, now_ms):
        return self.analysis


def _build(cfg=None):
    clock = ManualClock()
    alert, app, vision = RecordingAlert(), RecordingApp(), ProgrammableVision()
    controller = MainController(alert, app, vision, clock, config=cfg,
                                logger=lambda m: None)
    return clock, controller, alert, app, vision


def _advance(clock, controller, sources, ms, step=20):
    end = clock.now_ms() + ms
    while clock.now_ms() <= end:
        now = clock.now_ms()
        for s in sources:
            s.pump(now, controller)
        controller.tick(now)
        clock.advance(step)


def _candidate(now, conf=0.9):
    return CandidateFall("wearable", uptime_ms=now, confidence=conf, received_at_ms=now)


def test_confirm_path():
    clock, controller, alert, app, vision = _build()
    vision.evidence = (Activity.LYING, False, 0.9, True)  # lying, still
    controller.ingest_candidate(_candidate(clock.now_ms()))
    assert controller.state is FusionState.AWAITING_VISION
    _advance(clock, controller, [vision], ms=4000)
    assert controller.state is FusionState.ALERTING
    assert any(l is AlertLevel.CONFIRMED for _, l, _ in app.alerts)


def test_reject_path():
    clock, controller, alert, app, vision = _build()
    vision.evidence = (Activity.STANDING, True, 0.9, True)  # clearly upright
    controller.ingest_candidate(_candidate(clock.now_ms()))
    _advance(clock, controller, [vision], ms=1000)
    assert controller.state is FusionState.READY
    assert not app.alerts


def test_uncertain_on_timeout():
    clock, controller, alert, app, vision = _build()
    vision.evidence = (Activity.SITTING, True, 0.3, True)  # too low-confidence to decide
    controller.ingest_candidate(_candidate(clock.now_ms()))
    _advance(clock, controller, [vision], ms=9000)  # past the 8s window
    assert controller.state is FusionState.UNCERTAIN
    assert any(l is AlertLevel.CHECK for _, l, _ in app.alerts)


def test_uncertain_when_camera_unavailable():
    clock, controller, alert, app, vision = _build()
    vision.evidence = (Activity.NOT_VISIBLE, False, 0.9, False)  # occluded / camera down
    controller.ingest_candidate(_candidate(clock.now_ms()))
    _advance(clock, controller, [vision], ms=9000)
    assert controller.state is FusionState.UNCERTAIN


def test_subthreshold_candidate_ignored():
    clock, controller, alert, app, vision = _build()
    controller.ingest_candidate(_candidate(clock.now_ms(), conf=0.1))
    assert controller.state is FusionState.READY


def test_acknowledge_clears_alert():
    clock, controller, alert, app, vision = _build()
    vision.evidence = (Activity.LYING, False, 0.9, True)
    controller.ingest_candidate(_candidate(clock.now_ms()))
    _advance(clock, controller, [vision], ms=4000)
    assert controller.state is FusionState.ALERTING
    controller.acknowledge()
    assert controller.state is FusionState.READY


def test_analysis_never_confirms_but_can_check():
    clock, controller, alert, app, vision = _build()
    vision.analysis = SpaceAnalysis(
        request_id="a1", captured_at="", person_state="lying",
        room_summary="on the floor", risk_observations=["on floor"],
        alert_recommendation="alert", uncertain=False,
    )
    controller.request_analysis("a1")
    # advisory-only: raises a check, never a confirmed fall
    assert controller.state is FusionState.UNCERTAIN
    assert not any(l is AlertLevel.CONFIRMED for _, l, _ in app.alerts)


def _run_all():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"\n{len(tests)} passed")


if __name__ == "__main__":
    _run_all()
