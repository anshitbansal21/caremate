"""On-device YOLOv8-pose via onnxruntime — lightweight, no torch/ultralytics.

The UNO Q can't fit the full ultralytics/torch stack (disk + CPU), so the
Analyze-space action runs a single-frame pose inference through ``onnxruntime``
with a pre-exported ``yolov8n-pose.onnx`` (~13 MB). Inference is **on demand
only** — triggered by ``/analyze``, never in the hub's hot loop — so a slow
per-frame CPU inference doesn't affect the feed or fusion loop.

``OnnxPoseModel.infer_jpeg`` decodes the raw YOLOv8-pose output (1×56×8400) into
COCO-17 :class:`Pose` objects the existing activity classifier consumes, so the
same ``classify_activity`` → :class:`SpaceAnalysis` path used everywhere else
produces the structured JSON the app receives.

Only the standard library plus numpy / onnxruntime / Pillow are imported here,
and this module is imported lazily (behind ``run_hub --analyze-onnx``) so the
rest of the package stays dependency-free.
"""

from __future__ import annotations

import dataclasses
import io
from typing import List, Optional

import numpy as np
import onnxruntime as ort
from PIL import Image

from ..clock import Clock
from ..events import Activity, SpaceAnalysis, VisionEvidence
from ..interfaces import VisionSource
from .activity import MotionTracker, classify_activity
from .analyze import LocalSummaryAnalyzer, Snapshot, SpaceAnalyzer
from .backends import Frame, Pose
from .config import VisionConfig

_INPUT = 640          # yolov8n-pose export input size
_NUM_KP = 17          # COCO-17
_UNAVAILABLE = (Activity.NOT_VISIBLE, Activity.UNCERTAIN)


class OnnxPoseModel:
    """Single-frame YOLOv8-pose runner over onnxruntime (CPU)."""

    def __init__(self, model_path: str, conf: float = 0.35, iou: float = 0.5) -> None:
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = 3  # leave a core for the hub/feed
        self.session = ort.InferenceSession(
            model_path, sess_options=opts, providers=["CPUExecutionProvider"]
        )
        self.input_name = self.session.get_inputs()[0].name
        self.conf = conf
        self.iou = iou

    def infer_jpeg(self, jpeg: bytes) -> Frame:
        img = Image.open(io.BytesIO(jpeg)).convert("RGB")
        arr = np.asarray(img)                       # H, W, 3 (RGB)
        blob, scale, pad_x, pad_y = self._letterbox(arr)
        out = self.session.run(None, {self.input_name: blob})[0]  # (1, 56, 8400)
        poses = self._decode(out, scale, pad_x, pad_y, arr.shape[1], arr.shape[0])
        return Frame(poses=poses, image=arr)

    def _letterbox(self, arr: np.ndarray):
        h, w = arr.shape[:2]
        scale = min(_INPUT / w, _INPUT / h)
        nw, nh = int(round(w * scale)), int(round(h * scale))
        resized = np.asarray(Image.fromarray(arr).resize((nw, nh)))
        canvas = np.full((_INPUT, _INPUT, 3), 114, dtype=np.uint8)
        pad_x, pad_y = (_INPUT - nw) // 2, (_INPUT - nh) // 2
        canvas[pad_y:pad_y + nh, pad_x:pad_x + nw] = resized
        blob = canvas.astype(np.float32) / 255.0
        blob = np.ascontiguousarray(blob.transpose(2, 0, 1)[None])  # 1,3,640,640
        return blob, scale, pad_x, pad_y

    def _decode(self, out, scale, pad_x, pad_y, w0, h0) -> List[Pose]:
        pred = out[0].transpose(1, 0)               # (8400, 56)
        scores = pred[:, 4]
        keep = scores > self.conf
        pred, scores = pred[keep], scores[keep]
        if pred.shape[0] == 0:
            return []
        cx, cy, bw, bh = pred[:, 0], pred[:, 1], pred[:, 2], pred[:, 3]
        x1, y1 = cx - bw / 2, cy - bh / 2
        x2, y2 = cx + bw / 2, cy + bh / 2
        boxes = np.stack([x1, y1, x2, y2], axis=1)
        idxs = self._nms(boxes, scores, self.iou)

        def to_orig(x, y):
            return (float((x - pad_x) / scale), float((y - pad_y) / scale))

        poses: List[Pose] = []
        for i in idxs:
            bx1, by1 = to_orig(x1[i], y1[i])
            bx2, by2 = to_orig(x2[i], y2[i])
            box = (max(0.0, bx1), max(0.0, by1), min(float(w0), bx2), min(float(h0), by2))
            kp_raw = pred[i, 5:5 + _NUM_KP * 3].reshape(_NUM_KP, 3)
            kps = []
            for kx, ky, kc in kp_raw:
                ox, oy = to_orig(kx, ky)
                kps.append((ox, oy, float(kc)))
            poses.append(Pose(keypoints=kps, box=box, score=float(scores[i])))
        return poses

    @staticmethod
    def _nms(boxes: np.ndarray, scores: np.ndarray, iou_thr: float) -> List[int]:
        x1, y1, x2, y2 = boxes[:, 0], boxes[:, 1], boxes[:, 2], boxes[:, 3]
        areas = (x2 - x1) * (y2 - y1)
        order = scores.argsort()[::-1]
        keep: List[int] = []
        while order.size > 0:
            i = int(order[0])
            keep.append(i)
            if order.size == 1:
                break
            xx1 = np.maximum(x1[i], x1[order[1:]])
            yy1 = np.maximum(y1[i], y1[order[1:]])
            xx2 = np.minimum(x2[i], x2[order[1:]])
            yy2 = np.minimum(y2[i], y2[order[1:]])
            w = np.maximum(0.0, xx2 - xx1)
            h = np.maximum(0.0, yy2 - yy1)
            inter = w * h
            ovr = inter / (areas[i] + areas[order[1:]] - inter + 1e-9)
            order = order[1:][ovr <= iou_thr]
        return keep

    def close(self) -> None:  # pragma: no cover
        pass


class OnDemandPoseVision(VisionSource):
    """VisionSource that runs YOLO pose ONLY on an Analyze-space request.

    ``pump()`` intentionally does nothing: continuous fall-confirm vision would peg
    a CPU core with per-tick inference, which the board can't spare, so that path
    stays a TODO (fusion reads vision as absent → a wearable candidate resolves to
    "uncertain — check user", never a silent all-clear). ``analyze_space`` grabs the
    latest camera frame, runs pose once, classifies the person's state, and returns
    the same validated :class:`SpaceAnalysis` the app already consumes.
    """

    def __init__(
        self,
        camera,                       # V4l2MjpegCamera (latest_jpeg())
        model: OnnxPoseModel,
        clock: Clock,
        config: Optional[VisionConfig] = None,
        analyzer: Optional[SpaceAnalyzer] = None,
    ) -> None:
        self.camera = camera
        self.model = model
        self.clock = clock
        self.cfg = config or VisionConfig()
        self.analyzer = analyzer or LocalSummaryAnalyzer()

    def pump(self, now_ms: int, controller) -> None:
        return  # no continuous inference on the board (see class docstring)

    def analyze_space(self, request_id: str, now_ms: int) -> SpaceAnalysis:
        jpeg = self.camera.latest_jpeg()
        if jpeg is None:
            return self._unavailable(request_id)
        try:
            frame = self.model.infer_jpeg(jpeg)
        except Exception:
            return self._unavailable(request_id)

        people_count = len(frame.poses)
        pose = self._primary(frame.poses)
        if pose is None:
            evidence = VisionEvidence(
                at_ms=now_ms, activity=Activity.NOT_VISIBLE,
                motion=False, confidence=0.0, available=False,
            )
            conf = 0.0
        else:
            activity, conf = classify_activity(pose, moving=False, cfg=self.cfg)
            evidence = VisionEvidence(
                at_ms=now_ms, activity=activity, motion=False, confidence=conf,
                available=activity not in _UNAVAILABLE,
            )
        snapshot = Snapshot(
            request_id=request_id, evidence=evidence,
            pose=pose, image=frame.image, now_ms=now_ms,
        )
        base = self.analyzer.analyze(snapshot)

        # Vision enrichment: real people count + a count-aware summary + the method.
        who = "person" if people_count == 1 else "people"
        if people_count == 0:
            summary = "No person is clearly visible in the current view."
        else:
            summary = (f"Detected {people_count} {who} in view. The tracked person "
                       f"appears {base.person_state}"
                       f"{'' if evidence.motion else ' and not moving'}.")
        return dataclasses.replace(
            base,
            room_summary=summary,
            people_count=people_count,
            activity_confidence=round(conf, 2),
            method="on-device YOLOv8n-pose keypoints + torso-tilt/leg-ratio activity rule",
        )

    @staticmethod
    def _primary(poses: List[Pose]) -> Optional[Pose]:
        if not poses:
            return None
        return max(poses, key=lambda p: (p.area(), p.score))

    @staticmethod
    def _unavailable(request_id: str) -> SpaceAnalysis:
        return SpaceAnalysis(
            request_id=request_id, captured_at="", person_state="not_visible",
            room_summary="No camera frame available to analyze.",
            risk_observations=[], alert_recommendation="check", uncertain=True,
        )
