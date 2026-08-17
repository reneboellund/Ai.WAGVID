"""Recoverable evidence references bound to immutable media and calibration.

The original EvidenceReference contract remains stable for existing persisted evidence.
CanonicalEvidenceReference is the forward-compatible v2 contract: exact timeline ticks,
multi-camera source intervals, explicit calibration/synchronization bindings, derived
visualizations that can never masquerade as source evidence, and append-only reviews.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from enum import StrEnum
from fractions import Fraction
from typing import Iterable

from .calibration import ApparatusCalibration
from .media_timeline import CanonicalTimeline, FrameTimestamp


class EvidenceMismatch(ValueError):
    pass


@dataclass(frozen=True)
class EvidenceReference:
    evidence_id: str
    source_sha256: str
    timeline_digest: str
    camera_id: str
    start_frame: int
    end_frame: int
    start_timestamp_s: float
    end_timestamp_s: float
    calibration_id: str | None
    calibration_digest: str | None
    producer: str
    producer_version: str

    def __post_init__(self) -> None:
        if not self.evidence_id or not self.camera_id or not self.producer or not self.producer_version:
            raise ValueError("evidence identity and producer are required")
        if self.start_frame < 0 or self.end_frame < self.start_frame:
            raise ValueError("evidence frame range is invalid")
        if self.start_timestamp_s < 0 or self.end_timestamp_s < self.start_timestamp_s:
            raise ValueError("evidence timestamp range is invalid")
        if bool(self.calibration_id) != bool(self.calibration_digest):
            raise ValueError("calibration identity and digest must appear together")

    @property
    def digest(self) -> str:
        encoded = json.dumps(asdict(self), sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class ResolvedEvidence:
    reference: EvidenceReference
    frames: tuple[FrameTimestamp, ...]


def create_evidence_reference(
    *, evidence_id: str, timeline: CanonicalTimeline, camera_id: str,
    start_timestamp_s: float, end_timestamp_s: float,
    producer: str, producer_version: str,
    calibration: ApparatusCalibration | None = None,
) -> EvidenceReference:
    if end_timestamp_s < start_timestamp_s:
        raise ValueError("evidence interval is invalid")
    start = timeline.frame_at_or_before(start_timestamp_s)
    end = timeline.frame_at_or_before(end_timestamp_s)
    if calibration and (
        calibration.camera_id != camera_id or calibration.source_sha256 != timeline.source_sha256
    ):
        raise EvidenceMismatch("calibration does not match evidence camera/source")
    return EvidenceReference(
        evidence_id, timeline.source_sha256, timeline.digest, camera_id,
        start.frame_index, end.frame_index, timeline.timestamp_s(start.frame_index),
        timeline.timestamp_s(end.frame_index),
        calibration.calibration_id if calibration else None,
        calibration.digest if calibration else None,
        producer, producer_version,
    )


def resolve_evidence(
    reference: EvidenceReference, *, timeline: CanonicalTimeline,
    calibration: ApparatusCalibration | None = None,
) -> ResolvedEvidence:
    if timeline.source_sha256 != reference.source_sha256 or timeline.digest != reference.timeline_digest:
        raise EvidenceMismatch("timeline/source does not match evidence reference")
    if reference.end_frame >= len(timeline.frames):
        raise EvidenceMismatch("evidence frame range is outside timeline")
    expected_start = timeline.timestamp_s(reference.start_frame)
    expected_end = timeline.timestamp_s(reference.end_frame)
    if expected_start != reference.start_timestamp_s or expected_end != reference.end_timestamp_s:
        raise EvidenceMismatch("canonical timestamps do not match referenced frames")
    if reference.calibration_id:
        if not calibration:
            raise EvidenceMismatch("referenced calibration is unavailable")
        if (
            calibration.calibration_id != reference.calibration_id
            or calibration.digest != reference.calibration_digest
        ):
            raise EvidenceMismatch("calibration revision does not match evidence reference")
    return ResolvedEvidence(
        reference, tuple(timeline.frames[reference.start_frame : reference.end_frame + 1])
    )


# ---------------------------------------------------------------------------
# Canonical evidence v2
# ---------------------------------------------------------------------------


class VisualizationKind(StrEnum):
    POSE_OVERLAY = "pose-overlay"
    GEOMETRY_OVERLAY = "geometry-overlay"
    TRACK_OVERLAY = "track-overlay"
    ANNOTATED_FRAME = "annotated-frame"
    INTERPOLATED_VIEW = "interpolated-view"
    PROXY_CLIP = "proxy-clip"


class EvidenceReviewDecision(StrEnum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    REVISED = "revised"
    ESCALATED = "escalated"
    UNRESOLVED = "unresolved"


@dataclass(frozen=True)
class EvidenceCalibrationBinding:
    intrinsic_id: str | None = None
    intrinsic_digest: str | None = None
    extrinsic_id: str | None = None
    extrinsic_digest: str | None = None
    apparatus_geometry_id: str | None = None
    apparatus_geometry_digest: str | None = None
    synchronization_digest: str | None = None

    def __post_init__(self) -> None:
        _validate_reference_pair("intrinsic calibration", self.intrinsic_id, self.intrinsic_digest)
        _validate_reference_pair("extrinsic calibration", self.extrinsic_id, self.extrinsic_digest)
        _validate_reference_pair(
            "apparatus geometry", self.apparatus_geometry_id, self.apparatus_geometry_digest
        )
        if self.synchronization_digest is not None:
            _validate_sha256("synchronization_digest", self.synchronization_digest)


@dataclass(frozen=True)
class CanonicalEvidenceInterval:
    source_media_sha256: str
    timeline_digest: str
    stream_index: int
    camera_id: str
    start_frame_index: int
    end_frame_index: int
    start_timestamp_ticks: int
    end_timestamp_ticks: int
    time_base_numerator: int
    time_base_denominator: int
    calibration: EvidenceCalibrationBinding = EvidenceCalibrationBinding()

    def __post_init__(self) -> None:
        _validate_sha256("source_media_sha256", self.source_media_sha256)
        _validate_sha256("timeline_digest", self.timeline_digest)
        if self.stream_index < 0 or not self.camera_id:
            raise ValueError("stream_index and camera_id are invalid")
        if self.start_frame_index < 0 or self.end_frame_index < self.start_frame_index:
            raise ValueError("canonical evidence frame interval is invalid")
        if self.end_timestamp_ticks < self.start_timestamp_ticks:
            raise ValueError("canonical evidence timestamp interval is invalid")
        if self.time_base_numerator <= 0 or self.time_base_denominator <= 0:
            raise ValueError("canonical evidence time base must be positive")

    @property
    def time_base(self) -> Fraction:
        return Fraction(self.time_base_numerator, self.time_base_denominator)

    @property
    def start_seconds(self) -> Fraction:
        return self.start_timestamp_ticks * self.time_base

    @property
    def end_seconds(self) -> Fraction:
        return self.end_timestamp_ticks * self.time_base

    @property
    def digest(self) -> str:
        return _stable_digest(asdict(self))


@dataclass(frozen=True)
class DerivedVisualization:
    visualization_id: str
    kind: VisualizationKind
    artifact_sha256: str
    generator_name: str
    generator_digest: str
    source_evidence_digest: str
    generated_at: datetime
    notes: str | None = None

    def __post_init__(self) -> None:
        if not self.visualization_id or not self.generator_name:
            raise ValueError("visualization identity and generator are required")
        _validate_sha256("artifact_sha256", self.artifact_sha256)
        _validate_sha256("generator_digest", self.generator_digest)
        _validate_sha256("source_evidence_digest", self.source_evidence_digest)
        if self.generated_at.tzinfo is None or self.generated_at.utcoffset() is None:
            raise ValueError("visualization generated_at must be timezone-aware")

    @property
    def is_original_evidence(self) -> bool:
        return False

    @property
    def digest(self) -> str:
        payload = asdict(self)
        payload["kind"] = self.kind.value
        payload["generated_at"] = self.generated_at.astimezone(UTC).isoformat()
        return _stable_digest(payload)


@dataclass(frozen=True)
class CanonicalEvidenceReference:
    evidence_id: str
    intervals: tuple[CanonicalEvidenceInterval, ...]
    created_at: datetime
    purpose: str
    producer: str
    producer_version: str
    derived_visualizations: tuple[DerivedVisualization, ...] = ()

    def __post_init__(self) -> None:
        if not self.evidence_id or not self.purpose.strip() or not self.producer or not self.producer_version:
            raise ValueError("canonical evidence identity, purpose and producer are required")
        if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
            raise ValueError("canonical evidence created_at must be timezone-aware")
        if not self.intervals:
            raise ValueError("canonical evidence requires at least one source interval")
        if len({item.digest for item in self.intervals}) != len(self.intervals):
            raise ValueError("canonical evidence contains a duplicate source interval")
        for visualization in self.derived_visualizations:
            if visualization.source_evidence_digest != self.source_digest:
                raise EvidenceMismatch("derived visualization belongs to different source evidence")

    @property
    def source_digest(self) -> str:
        return _stable_digest(
            {
                "schema": "canonical-evidence-v2",
                "evidence_id": self.evidence_id,
                "intervals": [item.digest for item in self.intervals],
                "purpose": self.purpose,
                "producer": self.producer,
                "producer_version": self.producer_version,
            }
        )

    @property
    def digest(self) -> str:
        return _stable_digest(
            {
                "source_digest": self.source_digest,
                "created_at": self.created_at.astimezone(UTC).isoformat(),
                "visualizations": [item.digest for item in self.derived_visualizations],
            }
        )


def canonical_interval_from_timeline(
    timeline: CanonicalTimeline,
    *,
    camera_id: str,
    start_frame_index: int,
    end_frame_index: int,
    calibration: EvidenceCalibrationBinding = EvidenceCalibrationBinding(),
) -> CanonicalEvidenceInterval:
    if start_frame_index < 0 or end_frame_index < start_frame_index:
        raise ValueError("requested canonical evidence frame interval is invalid")
    try:
        start = timeline.frames[start_frame_index]
        end = timeline.frames[end_frame_index]
    except IndexError as error:
        raise EvidenceMismatch("requested canonical evidence lies outside timeline") from error
    if start.frame_index != start_frame_index or end.frame_index != end_frame_index:
        raise EvidenceMismatch("canonical timeline frame indices are not contiguous")
    return CanonicalEvidenceInterval(
        source_media_sha256=timeline.source_sha256,
        timeline_digest=timeline.digest,
        stream_index=timeline.stream_index,
        camera_id=camera_id,
        start_frame_index=start_frame_index,
        end_frame_index=end_frame_index,
        start_timestamp_ticks=start.best_effort_timestamp,
        end_timestamp_ticks=end.best_effort_timestamp,
        time_base_numerator=timeline.time_base.numerator,
        time_base_denominator=timeline.time_base.denominator,
        calibration=calibration,
    )


def resolve_canonical_interval(
    interval: CanonicalEvidenceInterval,
    *,
    timeline: CanonicalTimeline,
) -> tuple[FrameTimestamp, ...]:
    if timeline.source_sha256 != interval.source_media_sha256 or timeline.digest != interval.timeline_digest:
        raise EvidenceMismatch("canonical timeline/source does not match evidence interval")
    if timeline.stream_index != interval.stream_index:
        raise EvidenceMismatch("canonical evidence references a different video stream")
    if timeline.time_base != interval.time_base:
        raise EvidenceMismatch("canonical evidence time base does not match timeline")
    if interval.end_frame_index >= len(timeline.frames):
        raise EvidenceMismatch("canonical evidence frame interval lies outside timeline")
    start = timeline.frames[interval.start_frame_index]
    end = timeline.frames[interval.end_frame_index]
    if (
        start.best_effort_timestamp != interval.start_timestamp_ticks
        or end.best_effort_timestamp != interval.end_timestamp_ticks
    ):
        raise EvidenceMismatch("canonical evidence ticks no longer match referenced frames")
    return tuple(timeline.frames[interval.start_frame_index : interval.end_frame_index + 1])


@dataclass(frozen=True)
class CanonicalEvidenceReview:
    review_id: str
    evidence_digest: str
    author_id: str
    decision: EvidenceReviewDecision
    reason: str
    created_at: datetime
    supersedes_review_id: str | None = None

    def __post_init__(self) -> None:
        if not self.review_id or not self.author_id or not self.reason.strip():
            raise ValueError("review identity, author and reason are required")
        _validate_sha256("evidence_digest", self.evidence_digest)
        if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
            raise ValueError("review created_at must be timezone-aware")

    @property
    def digest(self) -> str:
        payload = asdict(self)
        payload["decision"] = self.decision.value
        payload["created_at"] = self.created_at.astimezone(UTC).isoformat()
        return _stable_digest(payload)


class CanonicalEvidenceReviewLedger:
    """Append-only linear decision history; material review cannot be bulk-overwritten."""

    def __init__(self, reviews: Iterable[CanonicalEvidenceReview] = ()) -> None:
        self._reviews: dict[str, CanonicalEvidenceReview] = {}
        for review in reviews:
            self.append(review)

    def append(self, review: CanonicalEvidenceReview) -> None:
        existing = self._reviews.get(review.review_id)
        if existing is not None:
            if existing == review:
                return
            raise ValueError("review_id is immutable")
        same_evidence = [
            item for item in self._reviews.values() if item.evidence_digest == review.evidence_digest
        ]
        if review.supersedes_review_id is None:
            if same_evidence:
                raise ValueError("later review must explicitly supersede the prior decision")
        else:
            previous = self._reviews.get(review.supersedes_review_id)
            if previous is None:
                raise ValueError("superseded review does not exist")
            if previous.evidence_digest != review.evidence_digest:
                raise ValueError("review cannot supersede different evidence")
            if review.created_at <= previous.created_at:
                raise ValueError("superseding review must be created later")
            if any(item.supersedes_review_id == previous.review_id for item in same_evidence):
                raise ValueError("review history cannot fork")
        self._reviews[review.review_id] = review

    def history(self, evidence_digest: str) -> tuple[CanonicalEvidenceReview, ...]:
        _validate_sha256("evidence_digest", evidence_digest)
        return tuple(
            sorted(
                (item for item in self._reviews.values() if item.evidence_digest == evidence_digest),
                key=lambda item: (item.created_at, item.review_id),
            )
        )

    def current(self, evidence_digest: str) -> CanonicalEvidenceReview | None:
        values = self.history(evidence_digest)
        return values[-1] if values else None


def _validate_reference_pair(label: str, identifier: str | None, digest: str | None) -> None:
    if (identifier is None) != (digest is None):
        raise ValueError(f"{label} identity and digest must be supplied together")
    if digest is not None:
        _validate_sha256(f"{label} digest", digest)


def _validate_sha256(label: str, value: str) -> None:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError(f"{label} must be lowercase SHA-256 hexadecimal")


def _stable_digest(payload: dict) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(encoded).hexdigest()
