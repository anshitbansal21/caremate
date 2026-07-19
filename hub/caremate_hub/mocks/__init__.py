"""In-process fakes so the fusion machine runs end-to-end with no hardware.

Each fake stands in for one real teammate-owned implementation and prints what
the real one would actuate/publish, so the two demo-script scenarios can be
rehearsed on a laptop with no camera, wearable, MCU, or Wi-Fi.
"""

from .alert import MockAlertSink, SerialAlertSink
from .appbus import MockAppBus
from .vision import MockVision
from .wearable import MockWearable

__all__ = [
    "MockAlertSink",
    "SerialAlertSink",
    "MockAppBus",
    "MockVision",
    "MockWearable",
]
