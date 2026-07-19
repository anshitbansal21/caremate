"""Pose backends: the swappable "body" behind the vision brain.

``PoseBackend.read()`` returns the latest :class:`Frame` (detected poses + the
raw image) or ``None`` when no frame is available. Concrete backends:

- ``FakePoseBackend`` — replays scripted poses; drives the whole vision->fusion
  path in tests with no camera or model.
- ``YoloPoseBackend`` — real Ultralytics YOLOv8n-pose over a webcam. Imports
  ``ultralytics``/``cv2`` lazily so the rest of the package stays dependency-free.
  Untested without hardware; validate FPS on the UNO Q with the C270.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Callable, List, Optional, Sequence, Tuple

Keypoint = Tuple[float, float, float]  # (x, y, confidence)


@dataclass
class Pose:
    keypoints: List[Keypoint]                 # 17, COCO order
    box: Optional[Tuple[float, float, float, float]] = None  # x1,y1,x2,y2
    score: float = 1.0

    def area(self) -> float:
        if not self.box:
            return 0.0
        x1, y1, x2, y2 = self.box
        return abs((x2 - x1) * (y2 - y1))


@dataclass
class Frame:
    poses: List[Pose] = field(default_factory=list)
    image: object = None        # numpy array in the real backend, None in fakes
    at_ms: Optional[int] = None


class PoseBackend(ABC):
    @abstractmethod
    def read(self) -> Optional[Frame]:
        ...

    def close(self) -> None:  # pragma: no cover - default no-op
        pass


class FakePoseBackend(PoseBackend):
    """Test/demo backend. ``source`` is either a list of Frames/Poses consumed one
    per ``read()``, or a callable ``() -> Optional[Frame|Pose|list[Pose]]`` for
    generated sequences. A bare Pose (or list) is wrapped in a Frame.
    """

    def __init__(self, source) -> None:
        self._callable = callable(source)
        self._fn: Optional[Callable] = source if self._callable else None
        self._items = None if self._callable else list(source)
        self._i = 0

    def read(self) -> Optional[Frame]:
        item = self._fn() if self._callable else self._next_item()
        return _as_frame(item)

    def _next_item(self):
        if self._i >= len(self._items):
            return None
        item = self._items[self._i]
        self._i += 1
        return item


def _as_frame(item) -> Optional[Frame]:
    if item is None:
        return None
    if isinstance(item, Frame):
        return item
    if isinstance(item, Pose):
        return Frame(poses=[item])
    if isinstance(item, (list, tuple)):
        return Frame(poses=list(item))
    raise TypeError(f"cannot coerce {type(item)!r} to Frame")


class YoloPoseBackend(PoseBackend):  # pragma: no cover - needs hardware + deps
    """Real webcam + YOLOv8n-pose. Kept import-light; construct only on a machine
    with ``ultralytics``, ``opencv-python`` and a camera.

    On the UNO Q, prefer an int8 export via App Lab / Edge Impulse and a reduced
    ``imgsz`` (e.g. 416-480); this class is the develop-on-a-laptop reference.
    """

    def __init__(
        self,
        model_path: str = "yolov8n-pose.pt",
        camera: int = 0,
        imgsz: int = 480,
        conf: float = 0.5,
    ) -> None:
        import cv2  # noqa: WPS433 (lazy, optional dependency)
        from ultralytics import YOLO  # noqa: WPS433

        self._cv2 = cv2
        self._model = YOLO(model_path)
        self._imgsz = imgsz
        self._conf = conf
        self._cap = cv2.VideoCapture(camera)
        if not self._cap.isOpened():
            raise RuntimeError(f"could not open camera {camera}")

    def read(self) -> Optional[Frame]:
        ok, image = self._cap.read()
        if not ok:
            return None
        results = self._model.predict(
            image, imgsz=self._imgsz, conf=self._conf, verbose=False
        )
        poses: List[Pose] = []
        for r in results:
            if r.keypoints is None or r.boxes is None:
                continue
            kdata = r.keypoints.data  # (n, 17, 3)
            for i in range(len(kdata)):
                kpts = [(float(x), float(y), float(c)) for x, y, c in kdata[i].tolist()]
                box = tuple(float(v) for v in r.boxes.xyxy[i].tolist())
                score = float(r.boxes.conf[i]) if r.boxes.conf is not None else 1.0
                poses.append(Pose(keypoints=kpts, box=box, score=score))
        return Frame(poses=poses, image=image)

    def close(self) -> None:
        try:
            self._cap.release()
        except Exception:
            pass
