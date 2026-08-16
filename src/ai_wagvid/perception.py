"""Model-neutral contracts for measurable motion perception.

This layer may observe motion and geometry. It must not assign FIG elements or scores.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol

from .domain import Apparatus, Provenance, TimeRange


class Visibility(str, Enum):
    VISIBLE = "VISIBLE"
    OCCLUDED = "OCCLUDED"
    OUT_OF_FRAME = "OUT_OF_FRAME"
    UNKNOWN = "UNKNOWN"


class ContactState(str, Enum):
    CONTACT = "CONTACT"
    FLIGHT = "FLIGHT"
    POSSIBLE_CONTACT = "POSSIBLE_CONTACT"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class Keypoint:
    name: str
    x: float
    y: float
    confidence: float
    z: float | None = None

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("keypoint confidence must be between 0 and 1")


@dataclass(frozen=True)
class PoseFrame:
    timestamp_s: float
    keypoints: tuple[Keypoint, ...]
    visibility: Visibility
    camera_id: str

    def __post_init__(self) -> None:
        if self.timestamp_s < 0:
            raise ValueError("timestamp_s cannot be negative")


@dataclass(frozen=True)
class MotionObservation:
    observation_id: str
    kind: str
    interval: TimeRange
    confidence: float | None
    evidence_frame_ids: tuple[str, ...]
    measurements: dict[str, float | int | str | bool | None]
    provenance: Provenance

    def __post_init__(self) -> None:
        if self.confidence is not None and not 0.0 <= self.confidence <= 1.0:
            raise ValueError("observation confidence must be between 0 and 1")


@dataclass(frozen=True)
class PerceptionBundle:
    media_id: str
    apparatus: Apparatus
    interval: TimeRange
    pose_frames: tuple[PoseFrame, ...] = ()
    observations: tuple[MotionObservation, ...] = ()
    limitations: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def has_usable_evidence(self) -> bool:
        return bool(self.pose_frames or self.observations)


class MotionPerceptionModel(Protocol):
    """Replaceable adapter implemented by a versioned vision/temporal model bundle."""

    @property
    def model_id(self) -> str: ...

    def perceive(
        self,
        *,
        media_id: str,
        apparatus: Apparatus,
        interval: TimeRange,
        camera_ids: Sequence[str],
    ) -> PerceptionBundle: ...
