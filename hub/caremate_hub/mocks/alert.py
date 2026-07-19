"""Local alert output fakes.

``MockAlertSink`` prints what the buzzer / red LED / LCD would do. ``SerialAlertSink``
formats the real line protocol to the MCU firmware but takes an injected writer,
so the scaffold stays dependency-free (wire pyserial in at deploy time).
"""

from __future__ import annotations

from typing import Callable

from ..events import AlertLevel, FusionState
from ..interfaces import AlertSink

_LEVEL_ICON = {
    AlertLevel.CONFIRMED: "RED-LED + BUZZER (siren)",
    AlertLevel.CHECK: "RED-LED slow blink (check)",
    AlertLevel.POSSIBLE: "amber standby",
    AlertLevel.NONE: "off",
}


class MockAlertSink(AlertSink):
    def set_status(self, state: FusionState, level: AlertLevel) -> None:
        print(f"[alert] {_LEVEL_ICON[level]:<28} (state={state.value})")

    def show(self, line1: str, line2: str = "") -> None:
        print(f"[lcd  ] |{line1[:16]:<16}|")
        print(f"[lcd  ] |{line2[:16]:<16}|")


class SerialAlertSink(AlertSink):
    """Drives ``firmware/caremate_controller`` over a newline-terminated protocol.

    ``writer`` is any ``Callable[[str], None]`` — e.g. wrap pyserial's
    ``Serial.write`` as ``lambda s: ser.write(s.encode())``.

    Protocol v1 (Linux -> MCU):
        STATUS <state> <level>\\n     # e.g. "STATUS alerting confirmed"
        LCD <line1>|<line2>\\n         # 16 chars each, '|' separates rows
    """

    def __init__(self, writer: Callable[[str], None]) -> None:
        self._w = writer

    def set_status(self, state: FusionState, level: AlertLevel) -> None:
        self._w(f"STATUS {state.value} {level.value}\n")

    def show(self, line1: str, line2: str = "") -> None:
        self._w(f"LCD {line1[:16]}|{line2[:16]}\n")
