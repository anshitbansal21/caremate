"""Scripted stand-in for the ESP32 candidate-event stream.

The real WearableSource is Aryan's ESP32<->UNO Q transport carrying the wearable
heuristic's ``candidate_fall`` events. This one replays a fixed schedule.
"""

from __future__ import annotations

from typing import List, Tuple

from ..events import CandidateFall
from ..interfaces import WearableSource


class MockWearable(WearableSource):
    def __init__(self, schedule: List[Tuple[int, float]]) -> None:
        # schedule: list of (emit_at_ms, confidence)
        self._events = sorted(schedule, key=lambda e: e[0])
        self._i = 0

    def pump(self, now_ms: int, controller) -> None:
        while self._i < len(self._events) and now_ms >= self._events[self._i][0]:
            at, conf = self._events[self._i]
            self._i += 1
            controller.ingest_candidate(
                CandidateFall(
                    source="wearable",
                    uptime_ms=at,
                    confidence=conf,
                    received_at_ms=now_ms,
                )
            )
