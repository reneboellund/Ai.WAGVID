"""Deterministic release-validation governance for post-event Ai.WAGVID analysis.

Validation is slice-based and evidence-bound. A good aggregate metric cannot override a failed
required apparatus/camera/challenge slice. Safety/provenance blockers are non-waivable by design.
The current promotion model ends at validated production post-event analysis; there is no shadow,
live-assist or official-scoring gate in this module.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum

from .domain import Apparatus


class ValidationGovernanceError(ValueError):
    pass


class ValidationLayer(StrEnum):
    MEDIA_INTEGRITY = "media-integrity"
    PERCEPTION = "perception"
    SEGMENTATION = "segmentation"
    D_SCORE = "d-score"
    DEDUCTION = "deduction"
    SCORE_VERIFICATION = "score-verification"
    PERFORMANCE = "performance"
    REVIEW_WORKFLOW = "review-workflow"
    RUNTIME = "runtime"
    GOVERNANCE = "governance"


class PromotionGate(StrEnum):
    RESEARCH_FIXTURE = "research-fixture"
    OFFLINE_COMPONENT = "offline-component"
    INTEGRATED_POST_ROUTINE = "integrated-post-routine"
    QUALIFIED_USER_PILOT = "qualified-user-pilot"
    PRODUCTION_POST_EVENT = "production-post-event"


class MetricComparator(StrEnum):
    AT_LEAST = "at-least"
    AT_MOST = "at-most"


class DatasetRightsStatus(StrEnum):
    CLEARED = "cleared"
    SYNTHETIC = "synthetic"
    UNCLEARED = "uncleared"


class HardBlockerCode(StrEnum):
    DATASET_RIGHTS_UNCLEARED = "dataset-rights-uncleared"
    OFFICIAL_SCORE_LEAKAGE = "official-score-leakage"
    RULEPACK_PROVENANCE_INVALID = "rulepack-provenance-invalid"
    AUDIT_PROVENANCE_INVALID = "audit-provenance-invalid"
    SOURCE_MEDIA_INTEGRITY_INVALID = "source-media-integrity-invalid"


class PromotionStatus(StrEnum):
    PASSED = "passed"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class DatasetEvidence:
    dataset_id: str
    dataset_digest: str
    rights_status: DatasetRightsStatus
    split_manifest_digest: str
    rights_reference: str | None = None
    rights_digest: str | None = None

    def __post_init__(self) -> None:
        if not self.dataset_id:
            raise ValidationGovernanceError("dataset_id is required")
        _require_sha256("dataset_digest", self.dataset_digest)
        _require_sha256("split_manifest_digest", self.split_manifest_digest)
        if self.rights_status is DatasetRightsStatus.CLEARED and (
            not self.rights_reference or not self.rights_digest
        ):
            raise ValidationGovernanceError(
                "cleared dataset requires rights reference and immutable rights digest"
            )
        if self.rights_digest is not None:
            _require_sha256("rights_digest", self.rights_digest)
        if self.rights_status is DatasetRightsStatus.UNCLEARED and (
            self.rights_reference is not None or self.rights_digest is not None
        ):
            raise ValidationGovernanceError(
                "uncleared dataset cannot claim cleared rights metadata"
            )

    @property
    def digest(self) -> str:
        payload = asdict(self)
        payload["rights_status"] = self.rights_status.value
        return _stable_digest(payload)


@dataclass(frozen=True)
class BenchmarkSlice:
    dataset: DatasetEvidence
    sample_count: int
    apparatus: Apparatus | None = None
    camera_condition: str | None = None
    skill_family: str | None = None
    challenge_tags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if isinstance(self.sample_count, bool) or not isinstance(self.sample_count, int) or self.sample_count < 1:
            raise ValidationGovernanceError("benchmark sample_count must be a positive integer")
        for label, value in (
            ("camera_condition", self.camera_condition),
            ("skill_family", self.skill_family),
        ):
            if value is not None and not value:
                raise ValidationGovernanceError(f"{label} cannot be empty when present")
        if len(self.challenge_tags) != len(set(self.challenge_tags)):
            raise ValidationGovernanceError("challenge tags must be unique")
        if any(not item for item in self.challenge_tags):
            raise ValidationGovernanceError("challenge tags cannot be empty")

    @property
    def digest(self) -> str:
        return _stable_digest(
            {
                "dataset_digest": self.dataset.digest,
                "sample_count": self.sample_count,
                "apparatus": self.apparatus.value if self.apparatus else None,
                "camera_condition": self.camera_condition,
                "skill_family": self.skill_family,
                "challenge_tags": sorted(self.challenge_tags),
            }
        )


@dataclass(frozen=True)
class MetricResult:
    metric_id: str
    value: Decimal
    comparator: MetricComparator
    threshold: Decimal
    unit: str
    waivable: bool = True
    unavailable_count: int = 0
    unresolved_count: int = 0

    def __post_init__(self) -> None:
        if not self.metric_id or not self.unit:
            raise ValidationGovernanceError("metric_id and unit are required")
        _require_finite_decimal("metric value", self.value)
        _require_finite_decimal("metric threshold", self.threshold)
        for label, value in (
            ("unavailable_count", self.unavailable_count),
            ("unresolved_count", self.unresolved_count),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValidationGovernanceError(f"{label} must be a non-negative integer")

    @property
    def passed(self) -> bool:
        if self.comparator is MetricComparator.AT_LEAST:
            return self.value >= self.threshold
        return self.value <= self.threshold

    @property
    def digest(self) -> str:
        return _stable_digest(
            {
                "metric_id": self.metric_id,
                "value": _decimal_text(self.value),
                "comparator": self.comparator.value,
                "threshold": _decimal_text(self.threshold),
                "unit": self.unit,
                "waivable": self.waivable,
                "unavailable_count": self.unavailable_count,
                "unresolved_count": self.unresolved_count,
            }
        )


@dataclass(frozen=True)
class ValidationRun:
    run_id: str
    layer: ValidationLayer
    benchmark_slice: BenchmarkSlice
    release_digest: str
    model_bundle_digest: str
    rulepack_digest: str
    software_digest: str
    runtime_manifest_digest: str
    metrics: tuple[MetricResult, ...]
    started_at: datetime
    completed_at: datetime
    official_score_leakage_detected: bool = False
    rulepack_provenance_valid: bool = True
    audit_provenance_valid: bool = True
    source_media_integrity_valid: bool = True

    def __post_init__(self) -> None:
        if not self.run_id:
            raise ValidationGovernanceError("validation run_id is required")
        for label, value in (
            ("release_digest", self.release_digest),
            ("model_bundle_digest", self.model_bundle_digest),
            ("rulepack_digest", self.rulepack_digest),
            ("software_digest", self.software_digest),
            ("runtime_manifest_digest", self.runtime_manifest_digest),
        ):
            _require_sha256(label, value)
        if self.started_at.tzinfo is None or self.started_at.utcoffset() is None:
            raise ValidationGovernanceError("validation started_at must be timezone-aware")
        if self.completed_at.tzinfo is None or self.completed_at.utcoffset() is None:
            raise ValidationGovernanceError("validation completed_at must be timezone-aware")
        if self.completed_at <= self.started_at:
            raise ValidationGovernanceError("validation completed_at must be after started_at")
        metric_ids = [item.metric_id for item in self.metrics]
        if len(metric_ids) != len(set(metric_ids)):
            raise ValidationGovernanceError("validation metric IDs must be unique per run")

    @property
    def metric_map(self) -> Mapping[str, MetricResult]:
        return {item.metric_id: item for item in self.metrics}

    @property
    def hard_blockers(self) -> tuple[HardBlockerCode, ...]:
        blockers: list[HardBlockerCode] = []
        if self.benchmark_slice.dataset.rights_status is DatasetRightsStatus.UNCLEARED:
            blockers.append(HardBlockerCode.DATASET_RIGHTS_UNCLEARED)
        if self.official_score_leakage_detected:
            blockers.append(HardBlockerCode.OFFICIAL_SCORE_LEAKAGE)
        if not self.rulepack_provenance_valid:
            blockers.append(HardBlockerCode.RULEPACK_PROVENANCE_INVALID)
        if not self.audit_provenance_valid:
            blockers.append(HardBlockerCode.AUDIT_PROVENANCE_INVALID)
        if not self.source_media_integrity_valid:
            blockers.append(HardBlockerCode.SOURCE_MEDIA_INTEGRITY_INVALID)
        return tuple(blockers)

    @property
    def digest(self) -> str:
        return _stable_digest(
            {
                "run_id": self.run_id,
                "layer": self.layer.value,
                "slice_digest": self.benchmark_slice.digest,
                "release_digest": self.release_digest,
                "model_bundle_digest": self.model_bundle_digest,
                "rulepack_digest": self.rulepack_digest,
                "software_digest": self.software_digest,
                "runtime_manifest_digest": self.runtime_manifest_digest,
                "metric_digests": [item.digest for item in sorted(self.metrics, key=lambda value: value.metric_id)],
                "started_at": self.started_at.astimezone(UTC).isoformat(),
                "completed_at": self.completed_at.astimezone(UTC).isoformat(),
                "official_score_leakage_detected": self.official_score_leakage_detected,
                "rulepack_provenance_valid": self.rulepack_provenance_valid,
                "audit_provenance_valid": self.audit_provenance_valid,
                "source_media_integrity_valid": self.source_media_integrity_valid,
            }
        )


@dataclass(frozen=True)
class ValidationRequirement:
    requirement_id: str
    layer: ValidationLayer
    metric_ids: tuple[str, ...]
    minimum_sample_count: int
    apparatus: Apparatus | None = None
    camera_condition: str | None = None
    skill_family: str | None = None
    required_challenge_tags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.requirement_id or not self.metric_ids:
            raise ValidationGovernanceError("validation requirement ID and metrics are required")
        if len(self.metric_ids) != len(set(self.metric_ids)):
            raise ValidationGovernanceError("required metric IDs must be unique")
        if isinstance(self.minimum_sample_count, bool) or not isinstance(self.minimum_sample_count, int) or self.minimum_sample_count < 1:
            raise ValidationGovernanceError("minimum_sample_count must be a positive integer")
        if len(self.required_challenge_tags) != len(set(self.required_challenge_tags)):
            raise ValidationGovernanceError("required challenge tags must be unique")

    def matches(self, run: ValidationRun) -> bool:
        slice_ = run.benchmark_slice
        if run.layer is not self.layer:
            return False
        if self.apparatus is not None and slice_.apparatus is not self.apparatus:
            return False
        if self.camera_condition is not None and slice_.camera_condition != self.camera_condition:
            return False
        if self.skill_family is not None and slice_.skill_family != self.skill_family:
            return False
        return set(self.required_challenge_tags).issubset(slice_.challenge_tags)


@dataclass(frozen=True)
class PromotionPolicy:
    policy_id: str
    gate: PromotionGate
    requirements: tuple[ValidationRequirement, ...]

    def __post_init__(self) -> None:
        if not self.policy_id or not self.requirements:
            raise ValidationGovernanceError("promotion policy ID and requirements are required")
        requirement_ids = [item.requirement_id for item in self.requirements]
        if len(requirement_ids) != len(set(requirement_ids)):
            raise ValidationGovernanceError("promotion requirement IDs must be unique")

    @property
    def digest(self) -> str:
        return _stable_digest(
            {
                "policy_id": self.policy_id,
                "gate": self.gate.value,
                "requirements": [
                    {
                        "requirement_id": item.requirement_id,
                        "layer": item.layer.value,
                        "metric_ids": list(item.metric_ids),
                        "minimum_sample_count": item.minimum_sample_count,
                        "apparatus": item.apparatus.value if item.apparatus else None,
                        "camera_condition": item.camera_condition,
                        "skill_family": item.skill_family,
                        "required_challenge_tags": list(item.required_challenge_tags),
                    }
                    for item in sorted(self.requirements, key=lambda value: value.requirement_id)
                ],
            }
        )


@dataclass(frozen=True)
class RegressionWaiver:
    waiver_id: str
    run_id: str
    metric_id: str
    approver_id: str
    reason: str
    approved_at: datetime
    expires_at: datetime

    def __post_init__(self) -> None:
        if not self.waiver_id or not self.run_id or not self.metric_id or not self.approver_id or not self.reason.strip():
            raise ValidationGovernanceError("waiver identity/run/metric/approver/reason are required")
        if self.approved_at.tzinfo is None or self.approved_at.utcoffset() is None:
            raise ValidationGovernanceError("waiver approved_at must be timezone-aware")
        if self.expires_at.tzinfo is None or self.expires_at.utcoffset() is None:
            raise ValidationGovernanceError("waiver expires_at must be timezone-aware")
        if self.expires_at <= self.approved_at:
            raise ValidationGovernanceError("waiver expiry must be after approval")

    def active_at(self, now: datetime) -> bool:
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValidationGovernanceError("waiver evaluation time must be timezone-aware")
        return self.approved_at <= now < self.expires_at

    @property
    def digest(self) -> str:
        payload = asdict(self)
        payload["approved_at"] = self.approved_at.astimezone(UTC).isoformat()
        payload["expires_at"] = self.expires_at.astimezone(UTC).isoformat()
        return _stable_digest(payload)


@dataclass(frozen=True)
class RequirementEvidence:
    requirement_id: str
    selected_run_digest: str | None
    waived_metric_ids: tuple[str, ...]
    blockers: tuple[str, ...]

    @property
    def satisfied(self) -> bool:
        return self.selected_run_digest is not None and not self.blockers


@dataclass(frozen=True)
class ValidatedScope:
    requirement_id: str
    layer: ValidationLayer
    run_digest: str
    apparatus: Apparatus | None
    camera_condition: str | None
    skill_family: str | None
    challenge_tags: tuple[str, ...]
    dataset_digest: str
    sample_count: int


@dataclass(frozen=True)
class PromotionDecision:
    policy_id: str
    policy_digest: str
    gate: PromotionGate
    release_digest: str
    evaluated_at: datetime
    status: PromotionStatus
    requirements: tuple[RequirementEvidence, ...]
    validated_scopes: tuple[ValidatedScope, ...]
    active_waiver_digests: tuple[str, ...]
    blockers: tuple[str, ...]

    @property
    def digest(self) -> str:
        return _stable_digest(
            {
                "policy_id": self.policy_id,
                "policy_digest": self.policy_digest,
                "gate": self.gate.value,
                "release_digest": self.release_digest,
                "evaluated_at": self.evaluated_at.astimezone(UTC).isoformat(),
                "status": self.status.value,
                "requirements": [asdict(item) for item in self.requirements],
                "validated_scopes": [
                    {
                        **asdict(item),
                        "layer": item.layer.value,
                        "apparatus": item.apparatus.value if item.apparatus else None,
                    }
                    for item in self.validated_scopes
                ],
                "active_waiver_digests": list(self.active_waiver_digests),
                "blockers": list(self.blockers),
            }
        )


@dataclass(frozen=True)
class ReleaseValidationManifest:
    manifest_id: str
    release_digest: str
    model_bundle_digest: str
    rulepack_digest: str
    software_digest: str
    promotion: PromotionDecision
    known_limitations: tuple[str, ...]
    created_at: datetime

    def __post_init__(self) -> None:
        if not self.manifest_id:
            raise ValidationGovernanceError("validation manifest_id is required")
        for label, value in (
            ("release_digest", self.release_digest),
            ("model_bundle_digest", self.model_bundle_digest),
            ("rulepack_digest", self.rulepack_digest),
            ("software_digest", self.software_digest),
        ):
            _require_sha256(label, value)
        if self.promotion.release_digest != self.release_digest:
            raise ValidationGovernanceError("promotion decision belongs to a different release")
        if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
            raise ValidationGovernanceError("validation manifest created_at must be timezone-aware")
        if len(self.known_limitations) != len(set(self.known_limitations)):
            raise ValidationGovernanceError("known limitations must be unique")

    def normalized_dict(self) -> dict:
        return {
            "schema": "ai.wagvid.release-validation.v1",
            "manifest_id": self.manifest_id,
            "release_digest": self.release_digest,
            "model_bundle_digest": self.model_bundle_digest,
            "rulepack_digest": self.rulepack_digest,
            "software_digest": self.software_digest,
            "promotion": {
                "decision_digest": self.promotion.digest,
                "policy_id": self.promotion.policy_id,
                "policy_digest": self.promotion.policy_digest,
                "gate": self.promotion.gate.value,
                "status": self.promotion.status.value,
                "validated_scopes": [
                    {
                        "requirement_id": item.requirement_id,
                        "layer": item.layer.value,
                        "run_digest": item.run_digest,
                        "apparatus": item.apparatus.value if item.apparatus else None,
                        "camera_condition": item.camera_condition,
                        "skill_family": item.skill_family,
                        "challenge_tags": list(item.challenge_tags),
                        "dataset_digest": item.dataset_digest,
                        "sample_count": item.sample_count,
                    }
                    for item in self.promotion.validated_scopes
                ],
                "active_waiver_digests": list(self.promotion.active_waiver_digests),
                "blockers": list(self.promotion.blockers),
            },
            "known_limitations": list(self.known_limitations),
            "created_at": self.created_at.astimezone(UTC).isoformat(),
        }

    def normalized_json(self) -> str:
        return json.dumps(self.normalized_dict(), sort_keys=True, separators=(",", ":"))

    @property
    def digest(self) -> str:
        return hashlib.sha256(self.normalized_json().encode()).hexdigest()


def evaluate_promotion(
    policy: PromotionPolicy,
    runs: Iterable[ValidationRun],
    *,
    release_digest: str,
    evaluated_at: datetime,
    waivers: Iterable[RegressionWaiver] = (),
) -> PromotionDecision:
    _require_sha256("release_digest", release_digest)
    if evaluated_at.tzinfo is None or evaluated_at.utcoffset() is None:
        raise ValidationGovernanceError("promotion evaluated_at must be timezone-aware")
    run_items = tuple(run for run in runs if run.release_digest == release_digest)
    waiver_items = tuple(waivers)
    waiver_ids = [item.waiver_id for item in waiver_items]
    if len(waiver_ids) != len(set(waiver_ids)):
        raise ValidationGovernanceError("waiver IDs must be unique")
    active_waiver_map = {
        (item.run_id, item.metric_id): item
        for item in waiver_items
        if item.active_at(evaluated_at)
    }
    if len(active_waiver_map) != sum(1 for item in waiver_items if item.active_at(evaluated_at)):
        raise ValidationGovernanceError("multiple active waivers target the same run metric")

    evidence: list[RequirementEvidence] = []
    scopes: list[ValidatedScope] = []
    used_waivers: dict[str, RegressionWaiver] = {}
    global_blockers: list[str] = []

    for requirement in sorted(policy.requirements, key=lambda item: item.requirement_id):
        candidates = tuple(run for run in run_items if requirement.matches(run))
        accepted_candidates: list[tuple[ValidationRun, tuple[str, ...], tuple[RegressionWaiver, ...]]] = []
        candidate_reasons: list[str] = []
        if not candidates:
            candidate_reasons.append("no-matching-validation-run")
        for run in candidates:
            reasons: list[str] = []
            run_waivers: list[RegressionWaiver] = []
            if run.benchmark_slice.sample_count < requirement.minimum_sample_count:
                reasons.append(
                    f"sample-count:{run.benchmark_slice.sample_count}<{requirement.minimum_sample_count}"
                )
            for blocker in run.hard_blockers:
                reasons.append(f"hard-blocker:{blocker.value}")
            for metric_id in requirement.metric_ids:
                metric = run.metric_map.get(metric_id)
                if metric is None:
                    reasons.append(f"missing-metric:{metric_id}")
                    continue
                if metric.passed:
                    continue
                waiver = active_waiver_map.get((run.run_id, metric_id))
                if waiver is None:
                    reasons.append(f"metric-failed:{metric_id}")
                elif not metric.waivable:
                    reasons.append(f"metric-non-waivable:{metric_id}")
                else:
                    run_waivers.append(waiver)
            if not reasons:
                accepted_candidates.append((run, (), tuple(run_waivers)))
            else:
                candidate_reasons.append(
                    f"run:{run.run_id}:" + "|".join(sorted(set(reasons)))
                )

        if accepted_candidates:
            # Deterministic selection: newest completed evidence; digest breaks exact-time ties.
            selected, _, selected_waivers = max(
                accepted_candidates,
                key=lambda item: (item[0].completed_at, item[0].digest),
            )
            for waiver in selected_waivers:
                used_waivers[waiver.waiver_id] = waiver
            evidence.append(
                RequirementEvidence(
                    requirement_id=requirement.requirement_id,
                    selected_run_digest=selected.digest,
                    waived_metric_ids=tuple(sorted(item.metric_id for item in selected_waivers)),
                    blockers=(),
                )
            )
            slice_ = selected.benchmark_slice
            scopes.append(
                ValidatedScope(
                    requirement_id=requirement.requirement_id,
                    layer=selected.layer,
                    run_digest=selected.digest,
                    apparatus=slice_.apparatus,
                    camera_condition=slice_.camera_condition,
                    skill_family=slice_.skill_family,
                    challenge_tags=tuple(sorted(slice_.challenge_tags)),
                    dataset_digest=slice_.dataset.dataset_digest,
                    sample_count=slice_.sample_count,
                )
            )
        else:
            requirement_blocker = f"requirement-unsatisfied:{requirement.requirement_id}"
            global_blockers.append(requirement_blocker)
            evidence.append(
                RequirementEvidence(
                    requirement_id=requirement.requirement_id,
                    selected_run_digest=None,
                    waived_metric_ids=(),
                    blockers=tuple(sorted(set(candidate_reasons))) or ("unsatisfied",),
                )
            )

    status = PromotionStatus.PASSED if not global_blockers else PromotionStatus.BLOCKED
    return PromotionDecision(
        policy_id=policy.policy_id,
        policy_digest=policy.digest,
        gate=policy.gate,
        release_digest=release_digest,
        evaluated_at=evaluated_at,
        status=status,
        requirements=tuple(evidence),
        validated_scopes=tuple(sorted(scopes, key=lambda item: item.requirement_id)),
        active_waiver_digests=tuple(sorted(item.digest for item in used_waivers.values())),
        blockers=tuple(sorted(global_blockers)),
    )


def _decimal_text(value: Decimal) -> str:
    _require_finite_decimal("decimal", value)
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def _require_finite_decimal(label: str, value: Decimal) -> None:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise ValidationGovernanceError(f"{label} must be a finite Decimal")


def _stable_digest(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


def _require_sha256(label: str, value: str) -> None:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValidationGovernanceError(f"{label} must be lowercase SHA-256 hexadecimal")
