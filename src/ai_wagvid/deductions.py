"""Evidence-linked deduction assistance with mandatory attributable decisions.

The module validates model/observer proposals against a pinned rule-pack deduction ontology.
A proposal is never itself a deduction in the score ledger. Only an explicit, attributable
human decision can create an accepted deduction entry. Qualitative artistry criteria always
require human judgement, and unavailable camera/evidence state fails closed.

No FIG deduction values are embedded here. Unit values and criteria are rule-pack data.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Iterable, Mapping

from .domain import Apparatus


class DeductionError(ValueError):
    pass


class DeductionChannel(StrEnum):
    EXECUTION = "execution"
    ARTISTRY = "artistry"
    NEUTRAL = "neutral"


class DeductionScope(StrEnum):
    ELEMENT = "element"
    PHASE = "phase"
    ROUTINE = "routine"
    PROCEDURAL = "procedural"


class ProposalState(StrEnum):
    READY_FOR_CONFIRMATION = "ready-for-confirmation"
    NEEDS_REVIEW = "needs-review"
    UNAVAILABLE = "unavailable"


class RuleApplicability(StrEnum):
    EXACT = "exact"
    CONDITIONAL = "conditional"
    AMBIGUOUS = "ambiguous"
    UNAVAILABLE = "unavailable"


class DecisionAction(StrEnum):
    ACCEPT = "accept"
    REJECT = "reject"
    CHANGE = "change"
    ESCALATE = "escalate"


@dataclass(frozen=True)
class SeverityRule:
    severity_id: str
    deduction_units: int
    source_rule_id: str | None = None

    def __post_init__(self) -> None:
        if not self.severity_id:
            raise DeductionError("severity_id is required")
        if self.deduction_units < 0:
            raise DeductionError("deduction units cannot be negative")


@dataclass(frozen=True)
class DeductionRule:
    rule_id: str
    channel: DeductionChannel
    criterion_id: str
    scope: DeductionScope
    severities: tuple[SeverityRule, ...]
    required_camera_capabilities: frozenset[str] = frozenset()
    minimum_evidence_quality_milli: int = 0
    minimum_model_confidence_milli: int = 0
    human_judgement_required: bool = False
    source_rule_id: str | None = None

    def __post_init__(self) -> None:
        if not self.rule_id or not self.criterion_id or not self.severities:
            raise DeductionError("deduction rule identity, criterion and severities are required")
        _require_milli("minimum_evidence_quality_milli", self.minimum_evidence_quality_milli)
        _require_milli("minimum_model_confidence_milli", self.minimum_model_confidence_milli)
        severity_ids = [item.severity_id for item in self.severities]
        if len(severity_ids) != len(set(severity_ids)):
            raise DeductionError("severity IDs must be unique within a deduction rule")
        if any(not item.strip() for item in self.required_camera_capabilities):
            raise DeductionError("camera capability names cannot be empty")
        if self.channel is DeductionChannel.ARTISTRY and not self.human_judgement_required:
            raise DeductionError("artistry criteria must require human judgement")

    @property
    def severity_map(self) -> Mapping[str, SeverityRule]:
        return {item.severity_id: item for item in self.severities}


@dataclass(frozen=True)
class DeductionPolicy:
    rulepack_id: str
    rulepack_digest: str
    apparatus: Apparatus
    units_per_point: int
    rules: tuple[DeductionRule, ...]

    def __post_init__(self) -> None:
        if not self.rulepack_id or not self.rules:
            raise DeductionError("rulepack_id and deduction rules are required")
        _require_sha256("rulepack_digest", self.rulepack_digest)
        if self.units_per_point < 1:
            raise DeductionError("units_per_point must be positive")
        rule_ids = [item.rule_id for item in self.rules]
        if len(rule_ids) != len(set(rule_ids)):
            raise DeductionError("deduction rule IDs must be unique")

    @property
    def rule_map(self) -> Mapping[str, DeductionRule]:
        return {item.rule_id: item for item in self.rules}

    @property
    def digest(self) -> str:
        return _stable_digest(
            {
                "rulepack_id": self.rulepack_id,
                "rulepack_digest": self.rulepack_digest,
                "apparatus": self.apparatus.value,
                "units_per_point": self.units_per_point,
                "rules": [_rule_payload(item) for item in sorted(self.rules, key=lambda value: value.rule_id)],
            }
        )


@dataclass(frozen=True)
class DeductionCandidate:
    candidate_id: str
    rule_id: str
    scope_ref: str
    evidence_ids: tuple[str, ...]
    observation_ids: tuple[str, ...]
    proposed_severity_id: str | None
    model_confidence_milli: int | None
    evidence_quality_milli: int | None
    camera_ids: tuple[str, ...]
    camera_capabilities: frozenset[str]
    producer_id: str
    producer_digest: str
    notes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.candidate_id or not self.rule_id or not self.scope_ref or not self.producer_id:
            raise DeductionError("candidate identity, rule, scope and producer are required")
        _require_sha256("producer_digest", self.producer_digest)
        if self.model_confidence_milli is not None:
            _require_milli("model_confidence_milli", self.model_confidence_milli)
        if self.evidence_quality_milli is not None:
            _require_milli("evidence_quality_milli", self.evidence_quality_milli)
        if len(self.evidence_ids) != len(set(self.evidence_ids)):
            raise DeductionError("candidate evidence IDs must be unique")
        if len(self.observation_ids) != len(set(self.observation_ids)):
            raise DeductionError("candidate observation IDs must be unique")
        if len(self.camera_ids) != len(set(self.camera_ids)):
            raise DeductionError("candidate camera IDs must be unique")
        if any(not item.strip() for item in self.camera_capabilities):
            raise DeductionError("candidate camera capabilities cannot contain empty values")

    @property
    def digest(self) -> str:
        payload = asdict(self)
        payload["camera_capabilities"] = sorted(self.camera_capabilities)
        return _stable_digest(payload)


@dataclass(frozen=True)
class DeductionProposal:
    candidate_id: str
    candidate_digest: str
    rule_id: str
    channel: DeductionChannel
    criterion_id: str
    scope: DeductionScope
    scope_ref: str
    allowed_severities: tuple[SeverityRule, ...]
    model_suggested_severity_id: str | None
    model_suggested_units: int | None
    state: ProposalState
    rule_applicability: RuleApplicability
    evidence_ids: tuple[str, ...]
    observation_ids: tuple[str, ...]
    camera_ids: tuple[str, ...]
    missing_camera_capabilities: tuple[str, ...]
    review_reasons: tuple[str, ...]
    human_judgement_required: bool
    source_rule_id: str | None
    producer_id: str
    producer_digest: str

    @property
    def digest(self) -> str:
        return _stable_digest(_proposal_payload(self))


@dataclass(frozen=True)
class DeductionDecision:
    decision_id: str
    proposal_digest: str
    candidate_id: str
    action: DecisionAction
    author_id: str
    created_at: datetime
    reason: str
    selected_severity_id: str | None = None
    supersedes_decision_id: str | None = None

    def __post_init__(self) -> None:
        if not self.decision_id or not self.candidate_id or not self.author_id or not self.reason.strip():
            raise DeductionError("decision identity, candidate, author and reason are required")
        _require_sha256("proposal_digest", self.proposal_digest)
        if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
            raise DeductionError("decision timestamp must be timezone-aware")
        if self.action in {DecisionAction.ACCEPT, DecisionAction.CHANGE}:
            if not self.selected_severity_id:
                raise DeductionError("accept/change decision requires explicit selected severity")
        elif self.selected_severity_id is not None:
            raise DeductionError("reject/escalate decision cannot select a severity")

    @property
    def digest(self) -> str:
        payload = asdict(self)
        payload["action"] = self.action.value
        payload["created_at"] = self.created_at.astimezone(UTC).isoformat()
        return _stable_digest(payload)


@dataclass(frozen=True)
class AcceptedDeductionEntry:
    candidate_id: str
    rule_id: str
    channel: DeductionChannel
    criterion_id: str
    scope: DeductionScope
    scope_ref: str
    severity_id: str
    deduction_units: int
    evidence_ids: tuple[str, ...]
    decision_id: str
    decision_author_id: str
    decision_reason: str
    source_rule_id: str | None


@dataclass(frozen=True)
class DeductionLedger:
    rulepack_id: str
    rulepack_digest: str
    policy_digest: str
    apparatus: Apparatus
    units_per_point: int
    accepted: tuple[AcceptedDeductionEntry, ...]
    rejected_candidate_ids: tuple[str, ...]
    unresolved_candidate_ids: tuple[str, ...]
    escalated_candidate_ids: tuple[str, ...]
    accepted_deduction_units: int

    @property
    def fully_resolved(self) -> bool:
        return not self.unresolved_candidate_ids and not self.escalated_candidate_ids

    def normalized_dict(self) -> dict:
        return {
            "schema": "ai.wagvid.deduction-ledger.v1",
            "rulepack_id": self.rulepack_id,
            "rulepack_digest": self.rulepack_digest,
            "policy_digest": self.policy_digest,
            "apparatus": self.apparatus.value,
            "units_per_point": self.units_per_point,
            "accepted": [
                {
                    **asdict(item),
                    "channel": item.channel.value,
                    "scope": item.scope.value,
                    "evidence_ids": list(item.evidence_ids),
                }
                for item in self.accepted
            ],
            "rejected_candidate_ids": list(self.rejected_candidate_ids),
            "unresolved_candidate_ids": list(self.unresolved_candidate_ids),
            "escalated_candidate_ids": list(self.escalated_candidate_ids),
            "accepted_deduction_units": self.accepted_deduction_units,
            "fully_resolved": self.fully_resolved,
        }

    def normalized_json(self) -> str:
        return json.dumps(self.normalized_dict(), sort_keys=True, separators=(",", ":"))

    @property
    def digest(self) -> str:
        return hashlib.sha256(self.normalized_json().encode()).hexdigest()


class DeductionDecisionLedger:
    """Append-only, non-forking decisions bound to immutable proposal digests."""

    def __init__(
        self,
        policy: DeductionPolicy,
        proposals: Iterable[DeductionProposal],
        decisions: Iterable[DeductionDecision] = (),
    ) -> None:
        self.policy = policy
        self._proposals = {item.candidate_id: item for item in proposals}
        if len(self._proposals) != len(tuple(proposals)):
            # This path is only reachable for re-iterable input; normal callers use tuples.
            raise DeductionError("proposal candidate IDs must be unique")
        self._decisions: dict[str, DeductionDecision] = {}
        for decision in decisions:
            self.append(decision)

    def append(self, decision: DeductionDecision) -> None:
        existing = self._decisions.get(decision.decision_id)
        if existing is not None:
            if existing == decision:
                return
            raise DeductionError("decision_id is immutable")
        proposal = self._proposals.get(decision.candidate_id)
        if proposal is None:
            raise DeductionError("decision references unknown deduction candidate")
        if proposal.digest != decision.proposal_digest:
            raise DeductionError("decision proposal digest does not match current immutable proposal")
        if decision.action in {DecisionAction.ACCEPT, DecisionAction.CHANGE}:
            if proposal.state is ProposalState.UNAVAILABLE:
                raise DeductionError("unavailable proposal cannot be accepted without revised evidence")
            allowed = {item.severity_id for item in proposal.allowed_severities}
            if decision.selected_severity_id not in allowed:
                raise DeductionError("decision severity is not allowed by the pinned rule")
        history = self.history(decision.candidate_id)
        if decision.supersedes_decision_id is None:
            if history:
                raise DeductionError("later decision must explicitly supersede the current decision")
        else:
            previous = self._decisions.get(decision.supersedes_decision_id)
            if previous is None:
                raise DeductionError("superseded decision does not exist")
            if previous.candidate_id != decision.candidate_id:
                raise DeductionError("decision cannot supersede a different candidate")
            if decision.created_at <= previous.created_at:
                raise DeductionError("superseding decision must be created later")
            if any(item.supersedes_decision_id == previous.decision_id for item in history):
                raise DeductionError("deduction decision history cannot fork")
        self._decisions[decision.decision_id] = decision

    def history(self, candidate_id: str) -> tuple[DeductionDecision, ...]:
        return tuple(
            sorted(
                (item for item in self._decisions.values() if item.candidate_id == candidate_id),
                key=lambda item: (item.created_at, item.decision_id),
            )
        )

    def current(self, candidate_id: str) -> DeductionDecision | None:
        history = self.history(candidate_id)
        return history[-1] if history else None

    @property
    def proposals(self) -> tuple[DeductionProposal, ...]:
        return tuple(sorted(self._proposals.values(), key=lambda item: item.candidate_id))


def evaluate_deduction_candidate(
    policy: DeductionPolicy,
    candidate: DeductionCandidate,
) -> DeductionProposal:
    rule = policy.rule_map.get(candidate.rule_id)
    if rule is None:
        raise DeductionError(f"candidate references unknown deduction rule: {candidate.rule_id}")
    severity_map = rule.severity_map
    if candidate.proposed_severity_id is not None and candidate.proposed_severity_id not in severity_map:
        raise DeductionError("candidate severity is not allowed by the pinned deduction rule")

    missing_camera = tuple(sorted(rule.required_camera_capabilities - candidate.camera_capabilities))
    reasons: list[str] = []
    unavailable = False
    if not candidate.evidence_ids:
        reasons.append("evidence-unavailable")
        unavailable = True
    if missing_camera:
        reasons.extend(f"missing-camera-capability:{item}" for item in missing_camera)
        unavailable = True
    if candidate.evidence_quality_milli is None:
        reasons.append("evidence-quality-unavailable")
        unavailable = True
    elif candidate.evidence_quality_milli < rule.minimum_evidence_quality_milli:
        reasons.append(
            "evidence-quality-below-rule-threshold:"
            f"{candidate.evidence_quality_milli}<{rule.minimum_evidence_quality_milli}"
        )
    if candidate.model_confidence_milli is None:
        reasons.append("model-confidence-unavailable")
    elif candidate.model_confidence_milli < rule.minimum_model_confidence_milli:
        reasons.append(
            "model-confidence-below-rule-threshold:"
            f"{candidate.model_confidence_milli}<{rule.minimum_model_confidence_milli}"
        )
    if candidate.proposed_severity_id is None:
        reasons.append("severity-unresolved")
    if rule.human_judgement_required:
        reasons.append("qualitative-human-judgement-required")

    if unavailable:
        state = ProposalState.UNAVAILABLE
        applicability = RuleApplicability.UNAVAILABLE
    elif (
        candidate.proposed_severity_id is None
        or candidate.model_confidence_milli is None
        or candidate.model_confidence_milli < rule.minimum_model_confidence_milli
    ):
        state = ProposalState.NEEDS_REVIEW
        applicability = RuleApplicability.AMBIGUOUS
    elif (
        candidate.evidence_quality_milli is not None
        and candidate.evidence_quality_milli < rule.minimum_evidence_quality_milli
    ):
        state = ProposalState.NEEDS_REVIEW
        applicability = RuleApplicability.CONDITIONAL
    elif rule.human_judgement_required:
        state = ProposalState.NEEDS_REVIEW
        applicability = RuleApplicability.CONDITIONAL
    else:
        state = ProposalState.READY_FOR_CONFIRMATION
        applicability = RuleApplicability.EXACT

    suggested = (
        severity_map.get(candidate.proposed_severity_id)
        if candidate.proposed_severity_id is not None
        else None
    )
    return DeductionProposal(
        candidate_id=candidate.candidate_id,
        candidate_digest=candidate.digest,
        rule_id=rule.rule_id,
        channel=rule.channel,
        criterion_id=rule.criterion_id,
        scope=rule.scope,
        scope_ref=candidate.scope_ref,
        allowed_severities=tuple(sorted(rule.severities, key=lambda item: item.severity_id)),
        model_suggested_severity_id=candidate.proposed_severity_id,
        model_suggested_units=(suggested.deduction_units if suggested is not None else None),
        state=state,
        rule_applicability=applicability,
        evidence_ids=tuple(candidate.evidence_ids),
        observation_ids=tuple(candidate.observation_ids),
        camera_ids=tuple(candidate.camera_ids),
        missing_camera_capabilities=missing_camera,
        review_reasons=tuple(reasons),
        human_judgement_required=rule.human_judgement_required,
        source_rule_id=rule.source_rule_id,
        producer_id=candidate.producer_id,
        producer_digest=candidate.producer_digest,
    )


def build_deduction_ledger(
    policy: DeductionPolicy,
    proposals: Iterable[DeductionProposal],
    decisions: DeductionDecisionLedger,
) -> DeductionLedger:
    proposal_items = tuple(sorted(proposals, key=lambda item: item.candidate_id))
    proposal_ids = [item.candidate_id for item in proposal_items]
    if len(proposal_ids) != len(set(proposal_ids)):
        raise DeductionError("proposal candidate IDs must be unique")
    if decisions.policy.digest != policy.digest:
        raise DeductionError("decision ledger belongs to a different deduction policy")
    if {item.candidate_id for item in decisions.proposals} != set(proposal_ids):
        raise DeductionError("decision ledger proposal set differs from requested deduction ledger")

    accepted: list[AcceptedDeductionEntry] = []
    rejected: list[str] = []
    unresolved: list[str] = []
    escalated: list[str] = []
    for proposal in proposal_items:
        decision = decisions.current(proposal.candidate_id)
        if decision is None:
            unresolved.append(proposal.candidate_id)
            continue
        if decision.action is DecisionAction.REJECT:
            rejected.append(proposal.candidate_id)
            continue
        if decision.action is DecisionAction.ESCALATE:
            escalated.append(proposal.candidate_id)
            continue
        severity = next(
            item for item in proposal.allowed_severities
            if item.severity_id == decision.selected_severity_id
        )
        accepted.append(
            AcceptedDeductionEntry(
                candidate_id=proposal.candidate_id,
                rule_id=proposal.rule_id,
                channel=proposal.channel,
                criterion_id=proposal.criterion_id,
                scope=proposal.scope,
                scope_ref=proposal.scope_ref,
                severity_id=severity.severity_id,
                deduction_units=severity.deduction_units,
                evidence_ids=proposal.evidence_ids,
                decision_id=decision.decision_id,
                decision_author_id=decision.author_id,
                decision_reason=decision.reason,
                source_rule_id=severity.source_rule_id or proposal.source_rule_id,
            )
        )
    accepted.sort(key=lambda item: (item.channel.value, item.scope_ref, item.candidate_id))
    return DeductionLedger(
        rulepack_id=policy.rulepack_id,
        rulepack_digest=policy.rulepack_digest,
        policy_digest=policy.digest,
        apparatus=policy.apparatus,
        units_per_point=policy.units_per_point,
        accepted=tuple(accepted),
        rejected_candidate_ids=tuple(sorted(rejected)),
        unresolved_candidate_ids=tuple(sorted(unresolved)),
        escalated_candidate_ids=tuple(sorted(escalated)),
        accepted_deduction_units=sum(item.deduction_units for item in accepted),
    )


def _rule_payload(rule: DeductionRule) -> dict:
    return {
        "rule_id": rule.rule_id,
        "channel": rule.channel.value,
        "criterion_id": rule.criterion_id,
        "scope": rule.scope.value,
        "severities": [
            asdict(item) for item in sorted(rule.severities, key=lambda value: value.severity_id)
        ],
        "required_camera_capabilities": sorted(rule.required_camera_capabilities),
        "minimum_evidence_quality_milli": rule.minimum_evidence_quality_milli,
        "minimum_model_confidence_milli": rule.minimum_model_confidence_milli,
        "human_judgement_required": rule.human_judgement_required,
        "source_rule_id": rule.source_rule_id,
    }


def _proposal_payload(proposal: DeductionProposal) -> dict:
    return {
        "candidate_id": proposal.candidate_id,
        "candidate_digest": proposal.candidate_digest,
        "rule_id": proposal.rule_id,
        "channel": proposal.channel.value,
        "criterion_id": proposal.criterion_id,
        "scope": proposal.scope.value,
        "scope_ref": proposal.scope_ref,
        "allowed_severities": [asdict(item) for item in proposal.allowed_severities],
        "model_suggested_severity_id": proposal.model_suggested_severity_id,
        "model_suggested_units": proposal.model_suggested_units,
        "state": proposal.state.value,
        "rule_applicability": proposal.rule_applicability.value,
        "evidence_ids": list(proposal.evidence_ids),
        "observation_ids": list(proposal.observation_ids),
        "camera_ids": list(proposal.camera_ids),
        "missing_camera_capabilities": list(proposal.missing_camera_capabilities),
        "review_reasons": list(proposal.review_reasons),
        "human_judgement_required": proposal.human_judgement_required,
        "source_rule_id": proposal.source_rule_id,
        "producer_id": proposal.producer_id,
        "producer_digest": proposal.producer_digest,
    }


def _stable_digest(payload: dict) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _require_milli(label: str, value: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 1000:
        raise DeductionError(f"{label} must be an integer in [0, 1000]")


def _require_sha256(label: str, value: str) -> None:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise DeductionError(f"{label} must be lowercase SHA-256 hexadecimal")
