"""Evidence-first vault phase and identity contracts.

This module is apparatus-specific but pre-scoring. It describes reviewed/measurable vault facts and
candidate identity references. FIG values and D-score arithmetic remain in the pinned rulepack and
#6 deterministic ledger.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from enum import StrEnum

from .domain import Apparatus


class VaultAnalysisError(ValueError):
    pass


class VaultPhase(StrEnum):
    APPROACH = "approach"
    HURDLE = "hurdle"
    SPRINGBOARD_CONTACT = "springboard-contact"
    PRE_FLIGHT = "pre-flight"
    TABLE_SUPPORT = "table-support"
    REPULSION = "repulsion"
    POST_FLIGHT = "post-flight"
    LANDING = "landing"
    STABILIZATION = "stabilization"


class VaultObservationKind(StrEnum):
    BOARD_CONTACT = "board-contact"
    TABLE_CONTACT = "table-contact"
    REPULSION = "repulsion"
    ROTATION = "rotation"
    TWIST = "twist"
    BODY_SHAPE = "body-shape"
    LANDING_CONTACT = "landing-contact"
    LANDING_DISPLACEMENT = "landing-displacement"
    FALL_OR_EXTRA_SUPPORT = "fall-or-extra-support"
    CORRIDOR_OR_BOUNDARY = "corridor-or-boundary"


class CapabilityState(StrEnum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class VaultEvidenceRef:
    evidence_id: str
    evidence_digest: str
    start_ms: int
    end_ms: int
    camera_id: str

    def __post_init__(self) -> None:
        if not self.evidence_id or not self.camera_id:
            raise VaultAnalysisError("vault evidence identity and camera are required")
        _sha("evidence_digest", self.evidence_digest)
        _interval(self.start_ms, self.end_ms)

    @property
    def digest(self) -> str:
        return _digest(asdict(self))


@dataclass(frozen=True)
class VaultPhaseInterval:
    phase: VaultPhase
    start_ms: int
    end_ms: int
    confidence_milli: int
    evidence: tuple[VaultEvidenceRef, ...]

    def __post_init__(self) -> None:
        _interval(self.start_ms, self.end_ms)
        _milli("phase confidence", self.confidence_milli)
        if not self.evidence:
            raise VaultAnalysisError("vault phase requires evidence")
        if any(ref.start_ms > self.start_ms or ref.end_ms < self.end_ms for ref in self.evidence):
            raise VaultAnalysisError("phase evidence must cover the phase interval")

    @property
    def digest(self) -> str:
        return _digest({
            "phase": self.phase.value,
            "start_ms": self.start_ms,
            "end_ms": self.end_ms,
            "confidence_milli": self.confidence_milli,
            "evidence_digests": [ref.digest for ref in self.evidence],
        })


@dataclass(frozen=True)
class VaultObservation:
    observation_id: str
    kind: VaultObservationKind
    phase: VaultPhase
    value: str
    confidence_milli: int
    evidence: tuple[VaultEvidenceRef, ...]
    calibration_digest: str | None = None
    limitations: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.observation_id or not self.value:
            raise VaultAnalysisError("vault observation identity/value are required")
        _milli("observation confidence", self.confidence_milli)
        if not self.evidence:
            raise VaultAnalysisError("vault observation requires evidence")
        if self.calibration_digest is not None:
            _sha("calibration_digest", self.calibration_digest)
        if len(self.limitations) != len(set(self.limitations)):
            raise VaultAnalysisError("observation limitations must be unique")
        if self.kind is VaultObservationKind.CORRIDOR_OR_BOUNDARY and self.calibration_digest is None:
            raise VaultAnalysisError("corridor/boundary observation requires calibration")

    @property
    def digest(self) -> str:
        return _digest({
            "observation_id": self.observation_id,
            "kind": self.kind.value,
            "phase": self.phase.value,
            "value": self.value,
            "confidence_milli": self.confidence_milli,
            "evidence_digests": [ref.digest for ref in self.evidence],
            "calibration_digest": self.calibration_digest,
            "limitations": list(self.limitations),
        })


@dataclass(frozen=True)
class VaultIdentityAlternative:
    element_id: str
    family: str
    probability_milli: int
    evidence_observation_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.element_id or not self.family:
            raise VaultAnalysisError("vault identity alternative ID/family are required")
        _milli("vault identity probability", self.probability_milli)
        if self.probability_milli == 0:
            raise VaultAnalysisError("ranked vault alternative must have positive probability")
        if len(self.evidence_observation_ids) != len(set(self.evidence_observation_ids)):
            raise VaultAnalysisError("vault identity evidence IDs must be unique")


@dataclass(frozen=True)
class VaultIdentityCandidates:
    alternatives: tuple[VaultIdentityAlternative, ...]
    unknown_ood_milli: int
    other_known_milli: int

    def __post_init__(self) -> None:
        _milli("vault unknown/OOD probability", self.unknown_ood_milli)
        _milli("vault other-known probability", self.other_known_milli)
        total = sum(item.probability_milli for item in self.alternatives) + self.unknown_ood_milli + self.other_known_milli
        if total != 1000:
            raise VaultAnalysisError(f"vault identity probability mass must total 1000, got {total}")
        ids = [item.element_id for item in self.alternatives]
        if len(ids) != len(set(ids)):
            raise VaultAnalysisError("vault identity alternatives must be unique")
        expected = tuple(sorted(self.alternatives, key=lambda item: (-item.probability_milli, item.element_id)))
        if expected != self.alternatives:
            raise VaultAnalysisError("vault identity alternatives must be deterministically ranked")


@dataclass(frozen=True)
class VaultGeometryCapability:
    state: CapabilityState
    calibration_digest: str | None
    reason: str

    def __post_init__(self) -> None:
        if not self.reason:
            raise VaultAnalysisError("vault geometry capability requires reason")
        if self.state is CapabilityState.AVAILABLE:
            if self.calibration_digest is None:
                raise VaultAnalysisError("available vault geometry requires calibration digest")
            _sha("calibration_digest", self.calibration_digest)
        elif self.calibration_digest is not None:
            _sha("calibration_digest", self.calibration_digest)


@dataclass(frozen=True)
class VaultAnalysisBundle:
    analysis_id: str
    routine_id: str
    source_media_sha256: str
    phases: tuple[VaultPhaseInterval, ...]
    observations: tuple[VaultObservation, ...]
    identity: VaultIdentityCandidates
    corridor_boundary_capability: VaultGeometryCapability
    model_bundle_digest: str
    perception_bundle_digest: str
    created_at: datetime
    limitations: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.analysis_id or not self.routine_id:
            raise VaultAnalysisError("vault analysis identity/routine are required")
        _sha("source_media_sha256", self.source_media_sha256)
        _sha("model_bundle_digest", self.model_bundle_digest)
        _sha("perception_bundle_digest", self.perception_bundle_digest)
        _aware("created_at", self.created_at)
        if not self.phases:
            raise VaultAnalysisError("vault analysis requires phase intervals")
        expected_order = tuple(sorted(self.phases, key=lambda item: (item.start_ms, item.end_ms, item.phase.value)))
        if expected_order != self.phases:
            raise VaultAnalysisError("vault phases must be chronological")
        seen_phases: set[VaultPhase] = set()
        previous_end = -1
        for phase in self.phases:
            if phase.phase in seen_phases:
                raise VaultAnalysisError("vault phase may occur only once in v1 canonical phase timeline")
            seen_phases.add(phase.phase)
            if phase.start_ms < previous_end:
                raise VaultAnalysisError("vault phases may not overlap")
            previous_end = phase.end_ms
        observation_ids = [item.observation_id for item in self.observations]
        if len(observation_ids) != len(set(observation_ids)):
            raise VaultAnalysisError("vault observation IDs must be unique")
        known = set(observation_ids)
        for alternative in self.identity.alternatives:
            missing = set(alternative.evidence_observation_ids) - known
            if missing:
                raise VaultAnalysisError("vault identity references unknown observations: " + ",".join(sorted(missing)))
        if self.corridor_boundary_capability.state is CapabilityState.UNAVAILABLE and any(
            item.kind is VaultObservationKind.CORRIDOR_OR_BOUNDARY
            for item in self.observations
        ):
            raise VaultAnalysisError(
                "unavailable corridor/boundary capability cannot emit boundary observations"
            )
        if len(self.limitations) != len(set(self.limitations)):
            raise VaultAnalysisError("vault analysis limitations must be unique")

    @property
    def apparatus(self) -> Apparatus:
        return Apparatus.VT

    @property
    def digest(self) -> str:
        return _digest({
            "analysis_id": self.analysis_id,
            "routine_id": self.routine_id,
            "apparatus": self.apparatus.value,
            "source_media_sha256": self.source_media_sha256,
            "phase_digests": [item.digest for item in self.phases],
            "observation_digests": [item.digest for item in self.observations],
            "identity": {
                "alternatives": [asdict(item) for item in self.identity.alternatives],
                "unknown_ood_milli": self.identity.unknown_ood_milli,
                "other_known_milli": self.identity.other_known_milli,
            },
            "corridor_boundary_capability": {
                "state": self.corridor_boundary_capability.state.value,
                "calibration_digest": self.corridor_boundary_capability.calibration_digest,
                "reason": self.corridor_boundary_capability.reason,
            },
            "model_bundle_digest": self.model_bundle_digest,
            "perception_bundle_digest": self.perception_bundle_digest,
            "created_at": self.created_at.astimezone(UTC).isoformat(),
            "limitations": list(self.limitations),
        })


def validate_required_phase_order(phases: tuple[VaultPhaseInterval, ...]) -> None:
    canonical = [
        VaultPhase.APPROACH,
        VaultPhase.HURDLE,
        VaultPhase.SPRINGBOARD_CONTACT,
        VaultPhase.PRE_FLIGHT,
        VaultPhase.TABLE_SUPPORT,
        VaultPhase.REPULSION,
        VaultPhase.POST_FLIGHT,
        VaultPhase.LANDING,
        VaultPhase.STABILIZATION,
    ]
    indexes = [canonical.index(item.phase) for item in phases]
    if indexes != sorted(indexes):
        raise VaultAnalysisError("vault phase semantic order is invalid")


def _interval(start_ms: int, end_ms: int) -> None:
    if isinstance(start_ms, bool) or not isinstance(start_ms, int) or start_ms < 0:
        raise VaultAnalysisError("start_ms must be a non-negative integer")
    if isinstance(end_ms, bool) or not isinstance(end_ms, int) or end_ms <= start_ms:
        raise VaultAnalysisError("end_ms must be an integer after start_ms")


def _milli(label: str, value: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 1000:
        raise VaultAnalysisError(f"{label} must be integer [0, 1000]")


def _sha(label: str, value: str) -> None:
    if len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        raise VaultAnalysisError(f"{label} must be lowercase SHA-256 hexadecimal")


def _aware(label: str, value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise VaultAnalysisError(f"{label} must be timezone-aware")


def _digest(payload: object) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()
