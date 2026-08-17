"""Stable KIGA integration boundary around Ai.WAGVID analysis artifacts.

This module does not recalculate analysis. It packages an already-produced, schema-valid public
analysis payload into immutable export revisions, negotiates public schema majors, issues scoped
evidence grants and creates idempotent notification envelopes.

Unreviewed output may be exported only as provisional. It can never be labelled as confirmed
fact. Raw model internals are rejected recursively from the public payload boundary.
"""

from __future__ import annotations

import hashlib
import json
import secrets
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Iterable, Mapping, Sequence


class KigaIntegrationError(ValueError):
    pass


class AnalysisReviewState(StrEnum):
    DRAFT = "draft"
    NEEDS_REVIEW = "needs-review"
    REVIEWED = "reviewed"


class DisclosureState(StrEnum):
    PROVISIONAL = "provisional"
    CONFIRMED = "confirmed"


class TrainingEligibility(StrEnum):
    UNKNOWN = "unknown"
    DENIED = "denied"
    ALLOWED = "allowed"


class EvidencePermission(StrEnum):
    VIEW = "view"
    DOWNLOAD = "download"


class BatchExportFormat(StrEnum):
    JSON = "json"
    PARQUET = "parquet"


_FORBIDDEN_PUBLIC_KEYS = frozenset(
    {
        "tensor",
        "tensors",
        "logit",
        "logits",
        "embedding",
        "embeddings",
        "feature_vector",
        "feature_vectors",
        "raw_model_output",
        "raw_model_outputs",
        "internal_class_index",
        "internal_class_indexes",
        "class_index",
        "class_indexes",
    }
)


@dataclass(frozen=True, order=True)
class PublicSchemaVersion:
    family: str
    major: int

    def __post_init__(self) -> None:
        if not self.family or self.major < 1:
            raise KigaIntegrationError("schema family and positive major version are required")

    @property
    def identifier(self) -> str:
        return f"{self.family}-v{self.major}"

    @classmethod
    def parse(cls, value: str) -> "PublicSchemaVersion":
        if not isinstance(value, str) or "-v" not in value:
            raise KigaIntegrationError(f"invalid public schema identifier: {value!r}")
        family, major_text = value.rsplit("-v", 1)
        try:
            major = int(major_text)
        except ValueError as error:
            raise KigaIntegrationError(f"invalid public schema major: {value!r}") from error
        return cls(family=family, major=major)


def negotiate_schema(
    *,
    offered: Iterable[PublicSchemaVersion],
    supported: Iterable[PublicSchemaVersion],
    family: str,
) -> PublicSchemaVersion:
    offered_set = {item for item in offered if item.family == family}
    supported_set = {item for item in supported if item.family == family}
    shared = offered_set & supported_set
    if not shared:
        raise KigaIntegrationError(f"no mutually supported schema for family {family}")
    return max(shared, key=lambda item: item.major)


@dataclass(frozen=True)
class StableKigaIdentity:
    competition_external_id: str
    routine_external_id: str
    athlete_external_id: str
    team_external_id: str | None = None

    def __post_init__(self) -> None:
        if (
            not self.competition_external_id
            or not self.routine_external_id
            or not self.athlete_external_id
        ):
            raise KigaIntegrationError("stable competition/routine/athlete IDs are required")

    @property
    def digest(self) -> str:
        return _stable_digest(asdict(self))


@dataclass(frozen=True)
class PublicAnalysisArtifact:
    schema: PublicSchemaVersion
    payload_json: str
    payload_digest: str
    review_state: AnalysisReviewState
    disclosure: DisclosureState

    def __post_init__(self) -> None:
        _require_sha256("analysis payload digest", self.payload_digest)
        try:
            payload = json.loads(self.payload_json)
        except json.JSONDecodeError as error:
            raise KigaIntegrationError("public analysis payload is not valid JSON") from error
        _ensure_public_payload_safe(payload)
        if _stable_digest(payload) != self.payload_digest:
            raise KigaIntegrationError("public analysis payload digest mismatch")
        if self.review_state is AnalysisReviewState.REVIEWED:
            if self.disclosure is not DisclosureState.CONFIRMED:
                raise KigaIntegrationError("reviewed analysis export must be confirmed")
        elif self.disclosure is not DisclosureState.PROVISIONAL:
            raise KigaIntegrationError(
                "draft/needs-review analysis cannot be exported as confirmed facts"
            )

    @property
    def payload(self) -> Mapping[str, Any]:
        value = json.loads(self.payload_json)
        if not isinstance(value, Mapping):
            raise KigaIntegrationError("analysis public payload root must be an object")
        return value


@dataclass(frozen=True)
class TrainingRightsAssertion:
    eligibility: TrainingEligibility
    rights_reference: str | None
    rights_digest: str | None

    def __post_init__(self) -> None:
        if self.eligibility is TrainingEligibility.ALLOWED:
            if not self.rights_reference or not self.rights_digest:
                raise KigaIntegrationError(
                    "training allowed requires explicit rights reference and digest"
                )
        if self.rights_digest is not None:
            _require_sha256("training rights digest", self.rights_digest)
        if self.eligibility is TrainingEligibility.UNKNOWN and (
            self.rights_reference is not None or self.rights_digest is not None
        ):
            raise KigaIntegrationError(
                "unknown training eligibility cannot imply a rights assertion"
            )


@dataclass(frozen=True)
class KigaAnalysisExportRevision:
    export_id: str
    identity: StableKigaIdentity
    analysis_id: str
    analysis_revision_id: str
    analysis_revision_digest: str
    artifact: PublicAnalysisArtifact
    rulepack_digest: str
    model_bundle_digest: str
    software_digest: str
    training_rights: TrainingRightsAssertion
    created_at: datetime
    supersedes_export_id: str | None = None

    def __post_init__(self) -> None:
        if not self.export_id or not self.analysis_id or not self.analysis_revision_id:
            raise KigaIntegrationError("export/analysis/revision identity is required")
        for label, value in (
            ("analysis revision digest", self.analysis_revision_digest),
            ("rulepack digest", self.rulepack_digest),
            ("model bundle digest", self.model_bundle_digest),
            ("software digest", self.software_digest),
        ):
            _require_sha256(label, value)
        if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
            raise KigaIntegrationError("export created_at must be timezone-aware")
        expected_export_id = export_revision_id(
            identity=self.identity,
            analysis_revision_digest=self.analysis_revision_digest,
            artifact=self.artifact,
        )
        if self.export_id != expected_export_id:
            raise KigaIntegrationError("export_id does not match immutable export content")

    @property
    def digest(self) -> str:
        return _stable_digest(
            {
                "export_id": self.export_id,
                "identity_digest": self.identity.digest,
                "analysis_id": self.analysis_id,
                "analysis_revision_id": self.analysis_revision_id,
                "analysis_revision_digest": self.analysis_revision_digest,
                "schema": self.artifact.schema.identifier,
                "payload_digest": self.artifact.payload_digest,
                "review_state": self.artifact.review_state.value,
                "disclosure": self.artifact.disclosure.value,
                "rulepack_digest": self.rulepack_digest,
                "model_bundle_digest": self.model_bundle_digest,
                "software_digest": self.software_digest,
                "training_rights": {
                    "eligibility": self.training_rights.eligibility.value,
                    "rights_reference": self.training_rights.rights_reference,
                    "rights_digest": self.training_rights.rights_digest,
                },
                "created_at": self.created_at.astimezone(UTC).isoformat(),
                "supersedes_export_id": self.supersedes_export_id,
            }
        )

    def public_envelope(self) -> dict[str, Any]:
        """Public KIGA response envelope. Stable IDs are primary; names are not keys."""
        return {
            "schema": "ai.wagvid.kiga-analysis-export.v1",
            "export_id": self.export_id,
            "competition_external_id": self.identity.competition_external_id,
            "routine_external_id": self.identity.routine_external_id,
            "athlete_external_id": self.identity.athlete_external_id,
            "team_external_id": self.identity.team_external_id,
            "analysis_id": self.analysis_id,
            "analysis_revision_id": self.analysis_revision_id,
            "analysis_revision_digest": self.analysis_revision_digest,
            "analysis_schema": self.artifact.schema.identifier,
            "analysis_payload_digest": self.artifact.payload_digest,
            "review_state": self.artifact.review_state.value,
            "disclosure": self.artifact.disclosure.value,
            "rulepack_digest": self.rulepack_digest,
            "model_bundle_digest": self.model_bundle_digest,
            "software_digest": self.software_digest,
            "training_eligibility": self.training_rights.eligibility.value,
            "created_at": self.created_at.astimezone(UTC).isoformat(),
            "supersedes_export_id": self.supersedes_export_id,
            "analysis": self.artifact.payload,
        }


def export_revision_id(
    *,
    identity: StableKigaIdentity,
    analysis_revision_digest: str,
    artifact: PublicAnalysisArtifact,
) -> str:
    _require_sha256("analysis revision digest", analysis_revision_digest)
    digest = _stable_digest(
        {
            "identity_digest": identity.digest,
            "analysis_revision_digest": analysis_revision_digest,
            "analysis_schema": artifact.schema.identifier,
            "payload_digest": artifact.payload_digest,
            "review_state": artifact.review_state.value,
            "disclosure": artifact.disclosure.value,
        }
    )
    return f"kiga-export:{digest[:32]}"


class KigaExportHistory:
    """Append-only, non-forking export history for one stable routine identity."""

    def __init__(self, revisions: Iterable[KigaAnalysisExportRevision] = ()) -> None:
        self._revisions: list[KigaAnalysisExportRevision] = []
        for revision in revisions:
            self.append(revision)

    def append(self, revision: KigaAnalysisExportRevision) -> None:
        if any(item.export_id == revision.export_id for item in self._revisions):
            existing = next(item for item in self._revisions if item.export_id == revision.export_id)
            if existing == revision:
                return
            raise KigaIntegrationError("export_id is immutable")
        if not self._revisions:
            if revision.supersedes_export_id is not None:
                raise KigaIntegrationError("first KIGA export cannot supersede another export")
            self._revisions.append(revision)
            return
        previous = self._revisions[-1]
        if revision.identity != previous.identity:
            raise KigaIntegrationError("KIGA export history cannot change stable routine identity")
        if revision.created_at <= previous.created_at:
            raise KigaIntegrationError("new KIGA export revision must be created later")
        if revision.supersedes_export_id != previous.export_id:
            raise KigaIntegrationError("new KIGA export must explicitly supersede current revision")
        self._revisions.append(revision)

    @property
    def revisions(self) -> tuple[KigaAnalysisExportRevision, ...]:
        return tuple(self._revisions)

    @property
    def current(self) -> KigaAnalysisExportRevision | None:
        return self._revisions[-1] if self._revisions else None


@dataclass(frozen=True)
class EvidenceGrantRecord:
    grant_id: str
    evidence_id: str
    evidence_digest: str
    organization_id: str
    subject_ref: str
    permissions: frozenset[EvidencePermission]
    token_digest: str
    issued_at: datetime
    expires_at: datetime
    revoked_at: datetime | None = None

    def __post_init__(self) -> None:
        if not self.grant_id or not self.evidence_id or not self.organization_id or not self.subject_ref:
            raise KigaIntegrationError("evidence grant identity/org/subject are required")
        _require_sha256("evidence digest", self.evidence_digest)
        _require_sha256("evidence grant token digest", self.token_digest)
        if not self.permissions:
            raise KigaIntegrationError("evidence grant requires at least one permission")
        if self.issued_at.tzinfo is None or self.issued_at.utcoffset() is None:
            raise KigaIntegrationError("evidence grant issued_at must be timezone-aware")
        if self.expires_at.tzinfo is None or self.expires_at.utcoffset() is None:
            raise KigaIntegrationError("evidence grant expires_at must be timezone-aware")
        if self.expires_at <= self.issued_at:
            raise KigaIntegrationError("evidence grant expiry must be after issuance")
        if self.revoked_at is not None:
            if self.revoked_at.tzinfo is None or self.revoked_at.utcoffset() is None:
                raise KigaIntegrationError("evidence grant revoked_at must be timezone-aware")
            if self.revoked_at < self.issued_at:
                raise KigaIntegrationError("evidence grant cannot be revoked before issuance")

    def authorizes(
        self,
        *,
        token: str,
        permission: EvidencePermission,
        now: datetime,
        organization_id: str,
        subject_ref: str,
    ) -> bool:
        if now.tzinfo is None or now.utcoffset() is None:
            raise KigaIntegrationError("evidence authorization time must be timezone-aware")
        if self.revoked_at is not None and now >= self.revoked_at:
            return False
        if now >= self.expires_at:
            return False
        if organization_id != self.organization_id or subject_ref != self.subject_ref:
            return False
        if permission not in self.permissions:
            return False
        return secrets.compare_digest(_token_digest(token), self.token_digest)


@dataclass(frozen=True)
class IssuedEvidenceGrant:
    token: str
    record: EvidenceGrantRecord


def issue_evidence_grant(
    *,
    evidence_id: str,
    evidence_digest: str,
    organization_id: str,
    subject_ref: str,
    permissions: Iterable[EvidencePermission],
    issued_at: datetime,
    expires_at: datetime,
) -> IssuedEvidenceGrant:
    permission_set = frozenset(permissions)
    token = secrets.token_urlsafe(32)
    token_digest = _token_digest(token)
    grant_seed = _stable_digest(
        {
            "evidence_id": evidence_id,
            "evidence_digest": evidence_digest,
            "organization_id": organization_id,
            "subject_ref": subject_ref,
            "permissions": sorted(item.value for item in permission_set),
            "token_digest": token_digest,
            "issued_at": issued_at.astimezone(UTC).isoformat(),
            "expires_at": expires_at.astimezone(UTC).isoformat(),
        }
    )
    record = EvidenceGrantRecord(
        grant_id=f"evidence-grant:{grant_seed[:32]}",
        evidence_id=evidence_id,
        evidence_digest=evidence_digest,
        organization_id=organization_id,
        subject_ref=subject_ref,
        permissions=permission_set,
        token_digest=token_digest,
        issued_at=issued_at,
        expires_at=expires_at,
    )
    return IssuedEvidenceGrant(token=token, record=record)


@dataclass(frozen=True)
class KigaNotification:
    notification_id: str
    event_type: str
    destination_ref: str
    export_id: str
    export_digest: str
    analysis_schema: str
    review_state: AnalysisReviewState
    disclosure: DisclosureState
    created_at: datetime

    def __post_init__(self) -> None:
        if not self.notification_id or not self.event_type or not self.destination_ref or not self.export_id:
            raise KigaIntegrationError("notification identity/type/destination/export are required")
        _require_sha256("KIGA export digest", self.export_digest)
        if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
            raise KigaIntegrationError("notification created_at must be timezone-aware")

    @property
    def idempotency_key(self) -> str:
        return _stable_digest(
            {
                "event_type": self.event_type,
                "destination_ref": self.destination_ref,
                "export_id": self.export_id,
                "export_digest": self.export_digest,
            }
        )

    def payload(self) -> dict[str, Any]:
        return {
            "schema": "ai.wagvid.kiga-notification.v1",
            "notification_id": self.notification_id,
            "idempotency_key": self.idempotency_key,
            "event_type": self.event_type,
            "destination_ref": self.destination_ref,
            "export_id": self.export_id,
            "export_digest": self.export_digest,
            "analysis_schema": self.analysis_schema,
            "review_state": self.review_state.value,
            "disclosure": self.disclosure.value,
            "created_at": self.created_at.astimezone(UTC).isoformat(),
        }


def make_notification(
    export: KigaAnalysisExportRevision,
    *,
    destination_ref: str,
    created_at: datetime,
    event_type: str = "analysis.export.ready",
) -> KigaNotification:
    seed = _stable_digest(
        {
            "event_type": event_type,
            "destination_ref": destination_ref,
            "export_id": export.export_id,
            "export_digest": export.digest,
        }
    )
    return KigaNotification(
        notification_id=f"kiga-notification:{seed[:32]}",
        event_type=event_type,
        destination_ref=destination_ref,
        export_id=export.export_id,
        export_digest=export.digest,
        analysis_schema=export.artifact.schema.identifier,
        review_state=export.artifact.review_state,
        disclosure=export.artifact.disclosure,
        created_at=created_at,
    )


@dataclass(frozen=True)
class KigaBatchExportManifest:
    batch_export_id: str
    schema: PublicSchemaVersion
    format: BatchExportFormat
    export_digests: tuple[str, ...]
    created_at: datetime

    def __post_init__(self) -> None:
        if not self.batch_export_id or not self.export_digests:
            raise KigaIntegrationError("batch export ID and at least one export digest are required")
        for digest in self.export_digests:
            _require_sha256("batch export member digest", digest)
        if len(self.export_digests) != len(set(self.export_digests)):
            raise KigaIntegrationError("batch export member digests must be unique")
        if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
            raise KigaIntegrationError("batch export created_at must be timezone-aware")


def build_batch_manifest(
    exports: Sequence[KigaAnalysisExportRevision],
    *,
    format: BatchExportFormat,
    created_at: datetime,
) -> KigaBatchExportManifest:
    if not exports:
        raise KigaIntegrationError("batch export requires at least one analysis export")
    schemas = {item.artifact.schema for item in exports}
    if len(schemas) != 1:
        raise KigaIntegrationError("batch export members must use one negotiated analysis schema")
    digests = tuple(sorted(item.digest for item in exports))
    seed = _stable_digest(
        {
            "schema": next(iter(schemas)).identifier,
            "format": format.value,
            "export_digests": list(digests),
        }
    )
    return KigaBatchExportManifest(
        batch_export_id=f"kiga-batch:{seed[:32]}",
        schema=next(iter(schemas)),
        format=format,
        export_digests=digests,
        created_at=created_at,
    )


def public_analysis_artifact(
    payload: Mapping[str, Any],
    *,
    schema: PublicSchemaVersion,
    review_state: AnalysisReviewState,
) -> PublicAnalysisArtifact:
    _ensure_public_payload_safe(payload)
    payload_json = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    disclosure = (
        DisclosureState.CONFIRMED
        if review_state is AnalysisReviewState.REVIEWED
        else DisclosureState.PROVISIONAL
    )
    return PublicAnalysisArtifact(
        schema=schema,
        payload_json=payload_json,
        payload_digest=_stable_digest(payload),
        review_state=review_state,
        disclosure=disclosure,
    )


def _ensure_public_payload_safe(value: Any, *, path: str = "$") -> None:
    if isinstance(value, Mapping):
        for raw_key, child in value.items():
            if not isinstance(raw_key, str):
                raise KigaIntegrationError(f"public payload key at {path} must be a string")
            normalized = raw_key.casefold().replace("-", "_")
            if normalized in _FORBIDDEN_PUBLIC_KEYS:
                raise KigaIntegrationError(
                    f"raw/internal model field is forbidden in public payload: {path}.{raw_key}"
                )
            _ensure_public_payload_safe(child, path=f"{path}.{raw_key}")
        return
    if isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            _ensure_public_payload_safe(child, path=f"{path}[{index}]")
        return
    if isinstance(value, (str, int, float, bool)) or value is None:
        return
    raise KigaIntegrationError(f"unsupported public payload value at {path}: {type(value).__name__}")


def _token_digest(token: str) -> str:
    if not isinstance(token, str) or not token:
        raise KigaIntegrationError("evidence grant token must be a non-empty string")
    return hashlib.sha256(token.encode()).hexdigest()


def _stable_digest(payload: Any) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


def _require_sha256(label: str, value: str) -> None:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise KigaIntegrationError(f"{label} must be lowercase SHA-256 hexadecimal")
