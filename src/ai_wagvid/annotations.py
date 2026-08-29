"""Append-only annotation revisions and reviewer adjudication contracts."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from .evidence import CanonicalEvidenceReference, EvidenceReference


class AnnotationKind(StrEnum):
    ROUTINE_INTERVAL = "routine-interval"
    PHASE = "phase"
    ELEMENT_CANDIDATE = "element-candidate"
    CONTACT = "contact"
    RELEASE = "release"
    LANDING = "landing"
    DEDUCTION_CANDIDATE = "deduction-candidate"


class ReviewState(StrEnum):
    DRAFT = "draft"
    SUBMITTED = "submitted"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"


@dataclass(frozen=True)
class AnnotationRevision:
    annotation_id: str
    revision: int
    kind: AnnotationKind
    evidence: EvidenceReference
    payload: dict[str, Any]
    state: ReviewState
    author_id: str
    created_at: datetime
    parent_digest: str | None = None
    comment: str = ""
    model_provenance: dict[str, str] | None = None

    def __post_init__(self) -> None:
        if not self.annotation_id or self.revision < 1 or not self.author_id:
            raise ValueError("annotation identity, revision and author are required")
        if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
            raise ValueError("annotation timestamp must be timezone-aware")
        if self.revision == 1 and self.parent_digest is not None:
            raise ValueError("first annotation revision cannot have a parent")
        if self.revision > 1 and not self.parent_digest:
            raise ValueError("later annotation revisions require parent digest")
        if not self.payload:
            raise ValueError("annotation payload cannot be empty")

    @property
    def digest(self) -> str:
        value = asdict(self)
        value["kind"] = self.kind.value
        value["state"] = self.state.value
        value["created_at"] = self.created_at.isoformat()
        encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(encoded).hexdigest()


def revise_annotation(
    previous: AnnotationRevision, *, payload: dict[str, Any], state: ReviewState,
    author_id: str, created_at: datetime, comment: str,
) -> AnnotationRevision:
    if previous.state is ReviewState.SUPERSEDED:
        raise ValueError("cannot revise an already superseded revision")
    return AnnotationRevision(
        previous.annotation_id, previous.revision + 1, previous.kind, previous.evidence,
        payload, state, author_id, created_at, previous.digest, comment,
        previous.model_provenance,
    )


def validate_revision_chain(revisions: tuple[AnnotationRevision, ...]) -> None:
    if not revisions:
        raise ValueError("annotation history cannot be empty")
    identity = revisions[0].annotation_id
    for index, revision in enumerate(revisions):
        if revision.annotation_id != identity or revision.revision != index + 1:
            raise ValueError("annotation revisions are not contiguous")
        if index and revision.parent_digest != revisions[index - 1].digest:
            raise ValueError("annotation parent digest mismatch")


@dataclass(frozen=True)
class Adjudication:
    annotation_id: str
    selected_revision_digest: str | None
    decision: str
    adjudicator_id: str
    created_at: datetime
    rationale: str

    def __post_init__(self) -> None:
        if self.decision not in {"accept", "reject", "inconclusive"}:
            raise ValueError("invalid adjudication decision")
        if self.decision == "accept" and not self.selected_revision_digest:
            raise ValueError("accepted adjudication requires selected revision")
        if not self.adjudicator_id or not self.rationale:
            raise ValueError("adjudicator and rationale are required")


def adjudicate(
    revisions: tuple[AnnotationRevision, ...], *, selected_revision_digest: str | None,
    decision: str, adjudicator_id: str, created_at: datetime, rationale: str,
) -> Adjudication:
    validate_revision_chain(revisions)
    authors = {revision.author_id for revision in revisions}
    if len(authors) < 2:
        raise ValueError("adjudication requires revisions from at least two reviewers")
    if selected_revision_digest and selected_revision_digest not in {
        revision.digest for revision in revisions
    }:
        raise ValueError("selected revision is not in annotation history")
    return Adjudication(
        revisions[0].annotation_id, selected_revision_digest, decision,
        adjudicator_id, created_at, rationale,
    )


def export_annotation_label(
    revision: AnnotationRevision, *, athlete_group_id: str,
    event_group_id: str, routine_group_id: str,
) -> dict[str, Any]:
    if revision.state is not ReviewState.ACCEPTED:
        raise ValueError("only accepted annotation revisions may become training labels")
    return {
        "schema": "ai.wagvid.annotation-label.v1",
        "annotation_id": revision.annotation_id,
        "revision_digest": revision.digest,
        "kind": revision.kind.value,
        "evidence_digest": revision.evidence.digest,
        "source_sha256": revision.evidence.source_sha256,
        "camera_id": revision.evidence.camera_id,
        "start_timestamp_s": revision.evidence.start_timestamp_s,
        "end_timestamp_s": revision.evidence.end_timestamp_s,
        "payload": revision.payload,
        "groups": {
            "athlete": athlete_group_id,
            "event": event_group_id,
            "routine": routine_group_id,
        },
    }


# ---------------------------------------------------------------------------
# Canonical annotation v2. Existing v1 classes above remain digest-compatible.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CanonicalAnnotationRevision:
    annotation_id: str
    revision: int
    kind: AnnotationKind
    evidence: CanonicalEvidenceReference
    payload: dict[str, Any]
    state: ReviewState
    author_id: str
    created_at: datetime
    parent_digest: str | None = None
    comment: str = ""
    model_provenance: dict[str, str] | None = None

    def __post_init__(self) -> None:
        if not self.annotation_id or self.revision < 1 or not self.author_id:
            raise ValueError("canonical annotation identity, revision and author are required")
        if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
            raise ValueError("canonical annotation timestamp must be timezone-aware")
        if self.revision == 1 and self.parent_digest is not None:
            raise ValueError("first canonical annotation revision cannot have a parent")
        if self.revision > 1 and not self.parent_digest:
            raise ValueError("later canonical annotation revisions require parent digest")
        if not self.payload:
            raise ValueError("canonical annotation payload cannot be empty")
        if self.model_provenance is not None and not all(
            str(key).strip() and str(value).strip() for key, value in self.model_provenance.items()
        ):
            raise ValueError("model provenance keys and values cannot be empty")

    @property
    def digest(self) -> str:
        payload = {
            "schema": "ai.wagvid.annotation-revision.v2",
            "annotation_id": self.annotation_id,
            "revision": self.revision,
            "kind": self.kind.value,
            "evidence_digest": self.evidence.digest,
            "payload": self.payload,
            "state": self.state.value,
            "author_id": self.author_id,
            "created_at": self.created_at.astimezone(UTC).isoformat(),
            "parent_digest": self.parent_digest,
            "comment": self.comment,
            "model_provenance": self.model_provenance,
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(encoded).hexdigest()


def revise_canonical_annotation(
    previous: CanonicalAnnotationRevision,
    *,
    payload: dict[str, Any],
    state: ReviewState,
    author_id: str,
    created_at: datetime,
    comment: str,
) -> CanonicalAnnotationRevision:
    if previous.state is ReviewState.SUPERSEDED:
        raise ValueError("cannot revise an already superseded canonical revision")
    if created_at <= previous.created_at:
        raise ValueError("canonical annotation revision must be created later than its parent")
    return CanonicalAnnotationRevision(
        annotation_id=previous.annotation_id,
        revision=previous.revision + 1,
        kind=previous.kind,
        evidence=previous.evidence,
        payload=payload,
        state=state,
        author_id=author_id,
        created_at=created_at,
        parent_digest=previous.digest,
        comment=comment,
        model_provenance=previous.model_provenance,
    )


def validate_canonical_revision_chain(
    revisions: tuple[CanonicalAnnotationRevision, ...],
) -> None:
    if not revisions:
        raise ValueError("canonical annotation history cannot be empty")
    identity = revisions[0].annotation_id
    evidence_digest = revisions[0].evidence.digest
    for index, revision in enumerate(revisions):
        if revision.annotation_id != identity or revision.revision != index + 1:
            raise ValueError("canonical annotation revisions are not contiguous")
        if revision.evidence.digest != evidence_digest:
            raise ValueError("canonical annotation revision cannot silently replace its evidence")
        if index:
            if revision.parent_digest != revisions[index - 1].digest:
                raise ValueError("canonical annotation parent digest mismatch")
            if revision.created_at <= revisions[index - 1].created_at:
                raise ValueError("canonical annotation timestamps are not strictly increasing")


def validate_bulk_review_transition(
    revisions: tuple[CanonicalAnnotationRevision, ...],
    *,
    target_state: ReviewState,
) -> None:
    """Block bulk acceptance of material scoring/identity decisions.

    Bulk workflow may still submit/reject administrative annotations, but element identity
    and deduction decisions require an individual attributable review action.
    """
    if target_state is not ReviewState.ACCEPTED or len(revisions) <= 1:
        return
    material = {
        AnnotationKind.ELEMENT_CANDIDATE,
        AnnotationKind.DEDUCTION_CANDIDATE,
    }
    if any(revision.kind in material for revision in revisions):
        raise ValueError("material element/deduction decisions cannot be bulk accepted")


def export_canonical_annotation_label(
    revision: CanonicalAnnotationRevision,
    *,
    athlete_group_id: str,
    event_group_id: str,
    routine_group_id: str,
) -> dict[str, Any]:
    if revision.state is not ReviewState.ACCEPTED:
        raise ValueError("only accepted canonical annotations may become training labels")
    if not athlete_group_id or not event_group_id or not routine_group_id:
        raise ValueError("stable leakage-protection group identifiers are required")
    return {
        "schema": "ai.wagvid.annotation-label.v2",
        "annotation_id": revision.annotation_id,
        "revision_digest": revision.digest,
        "kind": revision.kind.value,
        "evidence_digest": revision.evidence.digest,
        "evidence_source_digest": revision.evidence.source_digest,
        "intervals": [
            {
                "source_sha256": interval.source_media_sha256,
                "timeline_digest": interval.timeline_digest,
                "stream_index": interval.stream_index,
                "camera_id": interval.camera_id,
                "start_frame_index": interval.start_frame_index,
                "end_frame_index": interval.end_frame_index,
                "start_timestamp_ticks": interval.start_timestamp_ticks,
                "end_timestamp_ticks": interval.end_timestamp_ticks,
                "time_base": [interval.time_base_numerator, interval.time_base_denominator],
                "calibration": asdict(interval.calibration),
            }
            for interval in revision.evidence.intervals
        ],
        "payload": revision.payload,
        "model_provenance": revision.model_provenance,
        "groups": {
            "athlete": athlete_group_id,
            "event": event_group_id,
            "routine": routine_group_id,
        },
    }
