"""Human-in-the-loop review workflow for evidence-first Ai.WAGVID analysis.

AI proposal, deterministic rule output, official-result comparison and human decision are separate
artifact classes. Material decisions cannot be bulk-approved and every revision is append-only.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from enum import StrEnum

from .domain import Apparatus


class ReviewWorkflowError(ValueError):
    pass


class ReviewReason(StrEnum):
    UNKNOWN_ELEMENT = "unknown-element"
    LOW_CONFIDENCE = "low-confidence"
    POOR_QUALITY = "poor-quality"
    RULE_MISMATCH = "rule-mismatch"
    SCORE_DISCREPANCY = "score-discrepancy"
    DEDUCTION_REVIEW = "deduction-review"
    OOD_OR_UNAVAILABLE = "ood-or-unavailable"
    HUMAN_REQUESTED = "human-requested"


class ReviewArtifactKind(StrEnum):
    AI_PROPOSAL = "ai-proposal"
    DETERMINISTIC_RULE_RESULT = "deterministic-rule-result"
    OFFICIAL_RESULT = "official-result"
    EVIDENCE = "evidence"
    RULE_SOURCE = "rule-source"
    HUMAN_REVISION = "human-revision"


class ReviewAction(StrEnum):
    ACCEPT = "accept"
    REJECT = "reject"
    REVISE = "revise"
    ESCALATE = "escalate"


class ReviewState(StrEnum):
    OPEN = "open"
    ASSIGNED = "assigned"
    ESCALATED = "escalated"
    RESOLVED = "resolved"


@dataclass(frozen=True)
class ReviewArtifactRef:
    artifact_id: str
    artifact_digest: str
    kind: ReviewArtifactKind
    schema: str | None = None

    def __post_init__(self) -> None:
        if not self.artifact_id:
            raise ReviewWorkflowError("review artifact_id is required")
        _require_sha256("review artifact digest", self.artifact_digest)
        if self.schema is not None and not self.schema:
            raise ReviewWorkflowError("review artifact schema cannot be empty")

    @property
    def digest(self) -> str:
        payload = asdict(self)
        payload["kind"] = self.kind.value
        return _stable_digest(payload)


@dataclass(frozen=True)
class ReviewItem:
    review_id: str
    organization_id: str
    analysis_id: str
    analysis_revision_id: str
    analysis_revision_digest: str
    apparatus: Apparatus
    reason: ReviewReason
    material: bool
    created_at: datetime
    confidence_milli: int | None
    evidence: tuple[ReviewArtifactRef, ...]
    ai_proposal: ReviewArtifactRef | None = None
    deterministic_result: ReviewArtifactRef | None = None
    official_result: ReviewArtifactRef | None = None
    rule_sources: tuple[ReviewArtifactRef, ...] = ()
    assignee_id: str | None = None

    def __post_init__(self) -> None:
        if (
            not self.review_id
            or not self.organization_id
            or not self.analysis_id
            or not self.analysis_revision_id
        ):
            raise ReviewWorkflowError("review/organization/analysis/revision identity is required")
        _require_sha256("analysis revision digest", self.analysis_revision_digest)
        _require_aware("review created_at", self.created_at)
        if self.confidence_milli is not None and (
            isinstance(self.confidence_milli, bool)
            or not isinstance(self.confidence_milli, int)
            or not 0 <= self.confidence_milli <= 1000
        ):
            raise ReviewWorkflowError("confidence_milli must be integer [0, 1000]")
        if not self.evidence:
            raise ReviewWorkflowError("review item requires at least one evidence reference")
        if any(item.kind is not ReviewArtifactKind.EVIDENCE for item in self.evidence):
            raise ReviewWorkflowError("review evidence tuple may contain evidence refs only")
        if self.ai_proposal is not None and self.ai_proposal.kind is not ReviewArtifactKind.AI_PROPOSAL:
            raise ReviewWorkflowError("ai_proposal reference has wrong artifact kind")
        if (
            self.deterministic_result is not None
            and self.deterministic_result.kind is not ReviewArtifactKind.DETERMINISTIC_RULE_RESULT
        ):
            raise ReviewWorkflowError("deterministic result reference has wrong artifact kind")
        if self.official_result is not None and self.official_result.kind is not ReviewArtifactKind.OFFICIAL_RESULT:
            raise ReviewWorkflowError("official result reference has wrong artifact kind")
        if any(item.kind is not ReviewArtifactKind.RULE_SOURCE for item in self.rule_sources):
            raise ReviewWorkflowError("rule_sources may contain rule-source refs only")
        artifact_digests = [item.digest for item in self.evidence]
        if len(artifact_digests) != len(set(artifact_digests)):
            raise ReviewWorkflowError("review evidence references must be unique")
        if self.reason is ReviewReason.SCORE_DISCREPANCY:
            if self.official_result is None:
                raise ReviewWorkflowError("score discrepancy review requires official result reference")
            if self.deterministic_result is None:
                raise ReviewWorkflowError(
                    "score discrepancy review requires deterministic result reference"
                )
        if self.reason is ReviewReason.RULE_MISMATCH and not self.rule_sources:
            raise ReviewWorkflowError("rule mismatch review requires rule source reference")

    @property
    def digest(self) -> str:
        return _stable_digest(
            {
                "review_id": self.review_id,
                "organization_id": self.organization_id,
                "analysis_id": self.analysis_id,
                "analysis_revision_id": self.analysis_revision_id,
                "analysis_revision_digest": self.analysis_revision_digest,
                "apparatus": self.apparatus.value,
                "reason": self.reason.value,
                "material": self.material,
                "created_at": self.created_at.astimezone(UTC).isoformat(),
                "confidence_milli": self.confidence_milli,
                "evidence_digests": [item.digest for item in self.evidence],
                "ai_proposal_digest": self.ai_proposal.digest if self.ai_proposal else None,
                "deterministic_result_digest": (
                    self.deterministic_result.digest if self.deterministic_result else None
                ),
                "official_result_digest": self.official_result.digest if self.official_result else None,
                "rule_source_digests": [item.digest for item in self.rule_sources],
                "assignee_id": self.assignee_id,
            }
        )


@dataclass(frozen=True)
class ReviewDecision:
    decision_id: str
    review_id: str
    review_item_digest: str
    action: ReviewAction
    reviewer_id: str
    reviewer_qualification_ref: str | None
    reason_code: str
    notes: str
    created_at: datetime
    revised_artifact: ReviewArtifactRef | None = None
    supersedes_decision_id: str | None = None

    def __post_init__(self) -> None:
        if not self.decision_id or not self.review_id or not self.reviewer_id:
            raise ReviewWorkflowError("review decision identity/review/reviewer are required")
        _require_sha256("review item digest", self.review_item_digest)
        if not self.reason_code or not self.notes.strip():
            raise ReviewWorkflowError("review decision requires reason code and notes")
        _require_aware("review decision created_at", self.created_at)
        if self.action is ReviewAction.REVISE:
            if self.revised_artifact is None:
                raise ReviewWorkflowError("revise action requires revised artifact")
            if self.revised_artifact.kind is not ReviewArtifactKind.HUMAN_REVISION:
                raise ReviewWorkflowError("revised artifact must be human-revision kind")
        elif self.revised_artifact is not None:
            raise ReviewWorkflowError("only revise action may carry revised artifact")

    @property
    def digest(self) -> str:
        return _stable_digest(
            {
                "decision_id": self.decision_id,
                "review_id": self.review_id,
                "review_item_digest": self.review_item_digest,
                "action": self.action.value,
                "reviewer_id": self.reviewer_id,
                "reviewer_qualification_ref": self.reviewer_qualification_ref,
                "reason_code": self.reason_code,
                "notes": self.notes,
                "created_at": self.created_at.astimezone(UTC).isoformat(),
                "revised_artifact_digest": (
                    self.revised_artifact.digest if self.revised_artifact else None
                ),
                "supersedes_decision_id": self.supersedes_decision_id,
            }
        )


@dataclass(frozen=True)
class ReviewAssignment:
    review_id: str
    review_item_digest: str
    assignee_id: str
    assigned_by: str
    assigned_at: datetime

    def __post_init__(self) -> None:
        if not self.review_id or not self.assignee_id or not self.assigned_by:
            raise ReviewWorkflowError("review assignment review/assignee/actor are required")
        _require_sha256("review item digest", self.review_item_digest)
        _require_aware("review assigned_at", self.assigned_at)

    @property
    def digest(self) -> str:
        payload = asdict(self)
        payload["assigned_at"] = self.assigned_at.astimezone(UTC).isoformat()
        return _stable_digest(payload)


class ReviewDecisionLedger:
    """Append-only, non-forking human decision history for one immutable review item."""

    def __init__(
        self,
        item: ReviewItem,
        decisions: Iterable[ReviewDecision] = (),
    ) -> None:
        self.item = item
        self._decisions: list[ReviewDecision] = []
        for decision in decisions:
            self.append(decision)

    def append(self, decision: ReviewDecision) -> None:
        if decision.review_id != self.item.review_id:
            raise ReviewWorkflowError("review decision belongs to another review item")
        if decision.review_item_digest != self.item.digest:
            raise ReviewWorkflowError("review decision targets a different review item revision")
        if self.item.material and not decision.reviewer_qualification_ref:
            raise ReviewWorkflowError("material review decision requires reviewer qualification")
        if any(existing.decision_id == decision.decision_id for existing in self._decisions):
            existing = next(
                existing
                for existing in self._decisions
                if existing.decision_id == decision.decision_id
            )
            if existing == decision:
                return
            raise ReviewWorkflowError("review decision ID is immutable")
        if not self._decisions:
            if decision.supersedes_decision_id is not None:
                raise ReviewWorkflowError("first review decision cannot supersede another decision")
        else:
            current = self._decisions[-1]
            if decision.supersedes_decision_id != current.decision_id:
                raise ReviewWorkflowError("new review decision must explicitly supersede current decision")
            if decision.created_at <= current.created_at:
                raise ReviewWorkflowError("superseding review decision must be created later")
        self._decisions.append(decision)

    @property
    def decisions(self) -> tuple[ReviewDecision, ...]:
        return tuple(self._decisions)

    @property
    def current(self) -> ReviewDecision | None:
        return self._decisions[-1] if self._decisions else None

    @property
    def state(self) -> ReviewState:
        current = self.current
        if current is not None:
            return ReviewState.ESCALATED if current.action is ReviewAction.ESCALATE else ReviewState.RESOLVED
        return ReviewState.ASSIGNED if self.item.assignee_id else ReviewState.OPEN


@dataclass(frozen=True)
class ReviewFilter:
    reasons: frozenset[ReviewReason] = frozenset()
    apparatuses: frozenset[Apparatus] = frozenset()
    assignee_id: str | None = None
    unassigned_only: bool = False
    confidence_at_most_milli: int | None = None
    minimum_age_seconds: int | None = None
    material_only: bool = False

    def __post_init__(self) -> None:
        if self.assignee_id is not None and self.unassigned_only:
            raise ReviewWorkflowError("cannot filter by assignee and unassigned_only together")
        if self.confidence_at_most_milli is not None and (
            isinstance(self.confidence_at_most_milli, bool)
            or not isinstance(self.confidence_at_most_milli, int)
            or not 0 <= self.confidence_at_most_milli <= 1000
        ):
            raise ReviewWorkflowError("confidence filter must be integer [0, 1000]")
        if self.minimum_age_seconds is not None and (
            isinstance(self.minimum_age_seconds, bool)
            or not isinstance(self.minimum_age_seconds, int)
            or self.minimum_age_seconds < 0
        ):
            raise ReviewWorkflowError("minimum age must be non-negative integer seconds")


def filter_review_inbox(
    items: Iterable[ReviewItem],
    *,
    filter: ReviewFilter | None = None,
    now: datetime,
) -> tuple[ReviewItem, ...]:
    filter = filter or ReviewFilter()
    _require_aware("review inbox time", now)
    result = []
    for item in items:
        if filter.reasons and item.reason not in filter.reasons:
            continue
        if filter.apparatuses and item.apparatus not in filter.apparatuses:
            continue
        if filter.assignee_id is not None and item.assignee_id != filter.assignee_id:
            continue
        if filter.unassigned_only and item.assignee_id is not None:
            continue
        if filter.material_only and not item.material:
            continue
        if filter.confidence_at_most_milli is not None and (
            item.confidence_milli is None
            or item.confidence_milli > filter.confidence_at_most_milli
        ):
            continue
        if filter.minimum_age_seconds is not None:
            age_seconds = int((now - item.created_at).total_seconds())
            if age_seconds < filter.minimum_age_seconds:
                continue
        result.append(item)
    return tuple(sorted(result, key=lambda item: (item.created_at, item.review_id)))


def validate_bulk_action(items: Iterable[ReviewItem], action: ReviewAction) -> tuple[str, ...]:
    """Return safe review IDs for a bulk operation or fail closed for material resolution."""
    item_tuple = tuple(items)
    if action in {ReviewAction.ACCEPT, ReviewAction.REJECT, ReviewAction.REVISE}:
        material_ids = tuple(sorted(item.review_id for item in item_tuple if item.material))
        if material_ids:
            raise ReviewWorkflowError(
                "material review items cannot be bulk-resolved: " + ",".join(material_ids)
            )
    if action is ReviewAction.REVISE:
        # A revision is item-specific and requires an immutable replacement artifact, so the
        # generic bulk layer never performs revise even for non-material items.
        raise ReviewWorkflowError("revise is item-specific and cannot be a generic bulk action")
    return tuple(sorted(item.review_id for item in item_tuple))


@dataclass(frozen=True)
class ReviewEvidenceExport:
    export_id: str
    review_item_digest: str
    decision_digests: tuple[str, ...]
    evidence_digests: tuple[str, ...]
    rule_source_digests: tuple[str, ...]
    analysis_revision_digest: str
    created_at: datetime

    def __post_init__(self) -> None:
        if not self.export_id:
            raise ReviewWorkflowError("review evidence export_id is required")
        for label, value in (
            ("review item digest", self.review_item_digest),
            ("analysis revision digest", self.analysis_revision_digest),
        ):
            _require_sha256(label, value)
        for digest in (*self.decision_digests, *self.evidence_digests, *self.rule_source_digests):
            _require_sha256("review export member digest", digest)
        _require_aware("review export created_at", self.created_at)

    @property
    def digest(self) -> str:
        return _stable_digest(
            {
                "export_id": self.export_id,
                "review_item_digest": self.review_item_digest,
                "decision_digests": list(self.decision_digests),
                "evidence_digests": list(self.evidence_digests),
                "rule_source_digests": list(self.rule_source_digests),
                "analysis_revision_digest": self.analysis_revision_digest,
                "created_at": self.created_at.astimezone(UTC).isoformat(),
            }
        )


def build_review_evidence_export(
    item: ReviewItem,
    ledger: ReviewDecisionLedger,
    *,
    created_at: datetime,
) -> ReviewEvidenceExport:
    if ledger.item.digest != item.digest:
        raise ReviewWorkflowError("review ledger belongs to another review item")
    seed = _stable_digest(
        {
            "review_item_digest": item.digest,
            "decision_digests": [decision.digest for decision in ledger.decisions],
            "analysis_revision_digest": item.analysis_revision_digest,
        }
    )
    return ReviewEvidenceExport(
        export_id=f"review-export:{seed[:32]}",
        review_item_digest=item.digest,
        decision_digests=tuple(decision.digest for decision in ledger.decisions),
        evidence_digests=tuple(ref.artifact_digest for ref in item.evidence),
        rule_source_digests=tuple(ref.artifact_digest for ref in item.rule_sources),
        analysis_revision_digest=item.analysis_revision_digest,
        created_at=created_at,
    )


def _stable_digest(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


def _require_sha256(label: str, value: str) -> None:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ReviewWorkflowError(f"{label} must be lowercase SHA-256 hexadecimal")


def _require_aware(label: str, value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ReviewWorkflowError(f"{label} must be timezone-aware")
