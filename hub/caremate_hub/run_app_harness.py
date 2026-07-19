"""Mac-only test harness for the real HttpAppBus phone contract.

This is not the production hub and never produces live safety evidence. It
serves one explicitly supplied JPEG as a repeating MJPEG feed and sends it to an
explicitly selected local Ollama vision model for Analyze-space requests.
"""

from __future__ import annotations

import argparse
import threading
import time
from pathlib import Path

from .app_server import HttpAppBus
from .clock import RealClock
from .events import AlertLevel, FusionState
from .vision import VlmSpaceAnalyzer
from .vision.analyze import Snapshot
from .vision.ollama_adapter import OllamaVisionInference


class _HarnessController:
    def __init__(self, bus: HttpAppBus, image: bytes, analyzer: VlmSpaceAnalyzer) -> None:
        self.bus = bus
        self.image = image
        self.analyzer = analyzer

    def acknowledge(self) -> None:
        self.bus.publish_status(FusionState.READY, AlertLevel.NONE)

    def cancel(self) -> None:
        self.bus.publish_status(FusionState.READY, AlertLevel.NONE)

    def request_analysis(self, request_id: str) -> None:
        result = self.analyzer.analyze(
            Snapshot(request_id=request_id, evidence=None, image=self.image)
        )
        self.bus.publish_analysis(result)


def _load_jpeg(path: Path) -> bytes:
    data = path.read_bytes()
    if len(data) < 4 or not data.startswith(b"\xff\xd8") or not data.endswith(b"\xff\xd9"):
        raise ValueError(f"{path} is not a complete JPEG")
    return data


def main() -> None:
    parser = argparse.ArgumentParser(description="CareMate TEST DATA Mac app harness")
    parser.add_argument("--image", required=True, type=Path, help="consented/test JPEG")
    parser.add_argument("--model", required=True, help="installed Ollama vision model")
    parser.add_argument("--token", required=True, help="temporary LAN bearer token")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--analysis-timeout", type=float, default=30.0)
    parser.add_argument(
        "--simulate-fall",
        action="store_true",
        help="publish one possible-to-confirmed TEST transition after startup",
    )
    args = parser.parse_args()

    image = _load_jpeg(args.image)
    clock = RealClock()
    inference = OllamaVisionInference(args.model, timeout_s=args.analysis_timeout)
    analyzer = VlmSpaceAnalyzer(inference)
    bus = HttpAppBus(
        clock,
        host=args.host,
        port=args.port,
        token=args.token,
        frame_provider=lambda: image,
        analyze_timeout_s=args.analysis_timeout + 1,
    )
    controller = _HarnessController(bus, image, analyzer)
    bus.start()
    bus.publish_status(FusionState.READY, AlertLevel.NONE)

    if args.simulate_fall:
        def publish_test_transition() -> None:
            time.sleep(3)
            bus.publish_status(FusionState.AWAITING_VISION, AlertLevel.POSSIBLE)
            time.sleep(3)
            bus.publish_alert(
                FusionState.CONFIRMED_FALL,
                AlertLevel.CONFIRMED,
                "TEST DATA: synthetic vision confirmation",
            )

        threading.Thread(target=publish_test_transition, daemon=True).start()

    print("\n*** TEST DATA — NOT LIVE ***")
    print(f"App API listening on http://<this-mac-ip>:{bus.port}")
    print(f"Fixture: {args.image}")
    print(f"Ollama model: {args.model}")
    print("Press Ctrl-C to stop.\n")
    try:
        while True:
            bus.pump(clock.now_ms(), controller)
            time.sleep(0.01)
    except KeyboardInterrupt:
        print("\nStopping test harness.")
    finally:
        bus.close()


if __name__ == "__main__":
    main()
