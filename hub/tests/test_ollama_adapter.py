"""Tests for the local Ollama development adapter; no model/network required."""

from __future__ import annotations

import base64
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from caremate_hub.vision import OllamaVisionInference, VlmSpaceAnalyzer
from caremate_hub.vision.analyze import Snapshot


class _Response:
    def __init__(self, body):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self):
        return json.dumps(self.body).encode()


def test_ollama_request_contains_image_schema_and_safety_prompt():
    captured = {}

    def opener(request, timeout):
        captured["payload"] = json.loads(request.data)
        captured["timeout"] = timeout
        return _Response({"message": {"content": json.dumps({
            "person_state": "standing",
            "room_summary": "One person is standing in a room.",
            "risk_observations": [],
            "alert_recommendation": "none",
            "uncertain": False,
        })}})

    infer = OllamaVisionInference("chosen-model", timeout_s=4, opener=opener)
    result = infer(b"\xff\xd8test\xff\xd9")

    assert result["person_state"] == "standing"
    assert result["captured_at"].endswith("Z")
    assert captured["payload"]["model"] == "chosen-model"
    assert base64.b64decode(captured["payload"]["messages"][0]["images"][0]).startswith(b"\xff\xd8")
    assert "untrusted" in captured["payload"]["messages"][0]["content"]
    assert captured["payload"]["format"]["properties"]["person_state"]["enum"]
    assert captured["timeout"] == 4


def test_invalid_model_state_fails_closed():
    analyzer = VlmSpaceAnalyzer(lambda image: {
        "person_state": "dancing_on_ceiling",
        "room_summary": "unsupported state",
        "risk_observations": [],
        "alert_recommendation": "none",
        "uncertain": False,
    })
    result = analyzer.analyze(Snapshot(request_id="r1", evidence=None, image=b"image"))

    assert result.person_state == "uncertain"
    assert result.uncertain is True


def _run_all():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for test in tests:
        test()
        print(f"  ok  {test.__name__}")
    print(f"\n{len(tests)} passed")


if __name__ == "__main__":
    _run_all()
