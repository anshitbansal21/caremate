"""Injectable monotonic clock.

The controller never calls ``time`` directly so that tests can drive it with a
``ManualClock`` and the demo can run in accelerated simulated time. This mirrors
the non-blocking ``millis()`` timing used in the MCU firmware.
"""

from __future__ import annotations

import time


class Clock:
    def now_ms(self) -> int:  # pragma: no cover - interface
        raise NotImplementedError


class RealClock(Clock):
    """Wall-clock time from a monotonic source (immune to clock adjustments)."""

    def now_ms(self) -> int:
        return time.monotonic_ns() // 1_000_000


class ManualClock(Clock):
    """Deterministic clock for tests and simulated demo runs."""

    def __init__(self, start_ms: int = 0) -> None:
        self._t = start_ms

    def now_ms(self) -> int:
        return self._t

    def advance(self, ms: int) -> int:
        self._t += ms
        return self._t
