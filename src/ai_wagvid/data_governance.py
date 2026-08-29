"""Cross-cutting data governance contracts for post-event Ai.WAGVID.

This module defines policy/provenance, not authentication transport or storage deletion. Django,
KIGA, object-storage and secret-store adapters execute these decisions while preserving their own
audit records.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import math
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Iterable, Mapping


class DataGovernanceError(ValueError):
    pass


class GovernedPermission(StrEnum):
    VIEW = "view"
    DOWNLOAD = "download"
    ANALYZE = "analyze"
    RETAIN = "retain"
    TRAIN = "train"
    EXPORT = "export"
    SHARE_EVIDENCE = "share-evidence"


class RightsLifecycle(StrEnum):
    ACTIVE = "active"
    REVOKED = "revoked"


class DeletionDisposition(StrEnum):
    BLOCKED = "blocked"
    QUARANTINE_ONLY = "quarantine-only"
    PHYSICAL_DELETE_ALLOWED = "physical-delete-allowed"


class EvidenceKind(StrEnum):
    SOURCE_INTERVAL = "source-interval"
    PROXY = "proxy"
    OVERLAY = "overlay"
    INTERPOLATED = "interpolated"
    GENERATED_VISUALIZATION = "generated-visualization"


class DecisionSemanticLayer(StrEnum):
    OBSERVED_FACT = "observed-fact"
    JUDGING_INTERPRETATION = "judging-interpretation"
    SCORE_EFFECT = "score-effect"
    PATTERN = "pattern"
    COACHING_HYPOTHESIS = "coaching-hypothesis"
    TRAINING_FOCUS = "suggested-training-focus"


class DecisionState(StrEnum):
    PROVISIONAL = "provisional"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"
    UNRESOLVED = "unresolved"


@dataclass(frozen=True)
class DatasetRightsRecord:
    record_id: str
    source_reference: str
    source_digest: str
    rights_reference: str
    rights_digest: str
    permissions: frozenset[GovernedPermission]
    retention_class: str
    valid_from: datetime
    valid_until: datetime | None = None
    lifecycle: RightsLifecycle = RightsLifecycle.ACTIVE
    revoked_at: datetime | None = None

    def __post_init__(self) -> None:
        if not self.record_id or not self.source_reference or not self.rights_reference or not self.retention_class:
            raise DataGovernanceError(
                "rights record ID/source/rights reference/retention class are required"
            )
        _require_sha256("source_digest", self.source_digest)
        _require_sha256("rights_digest", self.rights_digest)
        if not self.permissions:
            raise DataGovernanceError("rights record requires at least one explicit permission")
        _require_aware("valid_from", self.valid_from)
        if self.valid_until is not None:
            _require_aware("valid_until", self.valid_until)
            if self.valid_until <= self.valid_from:
                raise DataGovernanceError("rights valid_until must be after valid_from")
        if self.lifecycle is RightsLifecycle.REVOKED:
            if self.revoked_at is None:
                raise DataGovernanceError("revoked rights record requires revoked_at")
        elif self.revoked_at is not None:
            raise DataGovernanceError("active rights record cannot contain revoked_at")
        if self.revoked_at is not None:
            _require_aware("revoked_at", self.revoked_at)
            if self.revoked_at < self.valid_from:
                raise DataGovernanceError("rights cannot be revoked before becoming valid")

    def allows(self, permission: GovernedPermission, *, at: datetime) -> bool:
        _require_aware("rights evaluation time", at)
        if permission not in self.permissions:
            return False
        if at < self.valid_from:
            return False
        if self.valid_until is not None and at >= self.valid_until:
            return False
        if self.lifecycle is RightsLifecycle.REVOKED:
            return False
        if self.revoked_at is not None and at >= self.revoked_at:
            return False
        return True

    @property
    def digest(self) -> str:
        return _stable_digest(
            {
                "record_id": self.record_id,
                "source_reference": self.source_reference,
                "source_digest": self.source_digest,
                "rights_reference": self.rights_reference,
                "rights_digest": self.rights_digest,
                "permissions": sorted(item.value for item in self.permissions),
                "retention_class": self.retention_class,
                "valid_from": self.valid_from.astimezone(UTC).isoformat(),
                "valid_until": self.valid_until.astimezone(UTC).isoformat() if self.valid_until else None,
                "lifecycle": self.lifecycle.value,
                "revoked_at": self.revoked_at.astimezone(UTC).isoformat() if self.revoked_at else None,
            }
        )


def pseudonymous_group_id(
    *,
    namespace: str,
    stable_source_id: str,
    secret: bytes,
    prefix: str = "pseudo",
) -> str:
    """Derive a non-reversible stable grouping ID without storing the source ID in the output."""
    if not namespace or not stable_source_id or not prefix:
        raise DataGovernanceError("pseudonym namespace/source/prefix are required")
    if not isinstance(secret, bytes) or len(secret) < 32:
        raise DataGovernanceError("pseudonym secret must contain at least 32 bytes")
    digest = hmac.new(secret, f"{namespace}\x00{stable_source_id}".encode(), hashlib.sha256).hexdigest()
    return f"{prefix}:{digest[:32]}"


@dataclass(frozen=True)
class RetentionRecord:
    media_id: str
    source_sha256: str
    acquired_at: datetime
    retention_until: datetime | None
    retention_class: str
    legal_hold_ids: tuple[str, ...] = ()
    provider_immutable_until: datetime | None = None

    def __post_init__(self) -> None:
        if not self.media_id or not self.retention_class:
            raise DataGovernanceError("retention media_id and retention_class are required")
        _require_sha256("source_sha256", self.source_sha256)
        _require_aware("acquired_at", self.acquired_at)
        if self.retention_until is not None:
            _require_aware("retention_until", self.retention_until)
            if self.retention_until < self.acquired_at:
                raise DataGovernanceError("retention_until cannot predate acquisition")
        if self.provider_immutable_until is not None:
            _require_aware("provider_immutable_until", self.provider_immutable_until)
            if self.provider_immutable_until < self.acquired_at:
                raise DataGovernanceError("provider immutable time cannot predate acquisition")
        if len(self.legal_hold_ids) != len(set(self.legal_hold_ids)):
            raise DataGovernanceError("legal hold IDs must be unique")
        if any(not item for item in self.legal_hold_ids):
            raise DataGovernanceError("legal hold IDs cannot be empty")


@dataclass(frozen=True)
class DeletionRequest:
    request_id: str
    media_id: str
    requested_by: str
    approved_by: str
    reason: str
    requested_at: datetime
    correlation_id: str

    def __post_init__(self) -> None:
        if (
            not self.request_id
            or not self.media_id
            or not self.requested_by
            or not self.approved_by
            or not self.reason.strip()
            or not self.correlation_id
        ):
            raise DataGovernanceError(
                "deletion request requires identity, requester, approver, reason and correlation ID"
            )
        _require_aware("deletion requested_at", self.requested_at)

    @property
    def digest(self) -> str:
        payload = asdict(self)
        payload["requested_at"] = self.requested_at.astimezone(UTC).isoformat()
        return _stable_digest(payload)


@dataclass(frozen=True)
class DeletionDecision:
    media_id: str
    request_digest: str
    evaluated_at: datetime
    disposition: DeletionDisposition
    blockers: tuple[str, ...]
    earliest_physical_delete_at: datetime | None

    def __post_init__(self) -> None:
        _require_sha256("deletion request digest", self.request_digest)
        _require_aware("deletion evaluated_at", self.evaluated_at)
        if self.disposition is DeletionDisposition.PHYSICAL_DELETE_ALLOWED and self.blockers:
            raise DataGovernanceError("allowed physical deletion cannot have blockers")
        if self.earliest_physical_delete_at is not None:
            _require_aware("earliest physical delete time", self.earliest_physical_delete_at)


def evaluate_deletion(
    retention: RetentionRecord,
    request: DeletionRequest,
    *,
    now: datetime,
    rights: DatasetRightsRecord | None,
    active_evidence_refs: Iterable[str] = (),
    active_dataset_refs: Iterable[str] = (),
    active_export_refs: Iterable[str] = (),
    provider_delete_allowed: bool = True,
) -> DeletionDecision:
    _require_aware("deletion evaluation time", now)
    if request.media_id != retention.media_id:
        raise DataGovernanceError("deletion request belongs to different media")
    blockers: list[str] = []
    candidate_dates: list[datetime] = []
    if request.requested_at > now:
        blockers.append("deletion-request-is-in-the-future")
    if retention.retention_until is not None and now < retention.retention_until:
        blockers.append("retention-window-active")
        candidate_dates.append(retention.retention_until)
    if retention.provider_immutable_until is not None and now < retention.provider_immutable_until:
        blockers.append("provider-immutability-active")
        candidate_dates.append(retention.provider_immutable_until)
    if retention.legal_hold_ids:
        blockers.extend(f"legal-hold:{item}" for item in sorted(retention.legal_hold_ids))
    evidence_refs = tuple(sorted(set(active_evidence_refs)))
    dataset_refs = tuple(sorted(set(active_dataset_refs)))
    export_refs = tuple(sorted(set(active_export_refs)))
    blockers.extend(f"active-evidence-ref:{item}" for item in evidence_refs)
    blockers.extend(f"active-dataset-ref:{item}" for item in dataset_refs)
    blockers.extend(f"active-export-ref:{item}" for item in export_refs)
    if rights is not None and rights.allows(GovernedPermission.RETAIN, at=now):
        # Retain permission is an authorization to retain, not an automatic legal hold. The
        # explicit retention class/window above remains the destructive-operation control.
        pass
    if not provider_delete_allowed:
        blockers.append("provider-delete-denied")

    if blockers:
        non_time_blockers = [
            item
            for item in blockers
            if item not in {"retention-window-active", "provider-immutability-active"}
        ]
        disposition = (
            DeletionDisposition.QUARANTINE_ONLY
            if not non_time_blockers
            else DeletionDisposition.BLOCKED
        )
        earliest = max(candidate_dates) if candidate_dates and not non_time_blockers else None
    else:
        disposition = DeletionDisposition.PHYSICAL_DELETE_ALLOWED
        earliest = now
    return DeletionDecision(
        media_id=retention.media_id,
        request_digest=request.digest,
        evaluated_at=now,
        disposition=disposition,
        blockers=tuple(blockers),
        earliest_physical_delete_at=earliest,
    )


_SECRET_FIELD_NAMES = frozenset(
    {
        "password",
        "passwd",
        "secret",
        "secret_key",
        "api_key",
        "access_key",
        "private_key",
        "token",
        "refresh_token",
        "client_secret",
    }
)


@dataclass(frozen=True)
class FrozenConfigSnapshot:
    snapshot_id: str
    organization_id: str
    schema_version: str
    public_config_json: str
    config_digest: str
    secret_references: tuple[str, ...]
    created_at: datetime

    def __post_init__(self) -> None:
        if not self.snapshot_id or not self.organization_id or not self.schema_version:
            raise DataGovernanceError("config snapshot identity/org/schema are required")
        _require_sha256("config_digest", self.config_digest)
        _require_aware("config created_at", self.created_at)
        if len(self.secret_references) != len(set(self.secret_references)):
            raise DataGovernanceError("secret references must be unique")
        try:
            payload = json.loads(self.public_config_json)
        except json.JSONDecodeError as error:
            raise DataGovernanceError("frozen public config is not valid JSON") from error
        if _stable_digest(payload) != self.config_digest:
            raise DataGovernanceError("frozen config digest mismatch")
        _reject_plaintext_secret_fields(payload)


def freeze_configuration(
    config: Mapping[str, Any],
    *,
    snapshot_id: str,
    organization_id: str,
    schema_version: str,
    secret_references: Iterable[str],
    created_at: datetime,
) -> FrozenConfigSnapshot:
    _reject_plaintext_secret_fields(config)
    _require_json_safe(config)
    payload_json = json.dumps(config, sort_keys=True, separators=(",", ":"), allow_nan=False)
    digest = hashlib.sha256(payload_json.encode()).hexdigest()
    return FrozenConfigSnapshot(
        snapshot_id=snapshot_id,
        organization_id=organization_id,
        schema_version=schema_version,
        public_config_json=payload_json,
        config_digest=digest,
        secret_references=tuple(sorted(set(secret_references))),
        created_at=created_at,
    )


@dataclass(frozen=True)
class AuthorizedConfigChange:
    change_id: str
    organization_id: str
    from_config_digest: str
    to_config_digest: str
    actor_id: str
    approver_id: str
    reason: str
    correlation_id: str
    occurred_at: datetime
    prior_change_digest: str | None = None

    def __post_init__(self) -> None:
        if (
            not self.change_id
            or not self.organization_id
            or not self.actor_id
            or not self.approver_id
            or not self.reason.strip()
            or not self.correlation_id
        ):
            raise DataGovernanceError(
                "config change identity/org/actor/approver/reason/correlation are required"
            )
        _require_sha256("from_config_digest", self.from_config_digest)
        _require_sha256("to_config_digest", self.to_config_digest)
        if self.from_config_digest == self.to_config_digest:
            raise DataGovernanceError("config change must change the configuration digest")
        _require_aware("config change occurred_at", self.occurred_at)
        if self.prior_change_digest is not None:
            _require_sha256("prior_change_digest", self.prior_change_digest)

    @property
    def digest(self) -> str:
        payload = asdict(self)
        payload["occurred_at"] = self.occurred_at.astimezone(UTC).isoformat()
        return _stable_digest(payload)


class ConfigChangeLedger:
    """Append-only authorized config history anchored to a frozen snapshot digest."""

    def __init__(
        self,
        initial_snapshot: FrozenConfigSnapshot,
        changes: Iterable[AuthorizedConfigChange] = (),
    ) -> None:
        self.initial_snapshot = initial_snapshot
        self._changes: list[AuthorizedConfigChange] = []
        for change in changes:
            self.append(change)

    def append(self, change: AuthorizedConfigChange) -> None:
        if change.organization_id != self.initial_snapshot.organization_id:
            raise DataGovernanceError("config change belongs to another organization")
        if any(item.change_id == change.change_id for item in self._changes):
            existing = next(item for item in self._changes if item.change_id == change.change_id)
            if existing == change:
                return
            raise DataGovernanceError("config change ID is immutable")
        expected_from = self.current_config_digest
        if change.from_config_digest != expected_from:
            raise DataGovernanceError("config change does not start from current frozen digest")
        if not self._changes:
            if change.prior_change_digest is not None:
                raise DataGovernanceError("first config change cannot reference prior change")
        else:
            previous = self._changes[-1]
            if change.prior_change_digest != previous.digest:
                raise DataGovernanceError("config change hash chain mismatch")
            if change.occurred_at <= previous.occurred_at:
                raise DataGovernanceError("config change timestamps must increase")
        self._changes.append(change)

    @property
    def changes(self) -> tuple[AuthorizedConfigChange, ...]:
        return tuple(self._changes)

    @property
    def current_config_digest(self) -> str:
        return (
            self._changes[-1].to_config_digest
            if self._changes
            else self.initial_snapshot.config_digest
        )


@dataclass(frozen=True)
class EvidenceProvenanceRef:
    evidence_id: str
    evidence_digest: str
    canonical_source_sha256: str
    kind: EvidenceKind
    represented_as_original: bool

    def __post_init__(self) -> None:
        if not self.evidence_id:
            raise DataGovernanceError("evidence_id is required")
        _require_sha256("evidence_digest", self.evidence_digest)
        _require_sha256("canonical_source_sha256", self.canonical_source_sha256)
        if self.represented_as_original and self.kind is not EvidenceKind.SOURCE_INTERVAL:
            raise DataGovernanceError(
                "proxy/overlay/interpolated/generated evidence cannot be represented as original"
            )
        if self.kind is EvidenceKind.SOURCE_INTERVAL and not self.represented_as_original:
            raise DataGovernanceError("source interval evidence must be represented as original")

    @property
    def digest(self) -> str:
        payload = asdict(self)
        payload["kind"] = self.kind.value
        return _stable_digest(payload)


@dataclass(frozen=True)
class ProductionDecisionProvenance:
    decision_id: str
    organization_id: str
    object_ref: str
    semantic_layer: DecisionSemanticLayer
    state: DecisionState
    material: bool
    authority_ref: str
    evidence: tuple[EvidenceProvenanceRef, ...]
    rulepack_digest: str
    model_bundle_digest: str
    software_digest: str
    config_digest: str
    calibration_digest: str | None
    created_at: datetime
    limitations: tuple[str, ...] = ()
    supersedes_decision_id: str | None = None

    def __post_init__(self) -> None:
        if (
            not self.decision_id
            or not self.organization_id
            or not self.object_ref
            or not self.authority_ref
        ):
            raise DataGovernanceError("decision identity/org/object/authority are required")
        for label, value in (
            ("rulepack_digest", self.rulepack_digest),
            ("model_bundle_digest", self.model_bundle_digest),
            ("software_digest", self.software_digest),
            ("config_digest", self.config_digest),
        ):
            _require_sha256(label, value)
        if self.calibration_digest is not None:
            _require_sha256("calibration_digest", self.calibration_digest)
        _require_aware("decision created_at", self.created_at)
        if not self.evidence:
            raise DataGovernanceError("production decision requires evidence provenance")
        if len({item.digest for item in self.evidence}) != len(self.evidence):
            raise DataGovernanceError("production decision evidence references must be unique")
        if self.material and self.state is DecisionState.CONFIRMED:
            if not any(item.kind is EvidenceKind.SOURCE_INTERVAL for item in self.evidence):
                raise DataGovernanceError(
                    "confirmed material decision requires canonical source-interval evidence"
                )
        if self.calibration_digest is None and self.semantic_layer in {
            DecisionSemanticLayer.OBSERVED_FACT,
            DecisionSemanticLayer.JUDGING_INTERPRETATION,
            DecisionSemanticLayer.SCORE_EFFECT,
        }:
            if not any("calibration-unavailable" in item for item in self.limitations):
                raise DataGovernanceError(
                    "missing calibration provenance must be explicitly recorded as a limitation"
                )
        if len(self.limitations) != len(set(self.limitations)):
            raise DataGovernanceError("decision limitations must be unique")

    @property
    def digest(self) -> str:
        return _stable_digest(
            {
                "decision_id": self.decision_id,
                "organization_id": self.organization_id,
                "object_ref": self.object_ref,
                "semantic_layer": self.semantic_layer.value,
                "state": self.state.value,
                "material": self.material,
                "authority_ref": self.authority_ref,
                "evidence_digests": [item.digest for item in self.evidence],
                "rulepack_digest": self.rulepack_digest,
                "model_bundle_digest": self.model_bundle_digest,
                "software_digest": self.software_digest,
                "config_digest": self.config_digest,
                "calibration_digest": self.calibration_digest,
                "created_at": self.created_at.astimezone(UTC).isoformat(),
                "limitations": list(self.limitations),
                "supersedes_decision_id": self.supersedes_decision_id,
            }
        )


class ProductionDecisionLedger:
    """Append-only non-forking decision provenance history per governed object."""

    def __init__(self, decisions: Iterable[ProductionDecisionProvenance] = ()) -> None:
        self._decisions: dict[str, ProductionDecisionProvenance] = {}
        for decision in decisions:
            self.append(decision)

    def append(self, decision: ProductionDecisionProvenance) -> None:
        existing = self._decisions.get(decision.decision_id)
        if existing is not None:
            if existing == decision:
                return
            raise DataGovernanceError("production decision ID is immutable")
        history = self.history(decision.organization_id, decision.object_ref)
        if decision.supersedes_decision_id is None:
            if history:
                raise DataGovernanceError(
                    "new decision revision must explicitly supersede current decision"
                )
        else:
            previous = self._decisions.get(decision.supersedes_decision_id)
            if previous is None:
                raise DataGovernanceError("superseded decision does not exist")
            if (
                previous.organization_id != decision.organization_id
                or previous.object_ref != decision.object_ref
            ):
                raise DataGovernanceError("decision cannot supersede another governed object")
            if decision.created_at <= previous.created_at:
                raise DataGovernanceError("superseding decision must be created later")
            if any(
                item.supersedes_decision_id == previous.decision_id for item in history
            ):
                raise DataGovernanceError("production decision history cannot fork")
        self._decisions[decision.decision_id] = decision

    def history(
        self, organization_id: str, object_ref: str
    ) -> tuple[ProductionDecisionProvenance, ...]:
        return tuple(
            sorted(
                (
                    item
                    for item in self._decisions.values()
                    if item.organization_id == organization_id and item.object_ref == object_ref
                ),
                key=lambda item: (item.created_at, item.decision_id),
            )
        )

    def current(
        self, organization_id: str, object_ref: str
    ) -> ProductionDecisionProvenance | None:
        history = self.history(organization_id, object_ref)
        return history[-1] if history else None


def _reject_plaintext_secret_fields(value: Any, *, path: str = "$") -> None:
    if isinstance(value, Mapping):
        for raw_key, child in value.items():
            if not isinstance(raw_key, str):
                raise DataGovernanceError(f"configuration key at {path} must be a string")
            normalized = raw_key.casefold().replace("-", "_")
            if normalized.endswith("_ref") or normalized.endswith("_reference"):
                pass
            elif normalized in _SECRET_FIELD_NAMES or any(
                normalized.endswith(f"_{suffix}") for suffix in _SECRET_FIELD_NAMES
            ):
                raise DataGovernanceError(
                    f"plaintext secret-like configuration field is forbidden: {path}.{raw_key}"
                )
            _reject_plaintext_secret_fields(child, path=f"{path}.{raw_key}")
    elif isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            _reject_plaintext_secret_fields(child, path=f"{path}[{index}]")


def _require_json_safe(value: Any, *, path: str = "$") -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            if not isinstance(key, str):
                raise DataGovernanceError(f"JSON key at {path} must be string")
            _require_json_safe(child, path=f"{path}.{key}")
        return
    if isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            _require_json_safe(child, path=f"{path}[{index}]")
        return
    if isinstance(value, float) and not math.isfinite(value):
        raise DataGovernanceError(f"non-finite configuration value at {path}")
    if isinstance(value, (str, int, float, bool)) or value is None:
        return
    raise DataGovernanceError(f"unsupported configuration value at {path}: {type(value).__name__}")


def _stable_digest(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


def _require_sha256(label: str, value: str) -> None:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise DataGovernanceError(f"{label} must be lowercase SHA-256 hexadecimal")


def _require_aware(label: str, value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise DataGovernanceError(f"{label} must be timezone-aware")
