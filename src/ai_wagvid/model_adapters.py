"""Framework adapters that convert third-party outputs to WAGVID contracts.

Imports of heavy ML frameworks deliberately happen only in factory methods. This
keeps the web/API process usable without GPU packages and makes adapters testable
with recorded or synthetic inference output.
"""

from __future__ import annotations

import importlib
import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from .actions import ActionSegment, SkillAlternative
from .domain import Apparatus, Provenance, TimeRange
from .perception import Keypoint, PerceptionBundle, PoseFrame, Visibility
from .quality import QualityAssessment


class AdapterUnavailable(RuntimeError):
    """Raised when an optional framework or configured artifact is unavailable."""


COCO_KEYPOINTS = (
    "nose", "left_eye", "right_eye", "left_ear", "right_ear",
    "left_shoulder", "right_shoulder", "left_elbow", "right_elbow",
    "left_wrist", "right_wrist", "left_hip", "right_hip", "left_knee",
    "right_knee", "left_ankle", "right_ankle",
)

MEDIAPIPE_KEYPOINTS = (
    "nose", "left_eye_inner", "left_eye", "left_eye_outer", "right_eye_inner",
    "right_eye", "right_eye_outer", "left_ear", "right_ear", "mouth_left",
    "mouth_right", "left_shoulder", "right_shoulder", "left_elbow",
    "right_elbow", "left_wrist", "right_wrist", "left_pinky", "right_pinky",
    "left_index", "right_index", "left_thumb", "right_thumb", "left_hip",
    "right_hip", "left_knee", "right_knee", "left_ankle", "right_ankle",
    "left_heel", "right_heel", "left_foot_index", "right_foot_index",
)


def _visibility(keypoints: Sequence[Keypoint], threshold: float) -> Visibility:
    if not keypoints:
        return Visibility.OUT_OF_FRAME
    visible = sum(point.confidence >= threshold for point in keypoints)
    return Visibility.VISIBLE if visible >= len(keypoints) * 0.6 else Visibility.OCCLUDED


@dataclass(frozen=True)
class MediaPipePoseAdapter:
    model_id: str = "mediapipe-pose-landmarker@1"
    confidence_threshold: float = 0.5

    @staticmethod
    def create_landmarker(model_path: str) -> Any:
        try:
            tasks = importlib.import_module("mediapipe.tasks.python")
            vision = importlib.import_module("mediapipe.tasks.python.vision")
        except ImportError as error:
            raise AdapterUnavailable("Install the 'mediapipe' optional dependency") from error
        options = vision.PoseLandmarkerOptions(
            base_options=tasks.BaseOptions(model_asset_path=model_path),
            running_mode=vision.RunningMode.VIDEO,
        )
        return vision.PoseLandmarker.create_from_options(options)

    def convert_result(
        self, result: Any, *, timestamp_s: float, camera_id: str
    ) -> PoseFrame:
        poses = getattr(result, "pose_landmarks", None) or []
        landmarks = poses[0] if poses else []
        points = tuple(
            Keypoint(
                name=MEDIAPIPE_KEYPOINTS[index],
                x=float(point.x), y=float(point.y), z=float(point.z),
                confidence=float(getattr(point, "visibility", 0.0)),
            )
            for index, point in enumerate(landmarks[: len(MEDIAPIPE_KEYPOINTS)])
        )
        return PoseFrame(timestamp_s, points, _visibility(points, self.confidence_threshold), camera_id)


@dataclass(frozen=True)
class CocoPoseAdapter:
    """Converter shared by YOLO-Pose and COCO-keypoint MMPose/RTMPose models."""

    model_id: str
    producer_version: str
    confidence_threshold: float = 0.5

    def convert(
        self,
        keypoints: Sequence[Sequence[float]],
        *,
        timestamp_s: float,
        camera_id: str,
        normalized: bool = True,
        image_size: tuple[int, int] | None = None,
    ) -> PoseFrame:
        if not normalized and not image_size:
            raise ValueError("image_size is required for pixel keypoints")
        width, height = image_size or (1, 1)
        points = tuple(
            Keypoint(
                name=name,
                x=float(values[0]) / width,
                y=float(values[1]) / height,
                confidence=float(values[2]),
            )
            for name, values in zip(COCO_KEYPOINTS, keypoints, strict=False)
            if len(values) >= 3
        )
        return PoseFrame(timestamp_s, points, _visibility(points, self.confidence_threshold), camera_id)

    def bundle(
        self, *, media_id: str, apparatus: Apparatus, interval: TimeRange,
        frames: Sequence[PoseFrame], config_digest: str | None = None,
    ) -> PerceptionBundle:
        return PerceptionBundle(
            media_id=media_id, apparatus=apparatus, interval=interval,
            pose_frames=tuple(frames),
            limitations=tuple(["No sufficiently visible pose"] if not any(
                frame.visibility is Visibility.VISIBLE for frame in frames
            ) else []),
            metadata={"provenance": Provenance(
                media_id, self.model_id, self.producer_version, config_digest
            )},
        )


@dataclass(frozen=True)
class LabelMapping:
    source_label: str
    canonical_label: str | None
    status: str


@dataclass(frozen=True)
class MMActionAdapter:
    model_id: str
    producer_version: str
    labels: Mapping[int, LabelMapping]
    unknown_threshold: float = 0.35
    top_k: int = 3

    def convert_scores(
        self, scores: Sequence[float], *, segment_id: str, interval: TimeRange,
        apparatus: Apparatus, source_id: str, config_digest: str | None = None,
    ) -> ActionSegment:
        ranked = sorted(enumerate(scores), key=lambda item: item[1], reverse=True)
        alternatives: list[SkillAlternative] = []
        rejected = 0.0
        for index, score in ranked:
            probability = float(score)
            mapping = self.labels.get(index)
            if not mapping or mapping.status != "mapped" or not mapping.canonical_label:
                rejected += probability
            elif len(alternatives) < self.top_k:
                alternatives.append(SkillAlternative(mapping.canonical_label, probability))
            else:
                rejected += probability
        best = alternatives[0].confidence if alternatives else 0.0
        unknown = max(rejected, 1.0 - sum(item.confidence for item in alternatives))
        if best < self.unknown_threshold:
            unknown = max(unknown, 1.0 - best)
        total = sum(item.confidence for item in alternatives) + unknown
        if total > 1.0:
            alternatives = [SkillAlternative(item.label_id, item.confidence / total) for item in alternatives]
            unknown /= total
        return ActionSegment(
            segment_id, interval, apparatus, tuple(alternatives), unknown,
            Provenance(source_id, self.model_id, self.producer_version, config_digest),
        )


@dataclass(frozen=True)
class LinearAQAAdapter:
    """Calibrates an injected raw AQA score; never writes the official score ledger."""

    model_id: str
    producer_version: str
    calibration_id: str
    raw_min: float
    raw_max: float
    scorer: Callable[[str, Apparatus], tuple[float, float | None]]

    def assess(self, *, media_id: str, apparatus: Apparatus) -> QualityAssessment:
        raw, confidence = self.scorer(media_id, apparatus)
        if not math.isfinite(raw) or self.raw_max <= self.raw_min:
            raise ValueError("invalid AQA value or calibration range")
        normalized = min(10.0, max(0.0, 10 * (raw - self.raw_min) / (self.raw_max - self.raw_min)))
        return QualityAssessment(
            self.model_id, apparatus, normalized, self.calibration_id, confidence,
            Provenance(media_id, self.model_id, self.producer_version),
            {"raw_score": raw, "raw_range": [self.raw_min, self.raw_max]},
        )
