"""CareMate stationary vision-hub main controller (UNO Q Linux side).

Public surface: the fusion controller, its config, the event/value types, and the
four interfaces that concrete transports/cameras/serial/API layers implement.
"""

from .clock import Clock, ManualClock, RealClock
from .config import FusionConfig
from .controller import MainController
from .events import (
    Activity,
    AlertLevel,
    CandidateFall,
    FusionState,
    SpaceAnalysis,
    VisionEvidence,
)
from .fusion import VisionVerdict, classify_vision
from .interfaces import AlertSink, AppBus, VisionSource, WearableSource

__all__ = [
    "Clock",
    "ManualClock",
    "RealClock",
    "FusionConfig",
    "MainController",
    "Activity",
    "AlertLevel",
    "CandidateFall",
    "FusionState",
    "SpaceAnalysis",
    "VisionEvidence",
    "VisionVerdict",
    "classify_vision",
    "AlertSink",
    "AppBus",
    "VisionSource",
    "WearableSource",
]
