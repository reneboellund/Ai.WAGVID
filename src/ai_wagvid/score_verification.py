"""Post-routine score verification with an explicit AI-freeze boundary.

Official results are comparison data only. They cannot be attached before an immutable AI
reconstruction has been frozen. Material differences become evidence/rule-linked discrepancy
cases with append-only qualified human adjudication.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Iterable

from .domain import Apparatus
from .score_comparison import ScoreComparison, ScoreDifference, ScoreLine, compare_scores


class ScoreVerificationError(ValueError):
    pass


class DiscrepancyDecision(StrEnum):
    OFFICIAL_CONFIRMED = "official_confirmed"
    AI_SUPPORTED = "ai_supported"
    BOTH_PARTLY_WRONG = "both_partly_wrong"
    UNRESOLVED = "unresolved"


class DiscrepancyReason(StrEnum):
    ELEMENT_IDENTITY = "element_identity"
    COUNTING = "counting"
    COMPOSITION = "composition"
    CONNECTION = "connection"
    EXECUTION_SEVERITY = "execution_severity"
    ARTISTRY = "artistry"
    NEUTRAL = "neutral"
    ARITHMETIC = "arithmetic"
    OFFICIAL_DATA = "official_data"
    EVIDENCE_LIMITATION = "evidence_limitation"
    RULE_INTERPRETATION = "rule_interpretation"
    OTHER = "other"


@dataclass(frozen=True)
class LedgerReference:
    schema: str
    digest: str
    rulepack_id: str
    rulepack_digest: str
    resolved: bool
    unresolved_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.schema or not self.rulepack_id:
            raise ScoreVerificationError("ledger schema and rulepack_id are required")
        _require_sha256("ledger digest", self.digest)
        _require_sha256("ledger rulepack digest", self.rulepack_digest)
        if len(self.unresolved_refs) != len(set(self.unresolved_refs)):
            raise ScoreVerificationError("ledger unresolved references must be unique")
        if self.resolved and self.unresolved_refs:
            raise ScoreVerificationError("resolved ledger cannot contain unresolved references")


@dataclass(frozen=True)
class EvidenceLink:
    evidence_id: str
    evidence_digest: str

    def __post_init__(self) -> None:
        if not self.evidence_id:
            raise ScoreVerificationError("evidence_id is required")
        _require_sha256("evidence digest", self.evidence_digest)


@dataclass(frozen=True)
class RuleLink:
    rule_id: str
    source_locator: str

    def __post_init__(self) -> None:
        if not self.rule_id or not self.source_locator:
            raise ScoreVerificationError("rule_id and source locator are required")


@dataclass(frozen=True)
class AnalysisQualitySnapshot:
    media_id: str
    source_sha256: str
    apparatus: Apparatus
    calibration_state: str
    camera_suitability: str
    limitations: tuple[str, ...]
    model_digests: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.media_id or not self.calibration_state or not self.camera_suitability:
            raise ScoreVerificationError("media identity and quality states are required")
        _require_sha256("source media SHA-256", self.source_sha256)
        for digest in self.model_digests:
            _require_sha256("model digest", digest)
        if len(self.model_digests) != len(set(self.model_digests)):
            raise ScoreVerificationError("model digests must be unique")

    @property
    def digest(self) -> str:
        payload = asdict(self)
        payload["apparatus"] = self.apparatus.value
        return _stable_digest(payload)


@dataclass(frozen=True)
class FrozenAnalysis:
    analysis_id: str
    revision_id: str
    quality: AnalysisQualitySnapshot
    reconstructed_score: ScoreLine
    d_ledger: LedgerReference
    deduction_ledger: LedgerReference | None
    rulepack_id: str
    rulepack_digest: str
    software_digest: str
    frozen_at: datetime

    def __post_init__(self) -> None:
        if not self.analysis_id or not self.revision_id or not self.rulepack_id:
            raise ScoreVerificationError("analysis, revision and rulepack identity are required")
        if self.frozen_at.tzinfo is None or self.frozen_at.utcoffset() is None:
            raise ScoreVerificationError("frozen_at must be timezone-aware")
        _require_sha256("rulepack digest", self.rulepack_digest)
        _require_sha256("software digest", self.software_digest)
        if self.d_ledger.rulepack_id != self.rulepack_id:
            raise ScoreVerificationError("D ledger rulepack does not match frozen analysis")
        if self.d_ledger.rulepack_digest != self.rulepack_digest:
            raise ScoreVerificationError("D ledger rulepack digest does not match frozen analysis")
        if self.deduction_ledger is not None:
            if self.deduction_ledger.rulepack_id != self.rulepack_id:
                raise ScoreVerificationError("deduction ledger rulepack does not match frozen analysis")
            if self.deduction_ledger.rulepack_digest != self.rulepack_digest:
                raise ScoreVerificationError(
                    "deduction ledger rulepack digest does not match frozen analysis"
                )

    @property
    def digest(self) -> str:
        return _stable_digest(_frozen_payload(self))


@dataclass(frozen=True)
class OfficialScoreVersion:
    official_result_id: str
    version: int
    score: ScoreLine
    imported_at: datetime
    source_ref: str
    status: str = "official"

    def __post_init__(self) -> None:
        if not self.official_result_id or self.version < 1 or not self.source_ref:
            raise ScoreVerificationError("official result identity/version/source are required")
        if self.imported_at.tzinfo is None or self.imported_at.utcoffset() is None:
            raise ScoreVerificationError("official result imported_at must be timezone-aware")
        if not self.status:
            raise ScoreVerificationError("official result status is required")

    @property
    def digest(self) -> str:
        return _stable_digest(_official_payload(self))


@dataclass(frozen=True)
class ScoreVerificationComparison:
    frozen_analysis_digest: str
    official_score_digest: str
    comparison: ScoreComparison
    compared_at: datetime
    threshold: Decimal

    def __post_init__(self) -> None:
        _require_sha256("frozen analysis digest", self.frozen_analysis_digest)
        _require_sha256("official score digest", self.official_score_digest)
        if self.compared_at.tzinfo is None or self.compared_at.utcoffset() is None:
            raise ScoreVerificationError("compared_at must be timezone-aware")
        if self.threshold < 0:
            raise ScoreVerificationError("comparison threshold cannot be negative")

    @property
    def digest(self) -> str:
        return _stable_digest(_comparison_payload(self))


@dataclass(frozen=True)
class DiscrepancyCase:
    case_id: str
    comparison_digest: str
    field: str
    official_value: Decimal
    reconstructed_value: Decimal
    delta: Decimal
    evidence: tuple[EvidenceLink, ...]
    rules: tuple[RuleLink, ...]
    arithmetic_impact: Decimal
    confidence_milli: int | None
    created_at: datetime

    def __post_init__(self) -> None:
        if not self.case_id or not self.field:
            raise ScoreVerificationError("discrepancy case identity and field are required")
        _require_sha256("comparison digest", self.comparison_digest)
        if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
            raise ScoreVerificationError("discrepancy created_at must be timezone-aware")
        if self.confidence_milli is not None:
            if (
                isinstance(self.confidence_milli, bool)
                or not isinstance(self.confidence_milli, int)
                or not 0 <= self.confidence_milli <= 1000
            ):
                raise ScoreVerificationError("confidence_milli must be integer [0, 1000]")
        if self.delta != self.reconstructed_value - self.official_value:
            raise ScoreVerificationError("discrepancy delta arithmetic is inconsistent")
        if len({item.digest for item in self.evidence}) != len(self.evidence):
            raise ScoreVerificationError("duplicate evidence links in discrepancy case")

    @property
    def digest(self) -> str:
        return _stable_digest(_case_payload(self))


@dataclass(frozen=True)
class DiscrepancyAdjudication:
    adjudication_id: str
    case_digest: str
    reviewer_id: str
    reviewer_qualification_ref: str
    decision: DiscrepancyDecision
    reason_codes: tuple[DiscrepancyReason, ...]
    notes: str
    created_at: datetime
    supersedes_adjudication_id: str | None = None

    def __post_init__(self) -> None:
        if (
            not self.adjudication_id
            or not self.reviewer_id
            or not self.reviewer_qualification_ref
            or not self.notes.strip()
        ):
            raise ScoreVerificationError(
                "adjudication identity, qualified reviewer reference and notes are required"
            )
        _require_sha256("discrepancy case digest", self.case_digest)
        if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
            raise ScoreVerificationError("adjudication created_at must be timezone-aware")
        if not self.reason_codes:
            raise ScoreVerificationError("adjudication requires at least one reason code")
        if len(self.reason_codes) != len(set(self.reason_codes)):
            raise ScoreVerificationError("adjudication reason codes must be unique")

    @property
    def digest(self) -> str:
        payload = asdict(self)
        payload["decision"] = self.decision.value
        payload["reason_codes"] = [item.value for item in self.reason_codes]
        payload["created_at"] = self.created_at.astimezone(UTC).isoformat()
        return _stable_digest(payload)


class DiscrepancyAdjudicationLedger:
    """Append-only, non-forking adjudication history per immutable discrepancy case."""

    def __init__(self, cases: Iterable[DiscrepancyCase], adjudications: Iterable[DiscrepancyAdjudication] = ()) -> None:
        case_items = tuple(cases)
        self._cases = {item.case_id: item for item in case_items}
        if len(self._cases) != len(case_items):
            raise ScoreVerificationError("discrepancy case IDs must be unique")
        self._adjudications: dict[str, DiscrepancyAdjudication] = {}
        for item in adjudications:
            self.append(item)

    def append(self, adjudication: DiscrepancyAdjudication) -> None:
        existing = self._adjudications.get(adjudication.adjudication_id)
        if existing is not None:
            if existing == adjudication:
                return
            raise ScoreVerificationError("adjudication_id is immutable")
        case = next(
            (item for item in self._cases.values() if item.digest == adjudication.case_digest),
            None,
        )
        if case is None:
            raise ScoreVerificationError("adjudication references unknown discrepancy case")
        history = self.history(case.case_id)
        if adjudication.supersedes_adjudication_id is None:
            if history:
                raise ScoreVerificationError(
                    "later adjudication must explicitly supersede current adjudication"
                )
        else:
            previous = self._adjudications.get(adjudication.supersedes_adjudication_id)
            if previous is None:
                raise ScoreVerificationError("superseded adjudication does not exist")
            if previous.case_digest != adjudication.case_digest:
                raise ScoreVerificationError("adjudication cannot supersede a different discrepancy")
            if adjudication.created_at <= previous.created_at:
                raise ScoreVerificationError("superseding adjudication must be created later")
            if any(
                item.supersedes_adjudication_id == previous.adjudication_id
                for item in history
            ):
                raise ScoreVerificationError("discrepancy adjudication history cannot fork")
        self._adjudications[adjudication.adjudication_id] = adjudication

    def history(self, case_id: str) -> tuple[DiscrepancyAdjudication, ...]:
        case = self._cases.get(case_id)
        if case is None:
            raise ScoreVerificationError("unknown discrepancy case")
        return tuple(
            sorted(
                (
                    item
                    for item in self._adjudications.values()
                    if item.case_digest == case.digest
                ),
                key=lambda item: (item.created_at, item.adjudication_id),
            )
        )

    def current(self, case_id: str) -> DiscrepancyAdjudication | None:
        history = self.history(case_id)
        return history[-1] if history else None


def compare_frozen_to_official(
    frozen: FrozenAnalysis,
    official: OfficialScoreVersion,
    *,
    compared_at: datetime,
    threshold: Decimal = Decimal("0.100"),
) -> ScoreVerificationComparison:
    if compared_at.tzinfo is None or compared_at.utcoffset() is None:
        raise ScoreVerificationError("compared_at must be timezone-aware")
    if official.imported_at < frozen.frozen_at:
        raise ScoreVerificationError(
            "official score was imported before AI freeze; leakage-safe verification is invalid"
        )
    if compared_at < official.imported_at or compared_at < frozen.frozen_at:
        raise ScoreVerificationError("comparison cannot predate freeze or official import")
    return ScoreVerificationComparison(
        frozen_analysis_digest=frozen.digest,
        official_score_digest=official.digest,
        comparison=compare_scores(official.score, frozen.reconstructed_score, threshold=threshold),
        compared_at=compared_at,
        threshold=threshold,
    )


def discrepancy_cases_from_comparison(
    comparison: ScoreVerificationComparison,
    *,
    evidence_by_field: Mapping[str, tuple[EvidenceLink, ...]] | None = None,
    rules_by_field: Mapping[str, tuple[RuleLink, ...]] | None = None,
    confidence_by_field_milli: Mapping[str, int | None] | None = None,
) -> tuple[DiscrepancyCase, ...]:
    evidence_by_field = evidence_by_field or {}
    rules_by_field = rules_by_field or {}
    confidence_by_field_milli = confidence_by_field_milli or {}
    cases = []
    for difference in comparison.comparison.differences:
        if not difference.exceeds_threshold:
            continue
        cases.append(
            DiscrepancyCase(
                case_id=f"{difference.field}:{comparison.digest[:16]}",
                comparison_digest=comparison.digest,
                field=difference.field,
                official_value=difference.official,
                reconstructed_value=difference.proposed,
                delta=difference.delta,
                evidence=tuple(evidence_by_field.get(difference.field, ())),
                rules=tuple(rules_by_field.get(difference.field, ())),
                arithmetic_impact=difference.delta,
                confidence_milli=confidence_by_field_milli.get(difference.field),
                created_at=comparison.compared_at,
            )
        )
    return tuple(cases)


def _score_line_payload(score: ScoreLine) -> dict:
    return {
        "d_score": _decimal_text(score.d_score),
        "e_score": _decimal_text(score.e_score),
        "neutral": _decimal_text(score.neutral),
        "final_score": _decimal_text(score.final_score),
    }


def _frozen_payload(value: FrozenAnalysis) -> dict:
    return {
        "analysis_id": value.analysis_id,
        "revision_id": value.revision_id,
        "quality_digest": value.quality.digest,
        "reconstructed_score": _score_line_payload(value.reconstructed_score),
        "d_ledger": asdict(value.d_ledger),
        "deduction_ledger": asdict(value.deduction_ledger) if value.deduction_ledger else None,
        "rulepack_id": value.rulepack_id,
        "rulepack_digest": value.rulepack_digest,
        "software_digest": value.software_digest,
        "frozen_at": value.frozen_at.astimezone(UTC).isoformat(),
    }


def _official_payload(value: OfficialScoreVersion) -> dict:
    return {
        "official_result_id": value.official_result_id,
        "version": value.version,
        "score": _score_line_payload(value.score),
        "imported_at": value.imported_at.astimezone(UTC).isoformat(),
        "source_ref": value.source_ref,
        "status": value.status,
    }


def _comparison_payload(value: ScoreVerificationComparison) -> dict:
    return {
        "frozen_analysis_digest": value.frozen_analysis_digest,
        "official_score_digest": value.official_score_digest,
        "differences": [
            {
                "field": item.field,
                "official": _decimal_text(item.official),
                "proposed": _decimal_text(item.proposed),
                "delta": _decimal_text(item.delta),
                "exceeds_threshold": item.exceeds_threshold,
            }
            for item in value.comparison.differences
        ],
        "missing_fields": list(value.comparison.missing_fields),
        "compared_at": value.compared_at.astimezone(UTC).isoformat(),
        "threshold": _decimal_text(value.threshold),
    }


def _case_payload(value: DiscrepancyCase) -> dict:
    return {
        "case_id": value.case_id,
        "comparison_digest": value.comparison_digest,
        "field": value.field,
        "official_value": _decimal_text(value.official_value),
        "reconstructed_value": _decimal_text(value.reconstructed_value),
        "delta": _decimal_text(value.delta),
        "evidence": [asdict(item) for item in value.evidence],
        "rules": [asdict(item) for item in value.rules],
        "arithmetic_impact": _decimal_text(value.arithmetic_impact),
        "confidence_milli": value.confidence_milli,
        "created_at": value.created_at.astimezone(UTC).isoformat(),
    }


def _decimal_text(value: Decimal | None) -> str | None:
    if value is None:
        return None
    if not value.is_finite():
        raise ScoreVerificationError("score values must be finite decimals")
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def _stable_digest(payload: dict) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _require_sha256(label: str, value: str) -> None:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ScoreVerificationError(f"{label} must be lowercase SHA-256 hexadecimal")
