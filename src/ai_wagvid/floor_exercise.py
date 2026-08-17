"""Evidence-first floor-exercise analysis contracts.

This layer records floor/timing/sequence observations and candidate structure without calculating
D/E/final score. Audio may supply timing/synchronization only; music semantics are not represented.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from enum import StrEnum

from .domain import Apparatus


class FloorExerciseError(ValueError):
    pass


class FloorCapabilityState(StrEnum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"


class FloorIntervalKind(StrEnum):
    ROUTINE = "routine"
    TUMBLING_PASS = "tumbling-pass"
    ACRO_CANDIDATE = "acro-candidate"
    DANCE_CANDIDATE = "dance-candidate"
    TURN_CANDIDATE = "turn-candidate"
    CORNER_OR_PREPARATION = "corner-or-preparation"
    CHOREOGRAPHY = "choreography"
    LANDING = "landing"


class FloorObservationKind(StrEnum):
    ROTATION = "rotation"
    TWIST = "twist"
    BODY_SHAPE = "body-shape"
    LANDING_DISPLACEMENT = "landing-displacement"
    STEP_OR_FALL = "step-or-fall"
    BOUNDARY_CANDIDATE = "boundary-candidate"
    CONNECTION_TIMING = "connection-timing"
    ARTISTRY_CRITERION_EVIDENCE = "artistry-criterion-evidence"


class TimingSource(StrEnum):
    MEDIA_TIMELINE = "media-timeline"
    AUDIO_TIMELINE = "audio-timeline"
    COMBINED = "combined"


@dataclass(frozen=True)
class FloorEvidenceRef:
    evidence_id: str
    evidence_digest: str
    start_ms: int
    end_ms: int
    camera_id: str

    def __post_init__(self) -> None:
        if not self.evidence_id or not self.camera_id:
            raise FloorExerciseError("floor evidence identity/camera are required")
        _sha("evidence_digest", self.evidence_digest)
        _interval(self.start_ms, self.end_ms)

    @property
    def digest(self) -> str:
        return _digest(asdict(self))


@dataclass(frozen=True)
class FloorGeometryCapability:
    state: FloorCapabilityState
    floor_polygon_digest: str | None
    reason: str

    def __post_init__(self) -> None:
        if not self.reason:
            raise FloorExerciseError("floor geometry capability requires reason")
        if self.state is FloorCapabilityState.AVAILABLE:
            if self.floor_polygon_digest is None:
                raise FloorExerciseError("available floor geometry requires polygon digest")
            _sha("floor_polygon_digest", self.floor_polygon_digest)
        elif self.floor_polygon_digest is not None:
            _sha("floor_polygon_digest", self.floor_polygon_digest)


@dataclass(frozen=True)
class RoutineTiming:
    start_ms: int
    end_ms: int
    source: TimingSource
    timeline_digest: str
    confidence_milli: int
    evidence: tuple[FloorEvidenceRef, ...]
    limitations: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _interval(self.start_ms, self.end_ms)
        _sha("timeline_digest", self.timeline_digest)
        _milli("routine timing confidence", self.confidence_milli)
        if not self.evidence:
            raise FloorExerciseError("routine timing requires evidence")
        if len(self.limitations) != len(set(self.limitations)):
            raise FloorExerciseError("timing limitations must be unique")

    @property
    def duration_ms(self) -> int:
        return self.end_ms - self.start_ms

    @property
    def digest(self) -> str:
        return _digest({
            "start_ms": self.start_ms,
            "end_ms": self.end_ms,
            "source": self.source.value,
            "timeline_digest": self.timeline_digest,
            "confidence_milli": self.confidence_milli,
            "evidence_digests": [item.digest for item in self.evidence],
            "limitations": list(self.limitations),
        })


@dataclass(frozen=True)
class FloorInterval:
    interval_id: str
    kind: FloorIntervalKind
    start_ms: int
    end_ms: int
    confidence_milli: int
    evidence: tuple[FloorEvidenceRef, ...]
    temporal_candidate_digest: str | None = None
    family: str | None = None
    element_id: str | None = None
    accepted: bool = False
    limitations: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.interval_id:
            raise FloorExerciseError("floor interval_id is required")
        _interval(self.start_ms, self.end_ms)
        _milli("floor interval confidence", self.confidence_milli)
        if not self.evidence:
            raise FloorExerciseError("floor interval requires evidence")
        if self.temporal_candidate_digest is not None:
            _sha("temporal_candidate_digest", self.temporal_candidate_digest)
        candidate_kinds = {FloorIntervalKind.ACRO_CANDIDATE, FloorIntervalKind.DANCE_CANDIDATE, FloorIntervalKind.TURN_CANDIDATE}
        if self.kind in candidate_kinds and self.temporal_candidate_digest is None:
            raise FloorExerciseError("element candidate interval requires temporal candidate digest")
        if self.element_id is not None and not self.family:
            raise FloorExerciseError("exact floor element requires family")
        if not self.accepted and self.element_id is not None:
            raise FloorExerciseError("unaccepted floor candidate cannot claim exact element identity")
        if self.kind not in candidate_kinds and (self.family is not None or self.element_id is not None or self.accepted):
            raise FloorExerciseError("non-element floor interval cannot carry element identity")
        if len(self.limitations) != len(set(self.limitations)):
            raise FloorExerciseError("floor interval limitations must be unique")

    @property
    def digest(self) -> str:
        return _digest({
            "interval_id": self.interval_id,
            "kind": self.kind.value,
            "start_ms": self.start_ms,
            "end_ms": self.end_ms,
            "confidence_milli": self.confidence_milli,
            "evidence_digests": [item.digest for item in self.evidence],
            "temporal_candidate_digest": self.temporal_candidate_digest,
            "family": self.family,
            "element_id": self.element_id,
            "accepted": self.accepted,
            "limitations": list(self.limitations),
        })


@dataclass(frozen=True)
class FloorObservation:
    observation_id: str
    kind: FloorObservationKind
    start_ms: int
    end_ms: int
    value: str
    confidence_milli: int
    evidence: tuple[FloorEvidenceRef, ...]
    floor_polygon_digest: str | None = None
    criterion_id: str | None = None
    limitations: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.observation_id or not self.value:
            raise FloorExerciseError("floor observation identity/value are required")
        _interval(self.start_ms, self.end_ms)
        _milli("floor observation confidence", self.confidence_milli)
        if not self.evidence:
            raise FloorExerciseError("floor observation requires evidence")
        if self.floor_polygon_digest is not None:
            _sha("floor_polygon_digest", self.floor_polygon_digest)
        if self.kind is FloorObservationKind.BOUNDARY_CANDIDATE and self.floor_polygon_digest is None:
            raise FloorExerciseError("boundary candidate requires calibrated floor polygon")
        if self.kind is FloorObservationKind.ARTISTRY_CRITERION_EVIDENCE:
            if not self.criterion_id:
                raise FloorExerciseError("artistry evidence requires criterion_id")
        elif self.criterion_id is not None:
            raise FloorExerciseError("criterion_id is reserved for artistry criterion evidence")
        if len(self.limitations) != len(set(self.limitations)):
            raise FloorExerciseError("floor observation limitations must be unique")

    @property
    def digest(self) -> str:
        return _digest({
            "observation_id": self.observation_id,
            "kind": self.kind.value,
            "start_ms": self.start_ms,
            "end_ms": self.end_ms,
            "value": self.value,
            "confidence_milli": self.confidence_milli,
            "evidence_digests": [item.digest for item in self.evidence],
            "floor_polygon_digest": self.floor_polygon_digest,
            "criterion_id": self.criterion_id,
            "limitations": list(self.limitations),
        })


@dataclass(frozen=True)
class FloorConnectionCandidate:
    connection_id: str
    first_interval_id: str
    second_interval_id: str
    gap_ms: int
    evidence_observation_ids: tuple[str, ...]
    state: str
    confidence_milli: int

    def __post_init__(self) -> None:
        if not self.connection_id or not self.first_interval_id or not self.second_interval_id:
            raise FloorExerciseError("floor connection identity/intervals are required")
        if self.first_interval_id == self.second_interval_id:
            raise FloorExerciseError("floor connection requires distinct intervals")
        if isinstance(self.gap_ms, bool) or not isinstance(self.gap_ms, int) or self.gap_ms < 0:
            raise FloorExerciseError("floor connection gap_ms must be non-negative integer")
        if not self.evidence_observation_ids:
            raise FloorExerciseError("floor connection requires timing evidence observations")
        if self.state not in {"continuous", "interrupted", "unresolved"}:
            raise FloorExerciseError("invalid floor connection state")
        _milli("floor connection confidence", self.confidence_milli)


@dataclass(frozen=True)
class FloorExerciseBundle:
    analysis_id: str
    routine_id: str
    source_media_sha256: str
    timing: RoutineTiming
    geometry: FloorGeometryCapability
    intervals: tuple[FloorInterval, ...]
    observations: tuple[FloorObservation, ...]
    connections: tuple[FloorConnectionCandidate, ...]
    model_bundle_digest: str
    perception_bundle_digest: str
    created_at: datetime
    limitations: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.analysis_id or not self.routine_id:
            raise FloorExerciseError("floor analysis identity/routine are required")
        for label, value in (
            ("source_media_sha256", self.source_media_sha256),
            ("model_bundle_digest", self.model_bundle_digest),
            ("perception_bundle_digest", self.perception_bundle_digest),
        ):
            _sha(label, value)
        _aware("created_at", self.created_at)
        interval_ids = [item.interval_id for item in self.intervals]
        observation_ids = [item.observation_id for item in self.observations]
        connection_ids = [item.connection_id for item in self.connections]
        for label, values in (("interval", interval_ids), ("observation", observation_ids), ("connection", connection_ids)):
            if len(values) != len(set(values)):
                raise FloorExerciseError(f"floor {label} IDs must be unique")
        if any(item.start_ms < self.timing.start_ms or item.end_ms > self.timing.end_ms for item in self.intervals):
            raise FloorExerciseError("floor intervals must stay inside routine timing")
        if any(item.start_ms < self.timing.start_ms or item.end_ms > self.timing.end_ms for item in self.observations):
            raise FloorExerciseError("floor observations must stay inside routine timing")
        known_intervals = set(interval_ids)
        known_observations = set(observation_ids)
        for item in self.connections:
            if item.first_interval_id not in known_intervals or item.second_interval_id not in known_intervals:
                raise FloorExerciseError("floor connection references unknown interval")
            missing = set(item.evidence_observation_ids) - known_observations
            if missing:
                raise FloorExerciseError("floor connection references unknown observation: " + ",".join(sorted(missing)))
        boundary = [item for item in self.observations if item.kind is FloorObservationKind.BOUNDARY_CANDIDATE]
        if self.geometry.state is FloorCapabilityState.UNAVAILABLE and boundary:
            raise FloorExerciseError("unavailable floor geometry cannot emit boundary candidates")
        if self.geometry.state is FloorCapabilityState.AVAILABLE:
            if any(item.floor_polygon_digest is not None and item.floor_polygon_digest != self.geometry.floor_polygon_digest for item in self.observations):
                raise FloorExerciseError("floor observation polygon must match bundle geometry")
        if len(self.limitations) != len(set(self.limitations)):
            raise FloorExerciseError("floor bundle limitations must be unique")

    @property
    def apparatus(self) -> Apparatus:
        return Apparatus.FX

    @property
    def digest(self) -> str:
        return _digest({
            "analysis_id": self.analysis_id,
            "routine_id": self.routine_id,
            "apparatus": self.apparatus.value,
            "source_media_sha256": self.source_media_sha256,
            "timing_digest": self.timing.digest,
            "geometry": {"state": self.geometry.state.value, "floor_polygon_digest": self.geometry.floor_polygon_digest, "reason": self.geometry.reason},
            "interval_digests": [item.digest for item in self.intervals],
            "observation_digests": [item.digest for item in self.observations],
            "connections": [asdict(item) for item in self.connections],
            "model_bundle_digest": self.model_bundle_digest,
            "perception_bundle_digest": self.perception_bundle_digest,
            "created_at": self.created_at.astimezone(UTC).isoformat(),
            "limitations": list(self.limitations),
        })


def _interval(start_ms: int, end_ms: int) -> None:
    if isinstance(start_ms, bool) or not isinstance(start_ms, int) or start_ms < 0:
        raise FloorExerciseError("start_ms must be non-negative integer")
    if isinstance(end_ms, bool) or not isinstance(end_ms, int) or end_ms <= start_ms:
        raise FloorExerciseError("end_ms must be integer after start_ms")


def _milli(label: str, value: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 1000:
        raise FloorExerciseError(f"{label} must be integer [0, 1000]")


def _sha(label: str, value: str) -> None:
    if len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        raise FloorExerciseError(f"{label} must be lowercase SHA-256 hexadecimal")


def _aware(label: str, value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise FloorExerciseError(f"{label} must be timezone-aware")


def _digest(payload: object) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()
