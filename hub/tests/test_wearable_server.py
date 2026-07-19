"""Real-socket tests for the ESP32<->UNO Q message layer (WearableServer).

Opens an actual localhost TCP server, connects a fake wearable client, and
sends the exact newline-delimited JSON the firmware emits. Covers, per
AGENTS.md's fusion/transport verify guidance:
- candidate delivered as CandidateFall with a hub-stamped received_at_ms
- the hub acks a candidate
- duplicate seq (a retransmit) is re-acked but ingested only once
- a malformed line is ignored without breaking the stream
- boot clears the dedup history so post-reboot seqs are accepted
- reset is broadcast to the wearable
- liveness (is_online) reflects heartbeats
- end-to-end: a real candidate drives the MainController to AWAITING_VISION

Run: ``python hub/tests/test_wearable_server.py`` or via pytest.
"""

from __future__ import annotations

import json
import os
import socket
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from caremate_hub.clock import ManualClock
from caremate_hub.controller import MainController
from caremate_hub.events import FusionState
from caremate_hub.interfaces import AlertSink, AppBus, VisionSource
from caremate_hub.wearable_server import WearableServer


class RecordingController:
    """Minimal stand-in that just records what the server ingests."""

    def __init__(self):
        self.candidates = []

    def ingest_candidate(self, cf):
        self.candidates.append(cf)


def _connect(port):
    c = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    c.connect(("127.0.0.1", port))
    c.setblocking(False)
    return c


def _send(client, obj):
    client.sendall((json.dumps(obj) + "\n").encode())


def _pump_until(server, controller, clock, predicate, timeout_s=2.0):
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        server.pump(clock.now_ms(), controller)
        if predicate():
            return True
        time.sleep(0.005)
    server.pump(clock.now_ms(), controller)
    return predicate()


def _recv_lines(client, timeout_s=1.0):
    """Read whatever newline-delimited messages are available shortly."""
    client.settimeout(timeout_s)
    buf = b""
    try:
        while True:
            chunk = client.recv(512)
            if not chunk:
                break
            buf += chunk
            if buf.endswith(b"\n"):
                break
    except (socket.timeout, BlockingIOError):
        pass
    return [json.loads(l) for l in buf.split(b"\n") if l.strip()]


def _server(clock):
    s = WearableServer(clock, host="127.0.0.1", port=0, logger=lambda m: None)
    s.start()
    return s


def test_candidate_delivered_and_acked():
    clock = ManualClock(start_ms=10_000)
    server = _server(clock)
    ctrl = RecordingController()
    client = _connect(server.port)
    try:
        _send(client, {
            "version": 1, "event": "candidate_fall", "source": "wearable",
            "seq": 3, "uptime_ms": 5011, "confidence": 0.82,
        })
        assert _pump_until(server, ctrl, clock, lambda: len(ctrl.candidates) == 1)
        cf = ctrl.candidates[0]
        assert cf.source == "wearable"
        assert cf.uptime_ms == 5011
        assert abs(cf.confidence - 0.82) < 1e-6
        assert cf.received_at_ms == 10_000  # hub-stamped, not sent by wearable

        acks = [m for m in _recv_lines(client) if m.get("event") == "ack"]
        assert acks and acks[0]["seq"] == 3
    finally:
        client.close()
        server.close()


def test_duplicate_seq_reacked_but_ingested_once():
    clock = ManualClock(start_ms=1000)
    server = _server(clock)
    ctrl = RecordingController()
    client = _connect(server.port)
    try:
        msg = {"version": 1, "event": "candidate_fall", "source": "wearable",
               "seq": 7, "uptime_ms": 100, "confidence": 0.7}
        _send(client, msg)
        assert _pump_until(server, ctrl, clock, lambda: len(ctrl.candidates) == 1)
        _send(client, msg)  # retransmit of the same seq
        # Give it time; it must NOT ingest a second time.
        _pump_until(server, ctrl, clock, lambda: False, timeout_s=0.3)
        assert len(ctrl.candidates) == 1
        acks = [m for m in _recv_lines(client) if m.get("event") == "ack"]
        assert len([a for a in acks if a["seq"] == 7]) >= 2  # both were acked
    finally:
        client.close()
        server.close()


def test_malformed_line_ignored():
    clock = ManualClock()
    server = _server(clock)
    ctrl = RecordingController()
    client = _connect(server.port)
    try:
        client.sendall(b"{not json at all}\n")
        _pump_until(server, ctrl, clock, lambda: False, timeout_s=0.3)
        assert ctrl.candidates == []
        # stream still works after garbage
        _send(client, {"version": 1, "event": "candidate_fall", "source": "wearable",
                       "seq": 1, "uptime_ms": 1, "confidence": 0.9})
        assert _pump_until(server, ctrl, clock, lambda: len(ctrl.candidates) == 1)
    finally:
        client.close()
        server.close()


def test_boot_clears_dedup():
    clock = ManualClock()
    server = _server(clock)
    ctrl = RecordingController()
    client = _connect(server.port)
    try:
        first = {"version": 1, "event": "candidate_fall", "source": "wearable",
                 "seq": 1, "uptime_ms": 500, "confidence": 0.8}
        _send(client, first)
        assert _pump_until(server, ctrl, clock, lambda: len(ctrl.candidates) == 1)
        # Reboot: seq counter restarts at 1; boot must clear dedup so seq=1 is
        # accepted again rather than mistaken for a duplicate.
        _send(client, {"version": 1, "event": "boot", "source": "wearable",
                       "seq": 1, "uptime_ms": 0})
        _send(client, {"version": 1, "event": "candidate_fall", "source": "wearable",
                       "seq": 1, "uptime_ms": 20, "confidence": 0.8})
        assert _pump_until(server, ctrl, clock, lambda: len(ctrl.candidates) == 2)
    finally:
        client.close()
        server.close()


def test_reset_broadcast():
    clock = ManualClock()
    server = _server(clock)
    ctrl = RecordingController()
    client = _connect(server.port)
    try:
        # Ensure the connection is accepted first.
        _send(client, {"version": 1, "event": "heartbeat", "source": "wearable",
                       "seq": 1, "uptime_ms": 1})
        _pump_until(server, ctrl, clock, lambda: len(server._conns) == 1)
        server.send_reset()
        msgs = _recv_lines(client)
        assert any(m.get("event") == "reset" for m in msgs)
    finally:
        client.close()
        server.close()


def test_is_online_liveness():
    clock = ManualClock(start_ms=0)
    server = _server(clock)
    ctrl = RecordingController()
    client = _connect(server.port)
    try:
        _send(client, {"version": 1, "event": "heartbeat", "source": "wearable",
                       "seq": 1, "uptime_ms": 1})
        assert _pump_until(server, ctrl, clock, lambda: server.is_online(0))
        # Advance past the heartbeat timeout with no further messages.
        assert not server.is_online(999_999)
    finally:
        client.close()
        server.close()


# --- Recording sinks for the end-to-end controller test -------------------- #
class _Alert(AlertSink):
    def set_status(self, state, level): pass
    def show(self, line1, line2=""): pass


class _App(AppBus):
    def __init__(self): self.statuses = []
    def publish_status(self, state, level): self.statuses.append((state, level))
    def publish_alert(self, state, level, detail): pass
    def publish_analysis(self, analysis): pass
    def pump(self, now_ms, controller): pass


class _Vision(VisionSource):
    def pump(self, now_ms, controller): pass
    def analyze_space(self, request_id, now_ms): return None


def test_end_to_end_drives_controller_to_awaiting_vision():
    clock = ManualClock(start_ms=0)
    server = _server(clock)
    controller = MainController(_Alert(), _App(), _Vision(), clock,
                                logger=lambda m: None)
    client = _connect(server.port)
    try:
        _send(client, {"version": 1, "event": "candidate_fall", "source": "wearable",
                       "seq": 1, "uptime_ms": 800, "confidence": 0.9})
        assert _pump_until(
            server, controller, clock,
            lambda: controller.state is FusionState.AWAITING_VISION,
        )
    finally:
        client.close()
        server.close()


def _run_all():
    tests = [v for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"\n{len(tests)} passed")


if __name__ == "__main__":
    _run_all()
