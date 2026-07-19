"""Dependency-free live camera feed for the hub's ``/feed`` endpoint.

Wraps a single, continuous ``v4l2-ctl`` MJPEG capture of a UVC webcam (the
Logitech C270 on the UNO Q) and exposes the latest JPEG frame through a
``latest_jpeg()`` callable — exactly the ``frame_provider`` shape
``HttpAppBus`` expects. No OpenCV, no ultralytics: just the ``v4l2-ctl`` binary
that ships on the board plus the standard library, so a plain live feed works
long before the heavier YOLO-pose annotation path is deployed.

Why one long-lived capture (not a frame grab per request): the C270 resets
auto-exposure every time the device is reopened, so per-frame ``v4l2-ctl`` calls
come back black. A single streaming session keeps exposure settled and yields a
smooth feed. A background thread splits the MJPEG byte stream on JPEG SOI/EOI
markers and keeps only the most recent complete frame.

This is the un-annotated feed. When pose annotation lands, an annotating provider
can replace ``latest_jpeg`` without touching ``app_server``/``run_hub``.
"""

from __future__ import annotations

import subprocess
import threading
from typing import Optional

_SOI = b"\xff\xd8"  # JPEG start-of-image
_EOI = b"\xff\xd9"  # JPEG end-of-image
_MAX_BUFFER = 4 * 1024 * 1024  # guard against unbounded growth on a bad stream


class V4l2MjpegCamera:
    """Continuous MJPEG capture of a V4L2 webcam via the ``v4l2-ctl`` binary.

    ``latest_jpeg()`` returns the most recent complete JPEG frame (bytes) or
    ``None`` before the first frame / after the camera stops — the same contract
    ``HttpAppBus(frame_provider=...)`` expects.
    """

    def __init__(
        self,
        device: str = "/dev/video0",
        width: int = 640,
        height: int = 480,
    ) -> None:
        self.device = device
        self.width = width
        self.height = height
        self._latest: Optional[bytes] = None
        self._lock = threading.Lock()
        self._proc: Optional[subprocess.Popen] = None
        self._thread: Optional[threading.Thread] = None
        self._running = False

    def start(self) -> None:
        cmd = [
            "v4l2-ctl",
            "-d", self.device,
            f"--set-fmt-video=width={self.width},height={self.height},pixelformat=MJPG",
            "--stream-mmap",
            "--stream-count=0",   # 0 = stream continuously
            "--stream-to=-",      # write the MJPEG byte stream to stdout
        ]
        self._proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0
        )
        self._running = True
        self._thread = threading.Thread(target=self._reader, daemon=True)
        self._thread.start()

    def _reader(self) -> None:
        buf = b""
        assert self._proc is not None and self._proc.stdout is not None
        stream = self._proc.stdout
        while self._running:
            chunk = stream.read(8192)
            if not chunk:
                break
            buf += chunk
            # Pull out every complete JPEG in the buffer, keep the last one.
            while True:
                start = buf.find(_SOI)
                if start < 0:
                    break
                end = buf.find(_EOI, start + 2)
                if end < 0:
                    break
                frame = buf[start:end + 2]
                buf = buf[end + 2:]
                with self._lock:
                    self._latest = frame
            if len(buf) > _MAX_BUFFER:  # never seen a full frame — resync
                buf = buf[-_MAX_BUFFER:]

    def latest_jpeg(self) -> Optional[bytes]:
        with self._lock:
            return self._latest

    def close(self) -> None:
        self._running = False
        if self._proc is not None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self._proc.kill()
            self._proc = None
