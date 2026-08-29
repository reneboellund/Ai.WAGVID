"""Cross-apparatus promotion gates for model, rulepack and benchmark evidence.

A VT/UB/BB/FX implementation is not promotable merely because an apparatus contract exists.
Promotion requires an immutable model bundle, an apparatus-matching pinned rulepack policy,
and an executed reproducible benchmark whose required slices pass declared thresholds.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from enum import StrEnum

from .domain import Apparatus
from .dscore import (
    AcceptedConnectionFact,
    AcceptedElementFact,
    DeterministicDScoreEngine,
    DScoreLedger,
    DScorePolicy,
)


class ApparatusPromotionError(ValueError):
    pass


class BenchmarkRunState(StrEnum):
    PLANNED = "planned"
    EXECUTED = "executed"
    INVALID = "invalid"


class SliceStatus(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    UNSUPPORTED = "unsupported"


class PromotionStatus(StrEnum):
    BLOCKED = "blocked"
    RESEARCH_FIXTURE = "research-fixture"
    REPRODUCIBLE_OFFLINE_COMPONENT = "reproducible-offline-component"
    INTEGRATED_POST_ROUTINE = "integrated-post-routine"


@dataclass(frozen=True)
class ApparatusModelBundle:
    model_bundle_id: str
    apparatus: Apparatus
    adapter_id: str
    adapter_version: str
    checkpoint_sha256: str
    config_sha256: str
    label_map_sha256: str
    training_dataset_manifest_sha256: str
    training_rights_ref: str
    framework: str
    framework_version: str
    created_at: datetime

    def __post_init__(self) -> None:
        for value, label in (
            (self.model_bundle_id, "model_bundle_id"),
            (self.adapter_id, "adapter_id"),
            (self.adapter_version, "adapter_version"),
            (self.training_rights_ref, "training_rights_ref"),
            (self.framework, "framework"),
            (self.framework_version, "framework_version"),
        ):
            if not value.strip():
                raise ApparatusPromotionError(f"{label} is required")
        for label, value in (
            ("checkpoint_sha256", self.checkpoint_sha256),
            ("config_sha256", self.config_sha256),
            ("label_map_sha256", self.label_map_sha256),
            ("training_dataset_manifest_sha256", self.training_dataset_manifest_sha256),
        ):
            _sha(label, value)
        _aware("model created_at", self.created_at)

    @property
    def digest(self) -> str:
        return _digest({**asdict(self), "apparatus": self.apparatus.value, "created_at": self.created_at.astimezone(UTC).isoformat()})


@dataclass(frozen=True)
class ApparatusRulepackBinding:
    apparatus: Apparatus
    rulepack_id: str
    rulepack_digest: str
    dscore_policy_digest: str
    reviewed_by: str
    reviewer_qualification_ref: str
    reviewed_at: datetime

    def __post_init__(self) -> None:
        if not self.rulepack_id or not self.reviewed_by or not self.reviewer_qualification_ref:
            raise ApparatusPromotionError("rulepack binding requires rulepack and qualified reviewer")
        _sha("rulepack_digest", self.rulepack_digest)
        _sha("dscore_policy_digest", self.dscore_policy_digest)
        _aware("rulepack reviewed_at", self.reviewed_at)

    @classmethod
    def from_policy(
        cls,
        policy: DScorePolicy,
        *,
        reviewed_by: str,
        reviewer_qualification_ref: str,
        reviewed_at: datetime,
    ) -> ApparatusRulepackBinding:
        return cls(
            apparatus=policy.apparatus,
            rulepack_id=policy.rulepack_id,
            rulepack_digest=policy.rulepack_digest,
            dscore_policy_digest=policy.digest,
            reviewed_by=reviewed_by,
            reviewer_qualification_ref=reviewer_qualification_ref,
            reviewed_at=reviewed_at,
        )


@dataclass(frozen=True)
class ApparatusAcceptedFacts:
    apparatus: Apparatus
    model_bundle_digest: str
    evidence_bundle_digest: str
    review_decision_digest: str
    elements: tuple[AcceptedElementFact, ...]
    connections: tuple[AcceptedConnectionFact, ...] = ()

    def __post_init__(self) -> None:
        for label, value in (
            ("model_bundle_digest", self.model_bundle_digest),
            ("evidence_bundle_digest", self.evidence_bundle_digest),
            ("review_decision_digest", self.review_decision_digest),
        ):
            _sha(label, value)
        if not self.elements:
            raise ApparatusPromotionError("accepted apparatus facts require at least one element")


@dataclass(frozen=True)
class BenchmarkMetric:
    metric_id: str
    value_milli: int
    threshold_milli: int
    higher_is_better: bool

    def __post_init__(self) -> None:
        if not self.metric_id:
            raise ApparatusPromotionError("benchmark metric_id is required")
        for label, value in (("value_milli", self.value_milli), ("threshold_milli", self.threshold_milli)):
            if isinstance(value, bool) or not isinstance(value, int):
                raise ApparatusPromotionError(f"{label} must be integer")

    @property
    def passes(self) -> bool:
        return self.value_milli >= self.threshold_milli if self.higher_is_better else self.value_milli <= self.threshold_milli


@dataclass(frozen=True)
class BenchmarkSliceResult:
    slice_id: str
    dimensions: tuple[tuple[str, str], ...]
    metrics: tuple[BenchmarkMetric, ...]
    status: SliceStatus
    sample_count: int
    failure_reason: str | None = None

    def __post_init__(self) -> None:
        if not self.slice_id or self.sample_count < 0:
            raise ApparatusPromotionError("benchmark slice identity/sample_count invalid")
        if len(self.dimensions) != len(set(self.dimensions)):
            raise ApparatusPromotionError("benchmark slice dimensions must be unique")
        if self.status is SliceStatus.PASS:
            if self.sample_count == 0 or not self.metrics:
                raise ApparatusPromotionError("passing benchmark slice requires samples and metrics")
            if any(not metric.passes for metric in self.metrics):
                raise ApparatusPromotionError("passing benchmark slice contains failed metric")
        if self.status in {SliceStatus.FAIL, SliceStatus.UNSUPPORTED} and not self.failure_reason:
            raise ApparatusPromotionError("failed/unsupported benchmark slice requires reason")


@dataclass(frozen=True)
class ApparatusBenchmarkReport:
    benchmark_id: str
    apparatus: Apparatus
    run_state: BenchmarkRunState
    model_bundle_digest: str
    rulepack_digest: str
    benchmark_manifest_sha256: str
    validation_dataset_manifest_sha256: str
    split_manifest_sha256: str
    rights_ref: str
    hardware_runtime_manifest_sha256: str
    slices: tuple[BenchmarkSliceResult, ...]
    required_slice_ids: tuple[str, ...]
    executed_at: datetime | None

    def __post_init__(self) -> None:
        if not self.benchmark_id or not self.rights_ref:
            raise ApparatusPromotionError("benchmark ID and rights reference are required")
        for label, value in (
            ("model_bundle_digest", self.model_bundle_digest),
            ("rulepack_digest", self.rulepack_digest),
            ("benchmark_manifest_sha256", self.benchmark_manifest_sha256),
            ("validation_dataset_manifest_sha256", self.validation_dataset_manifest_sha256),
            ("split_manifest_sha256", self.split_manifest_sha256),
            ("hardware_runtime_manifest_sha256", self.hardware_runtime_manifest_sha256),
        ):
            _sha(label, value)
        slice_ids = [item.slice_id for item in self.slices]
        if len(slice_ids) != len(set(slice_ids)):
            raise ApparatusPromotionError("benchmark slice IDs must be unique")
        if len(self.required_slice_ids) != len(set(self.required_slice_ids)):
            raise ApparatusPromotionError("required benchmark slice IDs must be unique")
        unknown_required = set(self.required_slice_ids) - set(slice_ids)
        if unknown_required:
            raise ApparatusPromotionError("required benchmark slices missing from report: " + ",".join(sorted(unknown_required)))
        if self.run_state is BenchmarkRunState.EXECUTED:
            if self.executed_at is None:
                raise ApparatusPromotionError("executed benchmark requires executed_at")
            _aware("benchmark executed_at", self.executed_at)
        elif self.executed_at is not None:
            _aware("benchmark executed_at", self.executed_at)

    @property
    def required_slices_pass(self) -> bool:
        by_id: Mapping[str, BenchmarkSliceResult] = {item.slice_id: item for item in self.slices}
        return bool(self.required_slice_ids) and all(by_id[item].status is SliceStatus.PASS for item in self.required_slice_ids)

    @property
    def digest(self) -> str:
        return _digest({
            "benchmark_id": self.benchmark_id,
            "apparatus": self.apparatus.value,
            "run_state": self.run_state.value,
            "model_bundle_digest": self.model_bundle_digest,
            "rulepack_digest": self.rulepack_digest,
            "benchmark_manifest_sha256": self.benchmark_manifest_sha256,
            "validation_dataset_manifest_sha256": self.validation_dataset_manifest_sha256,
            "split_manifest_sha256": self.split_manifest_sha256,
            "rights_ref": self.rights_ref,
            "hardware_runtime_manifest_sha256": self.hardware_runtime_manifest_sha256,
            "slices": [
                {
                    "slice_id": item.slice_id,
                    "dimensions": list(item.dimensions),
                    "metrics": [asdict(metric) for metric in item.metrics],
                    "status": item.status.value,
                    "sample_count": item.sample_count,
                    "failure_reason": item.failure_reason,
                }
                for item in self.slices
            ],
            "required_slice_ids": list(self.required_slice_ids),
            "executed_at": self.executed_at.astimezone(UTC).isoformat() if self.executed_at else None,
        })


@dataclass(frozen=True)
class ApparatusPromotionDecision:
    apparatus: Apparatus
    status: PromotionStatus
    blockers: tuple[str, ...]
    model_bundle_digest: str
    rulepack_digest: str
    benchmark_digest: str
    dscore_ledger_digest: str | None


def evaluate_accepted_dscore(
    *,
    policy: DScorePolicy,
    binding: ApparatusRulepackBinding,
    accepted_facts: ApparatusAcceptedFacts,
) -> DScoreLedger:
    if policy.apparatus is not accepted_facts.apparatus or binding.apparatus is not accepted_facts.apparatus:
        raise ApparatusPromotionError("apparatus mismatch between accepted facts, rulepack binding and D-score policy")
    if policy.rulepack_id != binding.rulepack_id or policy.rulepack_digest != binding.rulepack_digest:
        raise ApparatusPromotionError("pinned rulepack does not match reviewed rulepack binding")
    if policy.digest != binding.dscore_policy_digest:
        raise ApparatusPromotionError("D-score policy digest does not match reviewed binding")
    return DeterministicDScoreEngine(policy).evaluate(elements=accepted_facts.elements, connections=accepted_facts.connections)


def evaluate_apparatus_promotion(
    *,
    model: ApparatusModelBundle,
    binding: ApparatusRulepackBinding,
    accepted_facts: ApparatusAcceptedFacts,
    benchmark: ApparatusBenchmarkReport,
    dscore_ledger: DScoreLedger | None,
) -> ApparatusPromotionDecision:
    apparatuses = {model.apparatus, binding.apparatus, accepted_facts.apparatus, benchmark.apparatus}
    if len(apparatuses) != 1:
        raise ApparatusPromotionError("promotion inputs must all target one apparatus")

    blockers: list[str] = []
    if accepted_facts.model_bundle_digest != model.digest:
        blockers.append("accepted-facts-model-digest-mismatch")
    if benchmark.model_bundle_digest != model.digest:
        blockers.append("benchmark-model-digest-mismatch")
    if benchmark.rulepack_digest != binding.rulepack_digest:
        blockers.append("benchmark-rulepack-digest-mismatch")
    if benchmark.run_state is not BenchmarkRunState.EXECUTED:
        blockers.append("benchmark-not-executed")
    if not benchmark.required_slices_pass:
        blockers.append("required-benchmark-slices-not-passed")
    if dscore_ledger is None:
        blockers.append("dscore-ledger-missing")
    else:
        if dscore_ledger.apparatus is not model.apparatus:
            blockers.append("dscore-ledger-apparatus-mismatch")
        if dscore_ledger.rulepack_digest != binding.rulepack_digest:
            blockers.append("dscore-ledger-rulepack-mismatch")
        if dscore_ledger.policy_digest != binding.dscore_policy_digest:
            blockers.append("dscore-ledger-policy-mismatch")
        if dscore_ledger.evaluation_blockers:
            blockers.append("dscore-ledger-blocked")

    status = PromotionStatus.BLOCKED if blockers else PromotionStatus.INTEGRATED_POST_ROUTINE
    return ApparatusPromotionDecision(
        apparatus=model.apparatus,
        status=status,
        blockers=tuple(sorted(set(blockers))),
        model_bundle_digest=model.digest,
        rulepack_digest=binding.rulepack_digest,
        benchmark_digest=benchmark.digest,
        dscore_ledger_digest=dscore_ledger.digest if dscore_ledger is not None else None,
    )


def _sha(label: str, value: str) -> None:
    if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise ApparatusPromotionError(f"{label} must be lowercase SHA-256 hexadecimal")


def _aware(label: str, value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ApparatusPromotionError(f"{label} must be timezone-aware")


def _digest(payload: object) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()
