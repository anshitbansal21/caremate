"""Stand-in for Anshit's API layer / iOS app.

Prints outbound status/alerts/analysis, and replays scripted inbound app actions
(Analyze space, acknowledge, cancel/test) so a full round trip runs headless.
"""

from __future__ import annotations

from typing import List, Optional, Tuple

from ..events import AlertLevel, FusionState, SpaceAnalysis
from ..interfaces import AppBus

# (at_ms, action) where action is "analyze" | "ack" | "cancel"
Action = Tuple[int, str]


class MockAppBus(AppBus):
    def __init__(self, schedule: Optional[List[Action]] = None) -> None:
        self._schedule = sorted(schedule or [], key=lambda e: e[0])
        self._i = 0

    def publish_status(self, state: FusionState, level: AlertLevel) -> None:
        print(f"[app  ] status: {state.value} / {level.value}")

    def publish_alert(self, state: FusionState, level: AlertLevel, detail: str) -> None:
        print(f"[app  ] *** ALERT: {state.value} ({level.value}) -- {detail}")

    def publish_analysis(self, analysis: SpaceAnalysis) -> None:
        print(
            f"[app  ] analysis[{analysis.request_id}]: {analysis.person_state} -- "
            f"{analysis.room_summary} "
            f"(rec={analysis.alert_recommendation}, uncertain={analysis.uncertain})"
        )

    def pump(self, now_ms: int, controller) -> None:
        while self._i < len(self._schedule) and now_ms >= self._schedule[self._i][0]:
            _, action = self._schedule[self._i]
            self._i += 1
            if action == "analyze":
                controller.request_analysis()
            elif action == "ack":
                controller.acknowledge()
            elif action == "cancel":
                controller.cancel()
