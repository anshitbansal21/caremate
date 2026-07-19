"""Vision layer for the CareMate hub.

The brain (``activity``) and seam (``backends``, ``PoseVisionSource``) are pure
Python; the real YOLO backend and cv2 annotation are optional and imported lazily,
so importing this package never requires ultralytics/opencv.
"""

from .activity import MotionTracker, classify_activity
from .analyze import LocalSummaryAnalyzer, Snapshot, SpaceAnalyzer, VlmSpaceAnalyzer
from .backends import FakePoseBackend, Frame, Pose, PoseBackend
from .config import VisionConfig
from .pose_vision_source import PoseVisionSource

__all__ = [
    "MotionTracker",
    "classify_activity",
    "VisionConfig",
    "PoseBackend",
    "FakePoseBackend",
    "Frame",
    "Pose",
    "PoseVisionSource",
    "SpaceAnalyzer",
    "LocalSummaryAnalyzer",
    "VlmSpaceAnalyzer",
    "Snapshot",
]
