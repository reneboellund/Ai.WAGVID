"""Evidence-first balance-beam analysis contracts.

Observable beam alignment, balance correction, series continuity and criterion-level artistry markers
remain separate from deterministic scoring and human qualitative decisions.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from enum import StrEnum

from .domain import Apparatus


class BalanceBeamError(ValueError):
    pass


class BeamObservationKind(StrEnum):
    ALIGNMENT = "alignment"
    BALANCE_CORRECTION = "balance-correction"
    PAUSE_OR_HESITATION = "pause-or-hesitation"
    FOOT_HAND_RELATION = "foot-hand-relation"
    FALL_OR_OFF_BEAM = "fall-or-off-beam"
    REMOUNT = "remount"
    MOUNT = "mount"
    DISMOUNT = "dismount"
    ARTISTRY_CRITERION_EVIDENCE = "artistry-criterion-evidence"


class BeamCapabilityState(StrEnum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"


class SeriesState(StrEnum):
    CONTINUOUS = "continuous"
    INTERRUPTED = "interrupted"
    UNRESOLVED = "unresolved"


@dataclass(frozen=True)
class BeamEvidenceRef:
    evidence_id: str
    evidence_digest: str
    start_ms: int
    end_ms: int
    camera_id: str

    def __post_init__(self) -> None:
        if not self.evidence_id or not self.camera_id:
            raise BalanceBeamError("beam evidence identity/camera are required")
        _sha("evidence_digest", self.evidence_digest)
        _interval(self.start_ms, self.end_ms)

    @property
    def digest(self) -> str:
        return _digest(asdict(self))


@dataclass(frozen=True)
class BeamGeometryCapability:
    state: BeamCapabilityState
    geometry_digest: str | None
    reason: str

    def __post_init__(self) -> None:
        if not self.reason:
            raise BalanceBeamError("beam geometry capability requires reason")
        if self.state is BeamCapabilityState.AVAILABLE:
            if self.geometry_digest is None:
                raise BalanceBeamError("available beam geometry requires digest")
            _sha("geometry_digest", self.geometry_digest)
        elif self.geometry_digest is not None:
            _sha("geometry_digest", self.geometry_digest)


@dataclass(frozen=True)
class BeamObservation:
    observation_id: str
    kind: BeamObservationKind
    start_ms: int
    end_ms: int
    value: str
    confidence_milli: int
    evidence: tuple[BeamEvidenceRef, ...]
    geometry_digest: str | None = None
    criterion_id: str | None = None
    limitations: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.observation_id or not self.value:
            raise BalanceBeamError("beam observation identity/value are required")
        _interval(self.start_ms, self.end_ms)
        _milli("beam observation confidence", self.confidence_milli)
        if not self.evidence:
            raise BalanceBeamError("beam observation requires evidence")
        if any(ref.start_ms > self.start_ms or ref.end_ms < self.end_ms for ref in self.evidence):
            raise BalanceBeamError("beam observation evidence must cover interval")
        if self.geometry_digest is not None:
            _sha("geometry_digest", self.geometry_digest)
        if self.kind in {BeamObservationKind.ALIGNMENT, BeamObservationKind.FOOT_HAND_RELATION, BeamObservationKind.FALL_OR_OFF_BEAM} and self.geometry_digest is None:
            raise BalanceBeamError("geometry-dependent beam observation requires geometry")
        if self.kind is BeamObservationKind.ARTISTRY_CRITERION_EVIDENCE:
            if not self.criterion_id:
                raise BalanceBeamError("artistry evidence requires criterion_id")
        elif self.criterion_id is not None:
            raise BalanceBeamError("criterion_id is reserved for artistry criterion evidence")
        if len(self.limitations) != len(set(self.limitations)):
            raise BalanceBeamError("beam observation limitations must be unique")

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
            "geometry_digest": self.geometry_digest,
            "criterion_id": self.criterion_id,
            "limitations": list(self.limitations),
        })


@dataclass(frozen=True)
class BeamElementRef:
    segment_id: str
    temporal_candidate_digest: str
    start_ms: int
    end_ms: int
    family: str | None
    element_id: str | None
    accepted: bool

    def __post_init__(self) -> None:
        if not self.segment_id:
            raise BalanceBeamError("beam element segment_id is required")
        _sha("temporal_candidate_digest", self.temporal_candidate_digest)
        _interval(self.start_ms, self.end_ms)
        if self.element_id is not None and not self.family:
            raise BalanceBeamError("exact beam element requires family")
        if not self.accepted and self.element_id is not None:
            raise BalanceBeamError("unaccepted beam candidate cannot claim exact identity")


@dataclass(frozen=True)
class BeamSeriesCandidate:
    series_id: str
    segment_ids: tuple[str, ...]
    state: SeriesState
    gap_ms: tuple[int, ...]
    evidence_observation_ids: tuple[str, ...]
    confidence_milli: int

    def __post_init__(self) -> None:
        if not self.series_id or len(self.segment_ids) < 2:
            raise BalanceBeamError("beam series requires ID and at least two segments")
        if len(self.segment_ids) != len(set(self.segment_ids)):
            raise BalanceBeamError("beam series segments must be unique")
        if len(self.gap_ms) != len(self.segment_ids) - 1:
            raise BalanceBeamError("beam series gap count must be segment count minus one")
        if any(isinstance(value, bool) or not isinstance(value, int) or value < 0 for value in self.gap_ms):
            raise BalanceBeamError("beam series gaps must be non-negative integers")
        if not self.evidence_observation_ids:
            raise BalanceBeamError("beam series requires continuity evidence observations")
        _milli("beam series confidence", self.confidence_milli)


@dataclass(frozen=True)
class ArtistryCriterionDecision:
    decision_id: str
    criterion_id: str
    observation_digests: tuple[str, ...]
    reviewer_id: str
    reviewer_qualification_ref: str
    accepted: bool
    reason_code: str
    notes: str
    decided_at: datetime

    def __post_init__(self) -> None:
        if not self.decision_id or not self.criterion_id or not self.reviewer_id or not self.reviewer_qualification_ref:
            raise BalanceBeamError("artistry decision identity/criterion/reviewer/qualification are required")
        if not self.observation_digests:
            raise BalanceBeamError("artistry decision requires criterion evidence")
        for digest in self.observation_digests:
            _sha("artistry observation digest", digest)
        if not self.reason_code or not self.notes.strip():
            raise BalanceBeamError("artistry decision requires reason and notes")
        _aware("artistry decision time", self.decided_at)

    @property
    def digest(self) -> str:
        return _digest({
            **asdict(self),
            "decided_at": self.decided_at.astimezone(UTC).isoformat(),
        })


@dataclass(frozen=True)
class BalanceBeamBundle:
    analysis_id: str
    routine_id: str
    source_media_sha256: str
    geometry: BeamGeometryCapability
    observations: tuple[BeamObservation, ...]
    elements: tuple[BeamElementRef, ...]
    series: tuple[BeamSeriesCandidate, ...]
    artistry_decisions: tuple[ArtistryCriterionDecision, ...]
    model_bundle_digest: str
    perception_bundle_digest: str
    created_at: datetime
    limitations: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.analysis_id or not self.routine_id:
            raise BalanceBeamError("beam analysis identity/routine are required")
        for label, value in (
            ("source_media_sha256", self.source_media_sha256),
            ("model_bundle_digest", self.model_bundle_digest),
            ("perception_bundle_digest", self.perception_bundle_digest),
        ):
            _sha(label, value)
        _aware("created_at", self.created_at)
        observation_ids = [item.observation_id for item in self.observations]
        element_ids = [item.segment_id for item in self.elements]
        series_ids = [item.series_id for item in self.series]
        decision_ids = [item.decision_id for item in self.artistry_decisions]
        for label, values in (("observation", observation_ids), ("element", element_ids), ("series", series_ids), ("artistry decision", decision_ids)):
            if len(values) != len(set(values)):
                raise BalanceBeamError(f"beam {label} IDs must be unique")
        known_observations = {item.observation_id: item for item in self.observations}
        known_elements = set(element_ids)
        for item in self.series:
            missing_segments = set(item.segment_ids) - known_elements
            if missing_segments:
                raise BalanceBeamError("beam series references unknown elements: " + ",".join(sorted(missing_segments)))
            missing_observations = set(item.evidence_observation_ids) - set(known_observations)
            if missing_observations:
                raise BalanceBeamError("beam series references unknown observations: " + ",".join(sorted(missing_observations)))
        if self.geometry.state is BeamCapabilityState.UNAVAILABLE:
            if any(item.geometry_digest is not None for item in self.observations):
                raise BalanceBeamError("unavailable beam geometry cannot coexist with geometry-bound observations")
        elif any(item.geometry_digest is not None and item.geometry_digest != self.geometry.geometry_digest for item in self.observations):
            raise BalanceBeamError("beam observation geometry must match bundle geometry")
        artistry_by_digest = {item.digest: item for item in self.observations if item.kind is BeamObservationKind.ARTISTRY_CRITERION_EVIDENCE}
        for decision in self.artistry_decisions:
            missing = set(decision.observation_digests) - set(artistry_by_digest)
            if missing:
                raise BalanceBeamError("artistry decision references unknown/non-artistry evidence")
            if any(artistry_by_digest[digest].criterion_id != decision.criterion_id for digest in decision.observation_digests):
                raise BalanceBeamError("artistry decision evidence must match criterion_id")
        if len(self.limitations) != len(set(self.limitations)):
            raise BalanceBeamError("beam bundle limitations must be unique")

    @property
    def apparatus(self) -> Apparatus:
        return Apparatus.BB

    @property
    def digest(self) -> str:
        return _digest({
            "analysis_id": self.analysis_id,
            "routine_id": self.routine_id,
            "apparatus": self.apparatus.value,
            "source_media_sha256": self.source_media_sha256,
            "geometry": {"state": self.geometry.state.value, "geometry_digest": self.geometry.geometry_digest, "reason": self.geometry.reason},
            "observation_digests": [item.digest for item in self.observations],
            "elements": [asdict(item) for item in self.elements],
            "series": [{**asdict(item), "state": item.state.value} for item in self.series],
            "artistry_decision_digests": [item.digest for item in self.artistry_decisions],
            "model_bundle_digest": self.model_bundle_digest,
            "perception_bundle_digest": self.perception_bundle_digest,
            "created_at": self.created_at.astimezone(UTC).isoformat(),
            "limitations": list(self.limitations),
        })


def _interval(start_ms: int, end_ms: int) -> None:
    if isinstance(start_ms, bool) or not isinstance(start_ms, int) or start_ms < 0:
        raise BalanceBeamError("start_ms must be non-negative integer")
    if isinstance(end_ms, bool) or not isinstance(end_ms, int) or end_ms <= start_ms:
        raise BalanceBeamError("end_ms must be integer after start_ms")


def _milli(label: str, value: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 1000:
        raise BalanceBeamError(f"{label} must be integer [0, 1000]")


def _sha(label: str, value: str) -> None:
    if len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        raise BalanceBeamError(f"{label} must be lowercase SHA-256 hexadecimal")


def _aware(label: str, value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise BalanceBeamError(f"{label} must be timezone-aware")


def _digest(payload: object) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()
