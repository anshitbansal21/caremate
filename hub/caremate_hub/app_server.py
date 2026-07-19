"""Real AppBus: the hub-side HTTP/SSE server the iOS app connects to.

Counterpart to ``mocks/appbus.py`` and sibling of ``wearable_server.py``. Runs on
the UNO Q Linux side and is the single handoff to Anshit's API layer / iOS app.

Transport (see docs/app-api.md for the full contract):
- ``GET  /events``  long-lived Server-Sent Events: status + fall-alert push
- ``GET  /status``  current status snapshot (JSON)
- ``POST /analyze`` trigger Analyze-space; returns the SpaceAnalysis (JSON)
- ``POST /ack``     acknowledge an active alert
- ``POST /cancel``  cancel / test (safe to call before real recipients exist)
- ``GET  /feed``    MJPEG annotated camera feed (if a frame provider is wired)

Threading model — preserves the controller's single-threaded invariant:
- HTTP requests run on their own threads (ThreadingHTTPServer). They NEVER touch
  the controller directly; inbound actions are enqueued and applied in ``pump()``
  on the fusion loop thread.
- ``publish_*`` (called from the fusion loop) fan out to each SSE subscriber's
  queue and update the status snapshot, both under a lock.

Auth: every endpoint requires ``Authorization: Bearer <token>`` (or ``?token=``
for the SSE/feed connections that browsers/img tags can't set headers on). The
token stays on the server; provider credentials (e.g. a VLM key) never reach the app.
"""

from __future__ import annotations

import json
import threading
import time
import uuid
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from queue import Empty, Full, Queue
from typing import Callable, Deque, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urlparse

from .clock import Clock
from .events import AlertLevel, FusionState, SpaceAnalysis
from .interfaces import AppBus

_SUB_QUEUE_MAX = 64
_ANALYZE_TIMEOUT_S = 6.0


class HttpAppBus(AppBus):
    def __init__(
        self,
        clock: Clock,
        host: str = "0.0.0.0",
        port: int = 8080,
        token: str = "caremate-dev",
        frame_provider: Optional[Callable[[], Optional[bytes]]] = None,
        analyze_timeout_s: float = _ANALYZE_TIMEOUT_S,
        logger: Optional[Callable[[str], None]] = None,
    ) -> None:
        self.clock = clock
        self.host = host
        self.port = port
        self.token = token
        self.frame_provider = frame_provider
        self.analyze_timeout_s = analyze_timeout_s
        self.log = logger or (lambda m: print(f"[app-net] {m}"))

        self._lock = threading.Lock()
        self._subscribers: List[Queue] = []
        self._status: Dict = {"state": FusionState.READY.value,
                              "level": AlertLevel.NONE.value, "ts": 0}
        self._actions: Deque[Tuple[str, dict]] = deque()
        self._pending: Dict[str, dict] = {}   # request_id -> {event, result}
        self._server: Optional[ThreadingHTTPServer] = None
        self._thread: Optional[threading.Thread] = None

    # ------------------------------------------------------------------ #
    # Lifecycle
    # ------------------------------------------------------------------ #
    def start(self) -> int:
        server = ThreadingHTTPServer((self.host, self.port), _Handler)
        server.bus = self  # type: ignore[attr-defined]
        self.port = server.server_address[1]
        self._server = server
        self._thread = threading.Thread(target=server.serve_forever, daemon=True)
        self._thread.start()
        self.log(f"listening on {self.host}:{self.port}")
        return self.port

    def close(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None

    # ------------------------------------------------------------------ #
    # AppBus: outbound (called on the fusion-loop thread)
    # ------------------------------------------------------------------ #
    def publish_status(self, state: FusionState, level: AlertLevel) -> None:
        snap = {"state": state.value, "level": level.value, "ts": self.clock.now_ms()}
        with self._lock:
            self._status = snap
        self._broadcast({"type": "status", **snap})

    def publish_alert(self, state: FusionState, level: AlertLevel, detail: str) -> None:
        snap = {"state": state.value, "level": level.value, "ts": self.clock.now_ms()}
        with self._lock:
            self._status = snap
        self._broadcast({"type": "alert", "detail": detail, **snap})

    def publish_analysis(self, analysis: SpaceAnalysis) -> None:
        msg = {
            "type": "analysis",
            "request_id": analysis.request_id,
            "person_state": analysis.person_state,
            "room_summary": analysis.room_summary,
            "risk_observations": list(analysis.risk_observations),
            "alert_recommendation": analysis.alert_recommendation,
            "uncertain": analysis.uncertain,
            "captured_at": analysis.captured_at,
            "ts": self.clock.now_ms(),
        }
        with self._lock:
            pending = self._pending.get(analysis.request_id)
            if pending is not None:
                pending["result"] = analysis
                pending["event"].set()
        self._broadcast(msg)

    # ------------------------------------------------------------------ #
    # AppBus: inbound (drained on the fusion-loop thread)
    # ------------------------------------------------------------------ #
    def pump(self, now_ms: int, controller) -> None:
        while True:
            with self._lock:
                if not self._actions:
                    return
                action, payload = self._actions.popleft()
            if action == "ack":
                controller.acknowledge()
            elif action == "cancel":
                controller.cancel()
            elif action == "analyze":
                controller.request_analysis(payload["request_id"])

    # ------------------------------------------------------------------ #
    # Internals used by the request handler
    # ------------------------------------------------------------------ #
    def snapshot(self) -> Dict:
        with self._lock:
            return dict(self._status)

    def enqueue_action(self, action: str, payload: Optional[dict] = None) -> None:
        with self._lock:
            self._actions.append((action, payload or {}))

    def request_analysis_blocking(self) -> SpaceAnalysis:
        """Called on an HTTP thread. Enqueues an analyze action and waits for the
        correlated result to be published, timing out to an uncertain result so
        the request never hangs."""
        rid = "req-" + uuid.uuid4().hex[:12]
        event = threading.Event()
        with self._lock:
            self._pending[rid] = {"event": event, "result": None}
        self.enqueue_action("analyze", {"request_id": rid})
        got = event.wait(timeout=self.analyze_timeout_s)
        with self._lock:
            entry = self._pending.pop(rid, None)
        result = entry.get("result") if entry else None
        if got and result is not None:
            return result
        return SpaceAnalysis(
            request_id=rid, captured_at="", person_state="uncertain",
            room_summary="Analysis timed out.", risk_observations=[],
            alert_recommendation="check", uncertain=True,
        )

    def add_subscriber(self) -> Queue:
        q: Queue = Queue(maxsize=_SUB_QUEUE_MAX)
        with self._lock:
            self._subscribers.append(q)
        return q

    def remove_subscriber(self, q: Queue) -> None:
        with self._lock:
            if q in self._subscribers:
                self._subscribers.remove(q)

    def _broadcast(self, msg: dict) -> None:
        with self._lock:
            subs = list(self._subscribers)
        for q in subs:
            try:
                q.put_nowait(msg)
            except Full:
                pass  # a slow subscriber drops events rather than blocking fusion


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    # Silence default stderr logging; route through the bus logger if desired.
    def log_message(self, fmt, *args):  # noqa: A003
        return

    @property
    def bus(self) -> HttpAppBus:
        return self.server.bus  # type: ignore[attr-defined]

    # -- helpers -------------------------------------------------------- #
    def _authorized(self) -> bool:
        auth = self.headers.get("Authorization", "")
        token = auth[7:] if auth.startswith("Bearer ") else None
        if token is None:
            q = parse_qs(urlparse(self.path).query)
            token = (q.get("token") or [None])[0]
        return token == self.bus.token

    def _reject(self) -> None:
        self._json(401, {"error": "unauthorized"})

    def _json(self, code: int, obj: dict) -> None:
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0) or 0)
        if not length:
            return {}
        try:
            return json.loads(self.rfile.read(length) or b"{}")
        except (ValueError, UnicodeDecodeError):
            return {}

    # -- routing -------------------------------------------------------- #
    def do_GET(self):  # noqa: N802
        if not self._authorized():
            return self._reject()
        path = urlparse(self.path).path
        if path == "/status":
            return self._json(200, self.bus.snapshot())
        if path == "/events":
            return self._serve_events()
        if path == "/feed":
            return self._serve_feed()
        return self._json(404, {"error": "not found"})

    def do_POST(self):  # noqa: N802
        if not self._authorized():
            return self._reject()
        path = urlparse(self.path).path
        self._read_body()  # drain/ignore; actions currently take no payload
        if path == "/ack":
            self.bus.enqueue_action("ack")
            return self._json(202, {"accepted": "ack"})
        if path == "/cancel":
            self.bus.enqueue_action("cancel")
            return self._json(202, {"accepted": "cancel"})
        if path == "/analyze":
            analysis = self.bus.request_analysis_blocking()
            return self._json(200, {
                "request_id": analysis.request_id,
                "person_state": analysis.person_state,
                "room_summary": analysis.room_summary,
                "risk_observations": list(analysis.risk_observations),
                "alert_recommendation": analysis.alert_recommendation,
                "uncertain": analysis.uncertain,
                "captured_at": analysis.captured_at,
            })
        return self._json(404, {"error": "not found"})

    # -- streaming ------------------------------------------------------ #
    def _serve_events(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        q = self.bus.add_subscriber()
        try:
            self._sse({"type": "status", **self.bus.snapshot()})  # current state on connect
            while True:
                try:
                    msg = q.get(timeout=15)
                except Empty:
                    self.wfile.write(b": ping\n\n")
                    self.wfile.flush()
                    continue
                self._sse(msg)
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            self.bus.remove_subscriber(q)

    def _sse(self, obj: dict) -> None:
        self.wfile.write(b"data: " + json.dumps(obj).encode() + b"\n\n")
        self.wfile.flush()

    def _serve_feed(self) -> None:
        provider = self.bus.frame_provider
        if provider is None:
            return self._json(503, {"error": "no camera feed wired"})
        self.send_response(200)
        self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        try:
            while True:
                jpg = provider()
                if jpg is None:
                    time.sleep(0.05)
                    continue
                self.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\n")
                self.wfile.write(f"Content-Length: {len(jpg)}\r\n\r\n".encode())
                self.wfile.write(jpg)
                self.wfile.write(b"\r\n")
                self.wfile.flush()
                time.sleep(0.05)  # ~20 fps cap; real rate follows the provider
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
