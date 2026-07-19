"""Runnable demo: exercises the two demo-script acceptance scenarios headless.

    python -m caremate_hub          # run both scenarios in accelerated sim time

Scenario 1 (Live fall detection): wearable candidate -> vision confirms lying +
no-motion -> local alert fires -> app shows the alert -> app acknowledges.

Scenario 2 (Live query / Analyze space): app requests analysis -> vision layer
returns a person/room summary -> app shows it, no alert.

No hardware, camera, wearable, MCU, or Wi-Fi involved — all four interfaces are
mocked, so this is a bench rehearsal of the fusion logic only.
"""

from __future__ import annotations

from .clock import ManualClock
from .controller import MainController
from .events import Activity, SpaceAnalysis
from .mocks import MockAlertSink, MockAppBus, MockVision, MockWearable


def _run_sim(clock: ManualClock, controller, sources, duration_ms: int, step_ms: int = 20) -> None:
    while clock.now_ms() <= duration_ms:
        now = clock.now_ms()
        for src in sources:
            src.pump(now, controller)
        controller.tick(now)
        clock.advance(step_ms)


def scenario_live_fall() -> None:
    print("\n=== Scenario 1: Live fall detection ===")
    clock = ManualClock()

    wearable = MockWearable(schedule=[(800, 0.9)])  # candidate at t=800ms
    vision = MockVision(
        timeline=[
            (0, Activity.WALKING, True, 0.85, True),    # walking around
            (600, Activity.LYING, False, 0.88, True),   # collapses and stays still
        ]
    )
    app = MockAppBus(schedule=[(6000, "ack")])          # caregiver acks on the app
    alert = MockAlertSink()

    controller = MainController(alert, app, vision, clock)
    _run_sim(clock, controller, [wearable, vision, app], duration_ms=7000)


def scenario_analyze_space() -> None:
    print("\n=== Scenario 2: Live query (Analyze space) ===")
    clock = ManualClock()

    wearable = MockWearable(schedule=[])                 # no fall
    vision = MockVision(
        timeline=[(0, Activity.ON_BED, False, 0.9, True)],
        analysis_result=SpaceAnalysis(
            request_id="",
            captured_at="2026-07-19T10:00:00Z",
            person_state="on_bed",
            room_summary="Person resting on the bed; floor clear of obstruction.",
            risk_observations=[],
            alert_recommendation="none",
            uncertain=False,
        ),
    )
    app = MockAppBus(schedule=[(1000, "analyze")])       # app taps "Analyze space"
    alert = MockAlertSink()

    controller = MainController(alert, app, vision, clock)
    _run_sim(clock, controller, [wearable, vision, app], duration_ms=2000)


def main() -> None:
    scenario_live_fall()
    scenario_analyze_space()
    print("\nDone. Both demo-script scenarios ran headless.")


if __name__ == "__main__":
    main()
