"""Bench harness: drive the fusion machine from a REAL wearable over TCP.

    python -m caremate_hub.run_live [--port 9000]

Runs the hub's cooperative pump/tick loop on a RealClock with the real
``WearableServer`` bound to a socket, so a live Glyph C6 (or a hand-typed
``nc``/``python`` client speaking the contract in
``firmware/caremate_wearable/README.md``) can push candidate_fall events and you
can watch fusion react — before the camera and MCU exist.

Bench-only stubs stand in for the not-yet-built pieces:
- Vision is stubbed to ALWAYS report "lying + still", so any real wearable
  candidate confirms after the no-motion window. This is a wiring rehearsal of
  the wearable->confirm->alert->reset path, NOT a real fall decision.
- The app auto-acknowledges a few seconds after a confirmed alert and sends the
  reset back down to the wearable, exercising the full round trip.

Quick manual client (no firmware needed):
    printf '{"version":1,"event":"candidate_fall","source":"wearable","seq":1,"uptime_ms":800,"confidence":0.9}\n' | nc 127.0.0.1 9000
"""

from __future__ import annotations

import argparse
import time

from .clock import RealClock
from .controller import MainController
from .events import Activity, AlertLevel, FusionState, VisionEvidence
from .interfaces import AppBus, VisionSource
from .mocks import MockAlertSink
from .wearable_server import WearableServer


class _AlwaysLyingVision(VisionSource):
    """BENCH STUB: pretends the camera always sees the person lying and still,
    so a real wearable candidate will confirm. Not a real detector."""

    def pump(self, now_ms: int, controller) -> None:
        controller.ingest_vision(
            VisionEvidence(at_ms=now_ms, activity=Activity.LYING,
                          motion=False, confidence=0.9, available=True)
        )

    def analyze_space(self, request_id: str, now_ms: int):
        return None  # Analyze-space not exercised in this harness


class _AutoAckApp(AppBus):
    """BENCH STUB: prints app-side status/alerts, then auto-acknowledges a
    confirmed alert after a delay and triggers the wearable reset."""

    def __init__(self, server: WearableServer, ack_after_ms: int = 5000) -> None:
        self._server = server
        self._ack_after_ms = ack_after_ms
        self._alert_at_ms = None

    def publish_status(self, state, level):
        print(f"[app  ] status: {state.value} / {level.value}")

    def publish_alert(self, state, level, detail):
        print(f"[app  ] *** ALERT: {state.value} ({level.value}) -- {detail}")
        if level is AlertLevel.CONFIRMED:
            self._alert_at_ms = None  # set on next pump via clock

    def publish_analysis(self, analysis):
        print(f"[app  ] analysis: {analysis.person_state} -- {analysis.room_summary}")

    def pump(self, now_ms, controller):
        if controller.state is FusionState.ALERTING:
            if self._alert_at_ms is None:
                self._alert_at_ms = now_ms
            elif now_ms - self._alert_at_ms >= self._ack_after_ms:
                print("[app  ] caregiver acknowledges -> reset wearable")
                controller.acknowledge()
                self._server.send_reset()
                self._alert_at_ms = None
        else:
            self._alert_at_ms = None


def main() -> None:
    parser = argparse.ArgumentParser(description="Live wearable bench harness")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=9000)
    args = parser.parse_args()

    clock = RealClock()
    server = WearableServer(clock, host=args.host, port=args.port)
    server.start()

    alert = MockAlertSink()
    app = _AutoAckApp(server)
    vision = _AlwaysLyingVision()
    controller = MainController(alert, app, vision, clock)

    sources = [server, vision, app]
    print("Ready. Point a wearable at this host:port and trigger a candidate.")
    print("(Vision is stubbed to always confirm — bench rehearsal only.)\n")
    try:
        while True:
            now = clock.now_ms()
            for src in sources:
                src.pump(now, controller)
            controller.tick(now)
            time.sleep(0.01)  # ~100 Hz cooperative loop
    except KeyboardInterrupt:
        print("\nShutting down.")
    finally:
        server.close()


if __name__ == "__main__":
    main()
