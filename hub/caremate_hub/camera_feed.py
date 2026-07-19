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
_SOS = b"\xff\xda"  # JPEG start-of-scan
_DHT = b"\xff\xc4"  # JPEG define-Huffman-table
_MAX_BUFFER = 4 * 1024 * 1024  # guard against unbounded growth on a bad stream


def _build_standard_dht() -> bytes:
    """The standard JPEG (Annex K) Huffman tables as one DHT segment.

    Motion-JPEG webcams (the Logitech C270 included) emit frames with an ``AVI1``
    marker and NO Huffman table, relying on the decoder to supply a default. Strict
    decoders — notably iOS ``CGImageSource``/``UIImage`` — refuse such frames
    ("failed to create image"), so the app's live feed renders empty even though
    valid pixels arrive. Injecting these standard tables makes every frame a
    complete, standards-compliant JPEG that decodes everywhere.
    """
    def table(idbyte, counts, values):
        return bytes([idbyte]) + bytes(counts) + bytes(values)

    dc_lum_c = [0, 1, 5, 1, 1, 1, 1, 1, 1, 0, 0, 0, 0, 0, 0, 0]
    dc_chr_c = [0, 3, 1, 1, 1, 1, 1, 1, 1, 1, 1, 0, 0, 0, 0, 0]
    dc_v = list(range(12))
    ac_lum_c = [0, 2, 1, 3, 3, 2, 4, 3, 5, 5, 4, 4, 0, 0, 1, 0x7d]
    ac_lum_v = [
        0x01, 0x02, 0x03, 0x00, 0x04, 0x11, 0x05, 0x12, 0x21, 0x31, 0x41, 0x06, 0x13, 0x51, 0x61, 0x07,
        0x22, 0x71, 0x14, 0x32, 0x81, 0x91, 0xa1, 0x08, 0x23, 0x42, 0xb1, 0xc1, 0x15, 0x52, 0xd1, 0xf0,
        0x24, 0x33, 0x62, 0x72, 0x82, 0x09, 0x0a, 0x16, 0x17, 0x18, 0x19, 0x1a, 0x25, 0x26, 0x27, 0x28,
        0x29, 0x2a, 0x34, 0x35, 0x36, 0x37, 0x38, 0x39, 0x3a, 0x43, 0x44, 0x45, 0x46, 0x47, 0x48, 0x49,
        0x4a, 0x53, 0x54, 0x55, 0x56, 0x57, 0x58, 0x59, 0x5a, 0x63, 0x64, 0x65, 0x66, 0x67, 0x68, 0x69,
        0x6a, 0x73, 0x74, 0x75, 0x76, 0x77, 0x78, 0x79, 0x7a, 0x83, 0x84, 0x85, 0x86, 0x87, 0x88, 0x89,
        0x8a, 0x92, 0x93, 0x94, 0x95, 0x96, 0x97, 0x98, 0x99, 0x9a, 0xa2, 0xa3, 0xa4, 0xa5, 0xa6, 0xa7,
        0xa8, 0xa9, 0xaa, 0xb2, 0xb3, 0xb4, 0xb5, 0xb6, 0xb7, 0xb8, 0xb9, 0xba, 0xc2, 0xc3, 0xc4, 0xc5,
        0xc6, 0xc7, 0xc8, 0xc9, 0xca, 0xd2, 0xd3, 0xd4, 0xd5, 0xd6, 0xd7, 0xd8, 0xd9, 0xda, 0xe1, 0xe2,
        0xe3, 0xe4, 0xe5, 0xe6, 0xe7, 0xe8, 0xe9, 0xea, 0xf1, 0xf2, 0xf3, 0xf4, 0xf5, 0xf6, 0xf7, 0xf8,
        0xf9, 0xfa,
    ]
    ac_chr_c = [0, 2, 1, 2, 4, 4, 3, 4, 7, 5, 4, 4, 0, 1, 2, 0x77]
    ac_chr_v = [
        0x00, 0x01, 0x02, 0x03, 0x11, 0x04, 0x05, 0x21, 0x31, 0x06, 0x12, 0x41, 0x51, 0x07, 0x61, 0x71,
        0x13, 0x22, 0x32, 0x81, 0x08, 0x14, 0x42, 0x91, 0xa1, 0xb1, 0xc1, 0x09, 0x23, 0x33, 0x52, 0xf0,
        0x15, 0x62, 0x72, 0xd1, 0x0a, 0x16, 0x24, 0x34, 0xe1, 0x25, 0xf1, 0x17, 0x18, 0x19, 0x1a, 0x26,
        0x27, 0x28, 0x29, 0x2a, 0x35, 0x36, 0x37, 0x38, 0x39, 0x3a, 0x43, 0x44, 0x45, 0x46, 0x47, 0x48,
        0x49, 0x4a, 0x53, 0x54, 0x55, 0x56, 0x57, 0x58, 0x59, 0x5a, 0x63, 0x64, 0x65, 0x66, 0x67, 0x68,
        0x69, 0x6a, 0x73, 0x74, 0x75, 0x76, 0x77, 0x78, 0x79, 0x7a, 0x82, 0x83, 0x84, 0x85, 0x86, 0x87,
        0x88, 0x89, 0x8a, 0x92, 0x93, 0x94, 0x95, 0x96, 0x97, 0x98, 0x99, 0x9a, 0xa2, 0xa3, 0xa4, 0xa5,
        0xa6, 0xa7, 0xa8, 0xa9, 0xaa, 0xb2, 0xb3, 0xb4, 0xb5, 0xb6, 0xb7, 0xb8, 0xb9, 0xba, 0xc2, 0xc3,
        0xc4, 0xc5, 0xc6, 0xc7, 0xc8, 0xc9, 0xca, 0xd2, 0xd3, 0xd4, 0xd5, 0xd6, 0xd7, 0xd8, 0xd9, 0xda,
        0xe2, 0xe3, 0xe4, 0xe5, 0xe6, 0xe7, 0xe8, 0xe9, 0xea, 0xf2, 0xf3, 0xf4, 0xf5, 0xf6, 0xf7, 0xf8,
        0xf9, 0xfa,
    ]
    body = (table(0x00, dc_lum_c, dc_v) + table(0x10, ac_lum_c, ac_lum_v)
            + table(0x01, dc_chr_c, dc_v) + table(0x11, ac_chr_c, ac_chr_v))
    return _DHT + (len(body) + 2).to_bytes(2, "big") + body


_STANDARD_DHT = _build_standard_dht()


def ensure_huffman(frame: bytes) -> bytes:
    """Return a frame guaranteed to carry Huffman tables.

    If the frame already has a DHT in its header (before the scan), it is returned
    unchanged (idempotent); otherwise the standard tables are inserted just before
    the start-of-scan so any decoder — iOS included — can read it.
    """
    if not frame.startswith(_SOI):
        return frame
    sos = frame.find(_SOS)
    if sos < 0:
        return frame
    if _DHT in frame[:sos]:  # already has tables in the header
        return frame
    return frame[:sos] + _STANDARD_DHT + frame[sos:]


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
                    self._latest = ensure_huffman(frame)
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
