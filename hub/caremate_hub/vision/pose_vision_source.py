"""PoseVisionSource — the real VisionSource, drop-in for run_live's stub.

Owns a pose backend + the activity classifier + a motion tracker, and turns each
frame into a :class:`VisionEvidence` for the fusion controller. Also serves the
Analyze-space action via a :class:`SpaceAnalyzer`.

Threading: heavy inference (tens of ms/frame) must not stall the hub's ~100 Hz
cooperative loop, so ``start()`` runs the capture+infer step on a worker thread
and ``pump()`` just forwards the latest evidence under a lock. Without
``start()`` the source runs synchronously inside ``pump()`` — convenient for
tests and for a laptop where the loop and inference rates are similar.

``at_ms`` is stamped when evidence is produced, never re-stamped on forward, so a
stalled camera lets the fusion staleness window read it as absent (not "no fall").
"""

from __future__ import annotations

import threading
from typing import List, Optional

from ..clock import Clock
from ..events import Activity, VisionEvidence
from ..interfaces import VisionSource
from .activity import MotionTracker, classify_activity
from .analyze import LocalSummaryAnalyzer, Snapshot, SpaceAnalyzer
from .backends import Frame, Pose, PoseBackend
from .config import VisionConfig

_UNAVAILABLE = (Activity.NOT_VISIBLE, Activity.UNCERTAIN)


class PoseVisionSource(VisionSource):
    def __init__(
        self,
        backend: PoseBackend,
        clock: Clock,
        config: Optional[VisionConfig] = None,
        analyzer: Optional[SpaceAnalyzer] = None,
    ) -> None:
        self.backend = backend
        self.clock = clock
        self.cfg = config or VisionConfig()
        self.analyzer = analyzer or LocalSummaryAnalyzer()
        self._motion = MotionTracker(self.cfg)

        self._lock = threading.Lock()
        self._latest: Optional[VisionEvidence] = None
        self._last_pose: Optional[Pose] = None
        self._last_image: object = None

        self._threaded = False
        self._stop: Optional[threading.Event] = None
        self._thread: Optional[threading.Thread] = None

    # ------------------------------------------------------------------ #
    # Lifecycle
    # ------------------------------------------------------------------ #
    def start(self) -> None:
        """Run capture+inference on a background thread (production mode)."""
        if self._threaded:
            return
        self._threaded = True
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def close(self) -> None:
        if self._stop is not None:
            self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)
        self.backend.close()

    def _run(self) -> None:
        assert self._stop is not None
        while not self._stop.is_set():
            self.process_once(self.clock.now_ms())

    # ------------------------------------------------------------------ #
    # VisionSource
    # ------------------------------------------------------------------ #
    def pump(self, now_ms: int, controller) -> None:
        if not self._threaded:
            self.process_once(now_ms)
        ev = self._get_latest()
        if ev is not None:
            controller.ingest_vision(ev)

    def analyze_space(self, request_id: str, now_ms: int):
        with self._lock:
            snapshot = Snapshot(
                request_id=request_id,
                evidence=self._latest,
                pose=self._last_pose,
                image=self._last_image,
                now_ms=now_ms,
            )
        return self.analyzer.analyze(snapshot)

    # ------------------------------------------------------------------ #
    # Core step
    # ------------------------------------------------------------------ #
    def process_once(self, now_ms: int) -> None:
        """Pull one frame, classify it, and update the latest evidence."""
        frame = self.backend.read()
        if frame is None:
            self._set(self._unavailable(now_ms), pose=None, image=None)
            return

        pose = self._primary(frame.poses)
        if pose is None:
            self._set(self._unavailable(now_ms), pose=None, image=frame.image)
            return

        metric = self._motion.update(pose, now_ms)
        activity, conf = classify_activity(pose, self._motion.is_walking(metric), self.cfg)
        ev = VisionEvidence(
            at_ms=now_ms,
            activity=activity,
            motion=self._motion.is_moving(metric),
            confidence=conf,
            available=activity not in _UNAVAILABLE,
        )
        self._set(ev, pose=pose, image=frame.image)

    @staticmethod
    def _unavailable(now_ms: int) -> VisionEvidence:
        return VisionEvidence(
            at_ms=now_ms,
            activity=Activity.NOT_VISIBLE,
            motion=False,
            confidence=0.0,
            available=False,
        )

    @staticmethod
    def _primary(poses: List[Pose]) -> Optional[Pose]:
        """Single-person MVP: track the largest / most-confident person."""
        if not poses:
            return None
        return max(poses, key=lambda p: (p.area(), p.score))

    def _set(self, ev: VisionEvidence, pose: Optional[Pose], image: object) -> None:
        with self._lock:
            self._latest = ev
            self._last_pose = pose
            self._last_image = image

    def _get_latest(self) -> Optional[VisionEvidence]:
        with self._lock:
            return self._latest
