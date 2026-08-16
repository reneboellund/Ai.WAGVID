"""Recoverable evidence references bound to immutable media and calibration."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass

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
