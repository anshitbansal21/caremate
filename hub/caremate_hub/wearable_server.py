"""Real WearableSource: the ESP32<->UNO Q message-layer server (hub side).

Counterpart to ``mocks/wearable.py``. Receives the wearable firmware's
newline-delimited JSON over a persistent TCP socket and turns ``candidate_fall``
messages into ``CandidateFall`` events for the controller. The contract is
documented in ``firmware/caremate_wearable/README.md``.

Wire messages (wearable -> hub):
    {"version":1,"event":"boot","source":"wearable","seq":1,"uptime_ms":1234}
    {"version":1,"event":"heartbeat","source":"wearable","seq":2,"uptime_ms":2734}
    {"version":1,"event":"candidate_fall","source":"wearable","seq":3,"uptime_ms":5011,"confidence":0.82}

Hub -> wearable:
    {"version":1,"event":"ack","seq":3}      # stops candidate retransmission
    {"version":1,"event":"reset"}            # caregiver acknowledged in the app

Design notes:
- ``seq`` is transport metadata (ack + dedup); it is stripped before building
  ``CandidateFall``. ``received_at_ms`` is stamped here from the injected clock,
  never sent by the wearable.
- Non-blocking throughout (``selectors`` polled inside ``pump``), so it preserves
  the controller's single-threaded, lock-free model — no background thread.
- Liveness: the newest message time per connection is tracked so a silently
  dropped wearable can be surfaced as a fault (``is_online``) rather than read as
  "no fall". Wiring that into the controller is left as a follow-up hook.
"""

from __future__ import annotations

import json
import selectors
import socket
from collections import deque
from typing import Callable, Deque, Dict, Optional, Set

from .clock import Clock
from .events import CandidateFall
from .interfaces import WearableSource

_MAX_LINE = 512          # a wearable line is ~120 bytes; guard against garbage
_DEDUP_HISTORY = 256     # per-connection recent seqs kept for duplicate rejection
_RECV_CHUNK = 1024


class _Conn:
    """Per-connection receive buffer, dedup history, and liveness timestamp."""

    def __init__(self, sock: socket.socket) -> None:
        self.sock = sock
        self.buf = bytearray()
        self.seen: Set[int] = set()
        self.seen_order: Deque[int] = deque(maxlen=_DEDUP_HISTORY)
        self.last_seen_ms: int = 0
        self.connected_at_ms: int = 0

    def remember(self, seq: int) -> bool:
        """Record ``seq``; return True if it was already seen (a duplicate)."""
        if seq in self.seen:
            return True
        if len(self.seen_order) == self.seen_order.maxlen:
            self.seen.discard(self.seen_order[0])  # evicted from the deque next
        self.seen_order.append(seq)
        self.seen.add(seq)
        return False


class WearableServer(WearableSource):
    def __init__(
        self,
        clock: Clock,
        host: str = "0.0.0.0",
        port: int = 9000,
        heartbeat_timeout_ms: int = 6000,
        reap_timeout_ms: int = 20000,
        logger: Optional[Callable[[str], None]] = None,
    ) -> None:
        self.clock = clock
        self.host = host
        self.port = port
        self.heartbeat_timeout_ms = heartbeat_timeout_ms
        # Close a connection we haven't heard a line from in this long. On a flaky
        # link the wearable reconnects (new socket) without cleanly closing the old
        # one, so dead half-open sockets accumulate; reaping keeps the set clean and
        # is_online honest. Set well above heartbeat_timeout so a merely-laggy link
        # isn't dropped.
        self.reap_timeout_ms = reap_timeout_ms
        self.log = logger or (lambda m: print(f"[wearable-net] {m}"))

        self._sel = selectors.DefaultSelector()
        self._server: Optional[socket.socket] = None
        self._conns: Dict[socket.socket, _Conn] = {}

    # ------------------------------------------------------------------ #
    # Lifecycle
    # ------------------------------------------------------------------ #
    def start(self) -> int:
        """Bind and listen (non-blocking). Returns the bound port (useful when
        port=0 lets the OS choose, e.g. in tests)."""
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind((self.host, self.port))
        srv.listen(4)
        srv.setblocking(False)
        self._sel.register(srv, selectors.EVENT_READ, data="server")
        self._server = srv
        self.port = srv.getsockname()[1]
        self.log(f"listening on {self.host}:{self.port}")
        return self.port

    def close(self) -> None:
        for conn in list(self._conns):
            self._drop(conn)
        if self._server is not None:
            try:
                self._sel.unregister(self._server)
            except KeyError:
                pass
            self._server.close()
            self._server = None

    # ------------------------------------------------------------------ #
    # WearableSource
    # ------------------------------------------------------------------ #
    def pump(self, now_ms: int, controller) -> None:
        """Drain all socket activity and deliver candidates to the controller.

        Non-blocking: ``select(timeout=0)`` returns immediately, so this fits
        inside the hub's cooperative tick loop.
        """
        if self._server is None:
            return
        for key, _ in self._sel.select(timeout=0):
            if key.data == "server":
                self._accept(now_ms)
            else:
                self._read(key.fileobj, now_ms, controller)
        self._reap(now_ms)

    def _reap(self, now_ms: int) -> None:
        """Close connections that have gone silent past ``reap_timeout_ms``."""
        for sock, conn in list(self._conns.items()):
            idle_since = max(conn.last_seen_ms, conn.connected_at_ms)
            if now_ms - idle_since > self.reap_timeout_ms:
                self.log("reaping stale wearable connection")
                self._drop(sock)

    # ------------------------------------------------------------------ #
    # Outbound
    # ------------------------------------------------------------------ #
    def send_reset(self) -> None:
        """Broadcast a reset to every connected wearable (caregiver acked).

        Wire this alongside ``controller.acknowledge()`` in the app-integration
        glue so the wearable clears its local latch.
        """
        self._broadcast('{"version":1,"event":"reset"}')

    def is_online(self, now_ms: int) -> bool:
        """True if any wearable has been heard from within the heartbeat window."""
        return any(
            now_ms - c.last_seen_ms <= self.heartbeat_timeout_ms
            for c in self._conns.values()
        )

    # ------------------------------------------------------------------ #
    # Internals
    # ------------------------------------------------------------------ #
    def _accept(self, now_ms: int = 0) -> None:
        assert self._server is not None
        try:
            sock, addr = self._server.accept()
        except (BlockingIOError, OSError):
            return
        sock.setblocking(False)
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self._sel.register(sock, selectors.EVENT_READ, data="conn")
        conn = _Conn(sock)
        conn.connected_at_ms = now_ms  # start the reap grace clock at connect
        self._conns[sock] = conn
        self.log(f"wearable connected: {addr}")

    def _read(self, sock: socket.socket, now_ms: int, controller) -> None:
        conn = self._conns.get(sock)
        if conn is None:
            return
        try:
            chunk = sock.recv(_RECV_CHUNK)
        except BlockingIOError:
            return
        except OSError:
            self._drop(sock)
            return
        if not chunk:  # peer closed
            self._drop(sock)
            return

        conn.buf.extend(chunk)
        while b"\n" in conn.buf:
            raw, _, rest = conn.buf.partition(b"\n")
            conn.buf = bytearray(rest)
            if len(raw) > _MAX_LINE:
                continue  # oversized / garbage line -> drop, keep the stream
            line = raw.strip()
            if line:
                self._handle_line(bytes(line), conn, now_ms, controller)

        if len(conn.buf) > _MAX_LINE:  # no newline and already too long -> reset
            conn.buf = bytearray()

    def _handle_line(self, line: bytes, conn: _Conn, now_ms: int, controller) -> None:
        try:
            msg = json.loads(line)
        except (ValueError, UnicodeDecodeError):
            self.log("ignoring malformed line")
            return
        if not isinstance(msg, dict):
            return

        conn.last_seen_ms = now_ms
        event = msg.get("event")

        if event == "candidate_fall":
            self._handle_candidate(msg, conn, now_ms, controller)
        elif event == "boot":
            # Uptime/seq reset on the wearable -> clear dedup history for it.
            conn.seen.clear()
            conn.seen_order.clear()
            self.log("wearable boot")
        elif event == "heartbeat":
            pass  # liveness already updated via last_seen_ms
        else:
            self.log(f"ignoring unknown event: {event!r}")

    def _handle_candidate(self, msg: dict, conn: _Conn, now_ms: int, controller) -> None:
        seq = msg.get("seq")
        # Always ack a candidate (even a duplicate): a repeat means the wearable
        # never received the first ack, so re-acking lets it stop retransmitting.
        if isinstance(seq, int):
            self._send(conn.sock, f'{{"version":1,"event":"ack","seq":{seq}}}')

        if isinstance(seq, int) and conn.remember(seq):
            return  # duplicate: acked above, but do not re-ingest

        try:
            uptime_ms = int(msg["uptime_ms"])
            confidence = float(msg["confidence"])
        except (KeyError, TypeError, ValueError):
            self.log("candidate missing/invalid fields; dropping")
            return

        cf = CandidateFall(
            source=str(msg.get("source", "wearable")),
            uptime_ms=uptime_ms,
            confidence=confidence,
            received_at_ms=self.clock.now_ms(),  # hub stamps receive time
            version=int(msg.get("version", 1)),
        )
        self.log(f"candidate_fall seq={seq} conf={confidence:.2f} -> controller")
        controller.ingest_candidate(cf)

    def _broadcast(self, payload: str) -> None:
        for conn in list(self._conns.values()):
            self._send(conn.sock, payload)

    def _send(self, sock: socket.socket, payload: str) -> None:
        try:
            sock.sendall(payload.encode("ascii") + b"\n")
        except OSError:
            self._drop(sock)

    def _drop(self, sock: socket.socket) -> None:
        try:
            self._sel.unregister(sock)
        except KeyError:
            pass
        self._conns.pop(sock, None)
        try:
            sock.close()
        except OSError:
            pass
