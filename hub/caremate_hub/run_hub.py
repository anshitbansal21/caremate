"""run_hub — launch the whole CareMate hub as one process.

Wires all four real components into a single cooperative loop on a RealClock:

    WearableServer   (TCP JSON from the ESP32)          --> WearableSource
    PoseVisionSource (YOLOv8n-pose)  or  ScriptedVision --> VisionSource
    MockAlertSink    or  SerialAlertSink (MCU)          --> AlertSink
    HttpAppBus       (SSE + REST for the iOS app)       --> AppBus

Runs anywhere by default (scripted vision, mock alerts) so you get one command to
bring the hub up; flags swap in real hardware as it comes online.

    python -m caremate_hub.run_hub                 # headless: hub up, idle vision
    python -m caremate_hub.run_hub --demo          # inject a scripted fall after 3 s
    python -m caremate_hub.run_hub --camera        # real webcam + YOLOv8n-pose
    python -m caremate_hub.run_hub --serial /dev/ttyACM0   # real MCU alert output
    python -m caremate_hub.run_hub --demo --seconds 8      # bounded run (smoke test)

Bench stubs are clearly labelled; --camera and a connected wearable make it real.
"""

from __future__ import annotations

import argparse
import time
from typing import Optional

from .app_server import HttpAppBus
from .clock import RealClock
from .controller import MainController
from .events import Activity, CandidateFall, SpaceAnalysis, VisionEvidence
from .interfaces import VisionSource
from .mocks import MockAlertSink, SerialAlertSink
from .wearable_server import WearableServer


class ScriptedVision(VisionSource):
    """Bench stand-in for the camera when no webcam is present. Reports STANDING;
    in --demo it reports LYING + still after a trigger so the confirm->alert->app
    path runs with zero hardware. Not a real detector."""

    def __init__(self, clock, demo: bool = False, demo_at_ms: int = 3000) -> None:
        self.clock = clock
        self.demo = demo
        self.demo_at_ms = demo_at_ms
        self._start_ms: Optional[int] = None

    def _lying_now(self, now_ms: int) -> bool:
        if not self.demo or self._start_ms is None:
            return False
        return now_ms - self._start_ms >= self.demo_at_ms

    def pump(self, now_ms: int, controller) -> None:
        if self._start_ms is None:
            self._start_ms = now_ms
        lying = self._lying_now(now_ms)
        controller.ingest_vision(VisionEvidence(
            at_ms=now_ms,
            activity=Activity.LYING if lying else Activity.STANDING,
            motion=False,
            confidence=0.9,
            available=True,
        ))

    def analyze_space(self, request_id: str, now_ms: int) -> SpaceAnalysis:
        lying = self._lying_now(now_ms)
        state = "lying" if lying else "standing"
        return SpaceAnalysis(
            request_id=request_id, captured_at="", person_state=state,
            room_summary=f"Person appears {state} (scripted bench vision).",
            risk_observations=["person lying and not moving"] if lying else [],
            alert_recommendation="check" if lying else "none", uncertain=False,
        )


def _build_vision(args, clock):
    if args.camera:
        from .vision import PoseVisionSource  # lazy: pulls ultralytics/cv2
        from .vision.backends import YoloPoseBackend
        backend = YoloPoseBackend(model_path=args.model, camera=args.cam_index, imgsz=args.imgsz)
        vision = PoseVisionSource(backend, clock)
        vision.start()  # inference on a worker thread
        return vision, True
    return ScriptedVision(clock, demo=args.demo, demo_at_ms=args.demo_after * 1000), False


def _build_alert(args):
    if args.serial:
        try:
            import serial  # pyserial, optional
        except ImportError:
            raise SystemExit("--serial needs pyserial: pip install pyserial")
        ser = serial.Serial(args.serial, args.baud, timeout=0)
        return SerialAlertSink(lambda s: ser.write(s.encode()))
    return MockAlertSink()


def main() -> None:
    p = argparse.ArgumentParser(description="Launch the CareMate hub")
    p.add_argument("--host", default="0.0.0.0")
    p.add_argument("--port", type=int, default=8080, help="app HTTP/SSE port")
    p.add_argument("--wearable-port", type=int, default=9000)
    p.add_argument("--token", default="caremate-dev", help="app bearer token")
    p.add_argument("--camera", action="store_true", help="use a real webcam + YOLOv8n-pose")
    p.add_argument("--cam-index", type=int, default=0)
    p.add_argument("--model", default="yolov8n-pose.pt")
    p.add_argument("--imgsz", type=int, default=480)
    p.add_argument("--feed-camera", action="store_true",
                   help="serve a live MJPEG /feed from a UVC webcam via v4l2-ctl "
                        "(dependency-free, un-annotated; no ultralytics/opencv)")
    p.add_argument("--feed-device", default="/dev/video0",
                   help="V4L2 device for --feed-camera")
    p.add_argument("--analyze-onnx", default=None, metavar="MODEL.onnx",
                   help="run Analyze-space with on-device YOLOv8-pose via onnxruntime "
                        "(single-frame, on demand). Uses the webcam frames; implies a camera.")
    p.add_argument("--serial", default=None, help="MCU serial device for real alerts")
    p.add_argument("--baud", type=int, default=115200)
    p.add_argument("--demo", action="store_true", help="inject a scripted fall (no hardware)")
    p.add_argument("--demo-after", type=int, default=3, help="seconds before the scripted fall")
    p.add_argument("--seconds", type=int, default=0, help="auto-stop after N seconds (0 = run forever)")
    args = p.parse_args()

    clock = RealClock()
    wearable = WearableServer(clock, host=args.host, port=args.wearable_port)

    # One shared webcam feeds both the live /feed and on-demand Analyze-space.
    camera = None
    if args.feed_camera or args.analyze_onnx:
        from .camera_feed import V4l2MjpegCamera
        camera = V4l2MjpegCamera(device=args.feed_device)
        camera.start()
        time.sleep(2.0)  # let the C270 auto-exposure settle before frames go live
    frame_provider = camera.latest_jpeg if (args.feed_camera and camera) else None
    app = HttpAppBus(clock, host=args.host, port=args.port, token=args.token,
                     frame_provider=frame_provider)
    alert = _build_alert(args)

    if args.analyze_onnx:
        from .vision.onnx_pose import OnDemandPoseVision, OnnxPoseModel
        vision = OnDemandPoseVision(camera, OnnxPoseModel(args.analyze_onnx), clock)
        threaded_vision = False
    else:
        vision, threaded_vision = _build_vision(args, clock)

    wearable.start()
    app.start()
    controller = MainController(alert, app, vision, clock)

    _banner(args, app, wearable)

    sources = [wearable, vision, app]
    start_ms = clock.now_ms()
    fired = False
    try:
        while True:
            now = clock.now_ms()
            if args.demo and not fired and now - start_ms >= args.demo_after * 1000:
                controller.ingest_candidate(CandidateFall(
                    source="demo", uptime_ms=now, confidence=0.95, received_at_ms=now))
                print("[demo ] injected scripted candidate_fall")
                fired = True
            for src in sources:
                src.pump(now, controller)
            controller.tick(now)
            if args.seconds and now - start_ms >= args.seconds * 1000:
                break
            time.sleep(0.01)  # ~100 Hz cooperative loop
    except KeyboardInterrupt:
        print("\nShutting down.")
    finally:
        wearable.close()
        app.close()
        if camera is not None:
            camera.close()
        if threaded_vision:
            vision.close()


def _banner(args, app, wearable) -> None:
    vsrc = "webcam + YOLOv8n-pose" if args.camera else (
        "scripted (DEMO fall)" if args.demo else "scripted (idle)")
    asink = f"serial {args.serial}" if args.serial else "mock (prints)"
    print("CareMate hub is up.")
    print(f"  app API     http://<hub-ip>:{app.port}   token: {args.token}")
    print(f"  wearable    tcp://<hub-ip>:{wearable.port}   (ESP32 candidate events)")
    print(f"  vision      {vsrc}")
    print(f"  alerts      {asink}")
    feed_desc = "live MJPEG (v4l2 webcam)" if args.feed_camera else (
        "503 until a frame provider is wired")
    print(f"  feed        /feed  {feed_desc}\n")
    print("  try:  curl -H 'Authorization: Bearer %s' http://127.0.0.1:%d/status" % (args.token, app.port))
    print("        curl -N -H 'Authorization: Bearer %s' http://127.0.0.1:%d/events\n" % (args.token, app.port))


if __name__ == "__main__":
    main()
