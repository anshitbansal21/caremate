"""The four abstractions the main controller talks to.

The controller depends only on these — never on a concrete transport, camera,
serial port, or HTTP framework. That is what makes the fusion machine testable
with mocks and lets each teammate's real implementation plug in unchanged:

    WearableSource  ── Aryan's ESP32<->UNO Q message layer (candidate events)
    VisionSource    ── Aryan's YOLOv8 pose + NL/VLM Analyze-space layer
    AlertSink       ── the MCU firmware (buzzer / red LED / LCD) over serial
    AppBus          ── Anshit's API layer (status, alerts, analysis to the app)

``pump(now_ms, controller)`` is the cooperative-scheduling hook: on each tick a
source drains whatever it has and pushes it into the controller's ``ingest_*``
methods. Single-threaded and deterministic — no locks, mirrors the firmware loop.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from .events import AlertLevel, FusionState, SpaceAnalysis


class WearableSource(ABC):
    @abstractmethod
    def pump(self, now_ms: int, controller: "object") -> None:
        """Deliver any pending candidate events via ``controller.ingest_candidate``."""


class VisionSource(ABC):
    @abstractmethod
    def pump(self, now_ms: int, controller: "object") -> None:
        """Deliver the latest streamed evidence via ``controller.ingest_vision``."""

    @abstractmethod
    def analyze_space(self, request_id: str, now_ms: int) -> SpaceAnalysis:
        """Capture a fresh frame and return a validated SpaceAnalysis.

        Must not raise for a model timeout/refusal/occlusion — return a
        ``uncertain=True`` result instead, so fusion can decide, never suppress.
        """


class AlertSink(ABC):
    """Local alert output on the stationary hub, driven from Linux over serial.

    Kept deliberately narrow so the MCU stays a dumb, reliable actuator: the
    fusion decision lives on the Linux side, the MCU just reflects it.
    """

    @abstractmethod
    def set_status(self, state: FusionState, level: AlertLevel) -> None:
        """Drive buzzer + red LED to reflect the current alert level."""

    @abstractmethod
    def show(self, line1: str, line2: str = "") -> None:
        """Write the 16x2 LCD."""


class AppBus(ABC):
    """Outbound status/alerts/analysis to the app, and inbound app actions."""

    @abstractmethod
    def publish_status(self, state: FusionState, level: AlertLevel) -> None:
        ...

    @abstractmethod
    def publish_alert(self, state: FusionState, level: AlertLevel, detail: str) -> None:
        ...

    @abstractmethod
    def publish_analysis(self, analysis: SpaceAnalysis) -> None:
        ...

    @abstractmethod
    def pump(self, now_ms: int, controller: "object") -> None:
        """Deliver pending app actions (analyze / acknowledge / cancel)."""
