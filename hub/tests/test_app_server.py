"""Tests for the hub-side app server (HttpAppBus): auth, actions, analyze
correlation, and the SSE stream. Uses a real loopback server on an OS-chosen port.

Run: ``python hub/tests/test_app_server.py`` (or via pytest).
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from http.client import HTTPConnection

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from caremate_hub.app_server import HttpAppBus
from caremate_hub.clock import ManualClock
from caremate_hub.events import AlertLevel, FusionState, SpaceAnalysis

TOKEN = "test-token"


class FakeController:
    """Captures action calls; simulates request_analysis publishing a result."""

    def __init__(self, bus):
        self.bus = bus
        self.acks = 0
        self.cancels = 0

    def acknowledge(self):
        self.acks += 1

    def cancel(self):
        self.cancels += 1

    def request_analysis(self, request_id):
        self.bus.publish_analysis(SpaceAnalysis(
            request_id=request_id, captured_at="", person_state="on_bed",
            room_summary="clear", risk_observations=[],
            alert_recommendation="none", uncertain=False,
        ))


def _bus():
    bus = HttpAppBus(ManualClock(), host="127.0.0.1", port=0, token=TOKEN,
                     logger=lambda m: None)
    bus.start()
    return bus


def _conn(bus):
    return HTTPConnection("127.0.0.1", bus.port, timeout=3)


def _get(bus, path, token=TOKEN):
    c = _conn(bus)
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    c.request("GET", path, headers=headers)
    r = c.getresponse()
    body = r.read()
    c.close()
    return r.status, body


def _post(bus, path, token=TOKEN):
    c = _conn(bus)
    headers = {"Authorization": f"Bearer {token}", "Content-Length": "0"}
    c.request("POST", path, headers=headers)
    r = c.getresponse()
    body = r.read()
    c.close()
    return r.status, body


def test_auth_required():
    bus = _bus()
    try:
        status, _ = _get(bus, "/status", token=None)
        assert status == 401
        status, _ = _get(bus, "/status")
        assert status == 200
    finally:
        bus.close()


def test_status_reflects_publish():
    bus = _bus()
    try:
        bus.publish_status(FusionState.ALERTING, AlertLevel.CONFIRMED)
        status, body = _get(bus, "/status")
        assert status == 200
        data = json.loads(body)
        assert data["state"] == "alerting" and data["level"] == "confirmed"
    finally:
        bus.close()


def test_actions_enqueue_and_pump_applies():
    bus = _bus()
    ctrl = FakeController(bus)
    try:
        assert _post(bus, "/ack")[0] == 202
        assert _post(bus, "/cancel")[0] == 202
        bus.pump(0, ctrl)  # drain on the "fusion loop" thread
        assert ctrl.acks == 1 and ctrl.cancels == 1
    finally:
        bus.close()


def test_analyze_correlates_result():
    bus = _bus()
    ctrl = FakeController(bus)
    try:
        # A background pumper stands in for the fusion loop draining actions.
        stop = threading.Event()

        def pumper():
            while not stop.is_set():
                bus.pump(0, ctrl)
                time.sleep(0.005)

        t = threading.Thread(target=pumper, daemon=True)
        t.start()

        status, body = _post(bus, "/analyze")
        stop.set()
        t.join(timeout=1)

        assert status == 200
        data = json.loads(body)
        assert data["person_state"] == "on_bed"
        assert data["alert_recommendation"] == "none"
        assert data["request_id"].startswith("req-")
    finally:
        bus.close()


def test_sse_sends_snapshot_then_event():
    bus = _bus()
    try:
        bus.publish_status(FusionState.READY, AlertLevel.NONE)
        c = _conn(bus)
        c.request("GET", "/events", headers={"Authorization": f"Bearer {TOKEN}"})
        r = c.getresponse()
        assert r.status == 200
        assert "text/event-stream" in r.getheader("Content-Type", "")

        # First data line = current snapshot sent on connect.
        line = _read_data_line(r)
        assert json.loads(line)["type"] == "status"

        # A subsequently published alert must arrive on the same stream.
        bus.publish_alert(FusionState.ALERTING, AlertLevel.CONFIRMED, "test")
        line2 = _read_data_line(r)
        payload = json.loads(line2)
        assert payload["type"] == "alert" and payload["level"] == "confirmed"
        c.close()
    finally:
        bus.close()


def _read_data_line(resp, deadline_s=3.0):
    """Read until the next ``data: ...`` SSE line and return its JSON payload."""
    end = time.time() + deadline_s
    while time.time() < end:
        raw = resp.fp.readline()
        if not raw:
            break
        line = raw.decode().strip()
        if line.startswith("data:"):
            return line[len("data:"):].strip()
    raise AssertionError("no SSE data line received")


def _run_all():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"\n{len(tests)} passed")


if __name__ == "__main__":
    _run_all()
