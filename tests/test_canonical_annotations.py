from datetime import UTC, datetime, timedelta
from fractions import Fraction

import pytest

from ai_wagvid.annotations import (
    AnnotationKind,
    CanonicalAnnotationRevision,
    ReviewState,
    export_canonical_annotation_label,
    revise_canonical_annotation,
    validate_bulk_review_transition,
    validate_canonical_revision_chain,
)
from ai_wagvid.evidence import CanonicalEvidenceReference, canonical_interval_from_timeline
from ai_wagvid.media_timeline import FrameTimestamp, build_timeline


T0 = datetime(2026, 8, 17, 10, 30, tzinfo=UTC)


def evidence() -> CanonicalEvidenceReference:
    timeline = build_timeline(
        source_sha256="a" * 64,
        time_base=Fraction(1, 1000),
        frames=tuple(
            FrameTimestamp(index, index * 40, index * 40, index * 40, 40, index == 0)
            for index in range(5)
        ),
    )
    interval = canonical_interval_from_timeline(
        timeline,
        camera_id="cam-a",
        start_frame_index=1,
        end_frame_index=3,
    )
    return CanonicalEvidenceReference(
        evidence_id="ev-annotation",
        intervals=(interval,),
        created_at=T0,
        purpose="element-review",
        producer="model",
        producer_version="bundle-1",
    )


def revision(
    *,
    annotation_id: str = "ann-1",
    kind: AnnotationKind = AnnotationKind.ELEMENT_CANDIDATE,
    state: ReviewState = ReviewState.SUBMITTED,
    created_at: datetime = T0 + timedelta(minutes=1),
) -> CanonicalAnnotationRevision:
    return CanonicalAnnotationRevision(
        annotation_id=annotation_id,
        revision=1,
        kind=kind,
        evidence=evidence(),
        payload={"candidate": "bb-element-x", "confidence": 0.71},
        state=state,
        author_id="reviewer-a",
        created_at=created_at,
        comment="Needs second-camera review",
        model_provenance={"model_bundle": "bundle-1", "artifact_digest": "b" * 64},
    )


def test_canonical_revision_chain_preserves_evidence_and_parent_digest():
    first = revision()
    second = revise_canonical_annotation(
        first,
        payload={"candidate": "bb-element-y", "confidence": 0.94},
        state=ReviewState.ACCEPTED,
        author_id="reviewer-b",
        created_at=T0 + timedelta(minutes=2),
        comment="Second camera resolves body shape",
    )

    validate_canonical_revision_chain((first, second))
    assert second.parent_digest == first.digest
    assert second.evidence.digest == first.evidence.digest
    assert second.model_provenance == first.model_provenance


def test_canonical_revision_must_move_forward_in_time():
    first = revision()
    with pytest.raises(ValueError, match="created later"):
        revise_canonical_annotation(
            first,
            payload={"candidate": "bb-element-y"},
            state=ReviewState.ACCEPTED,
            author_id="reviewer-b",
            created_at=first.created_at,
            comment="Invalid same-time revision",
        )


def test_revision_chain_rejects_silent_evidence_replacement():
    first = revision()
    other_evidence = CanonicalEvidenceReference(
        evidence_id="ev-other",
        intervals=evidence().intervals,
        created_at=T0,
        purpose="other",
        producer="model",
        producer_version="bundle-1",
    )
    second = CanonicalAnnotationRevision(
        annotation_id=first.annotation_id,
        revision=2,
        kind=first.kind,
        evidence=other_evidence,
        payload={"candidate": "bb-element-y"},
        state=ReviewState.ACCEPTED,
        author_id="reviewer-b",
        created_at=T0 + timedelta(minutes=2),
        parent_digest=first.digest,
        comment="Changed evidence",
        model_provenance=first.model_provenance,
    )
    with pytest.raises(ValueError, match="cannot silently replace its evidence"):
        validate_canonical_revision_chain((first, second))


def test_material_scoring_decisions_cannot_be_bulk_accepted():
    one = revision(annotation_id="ann-1", kind=AnnotationKind.ELEMENT_CANDIDATE)
    two = revision(annotation_id="ann-2", kind=AnnotationKind.DEDUCTION_CANDIDATE)
    with pytest.raises(ValueError, match="cannot be bulk accepted"):
        validate_bulk_review_transition((one, two), target_state=ReviewState.ACCEPTED)

    routine = revision(annotation_id="ann-routine", kind=AnnotationKind.ROUTINE_INTERVAL)
    phase = revision(annotation_id="ann-phase", kind=AnnotationKind.PHASE)
    validate_bulk_review_transition((routine, phase), target_state=ReviewState.ACCEPTED)


def test_training_label_export_contains_exact_canonical_intervals_and_group_keys():
    accepted = revision(state=ReviewState.ACCEPTED)
    payload = export_canonical_annotation_label(
        accepted,
        athlete_group_id="athlete-pseudo-1",
        event_group_id="event-1",
        routine_group_id="routine-1",
    )
    assert payload["schema"] == "ai.wagvid.annotation-label.v2"
    assert payload["evidence_digest"] == accepted.evidence.digest
    assert payload["intervals"][0]["start_timestamp_ticks"] == 40
    assert payload["intervals"][0]["end_timestamp_ticks"] == 120
    assert payload["intervals"][0]["time_base"] == [1, 1000]
    assert payload["groups"]["athlete"] == "athlete-pseudo-1"
    assert "name" not in payload["groups"]


def test_unreviewed_annotation_cannot_be_exported_as_training_truth():
    with pytest.raises(ValueError, match="only accepted"):
        export_canonical_annotation_label(
            revision(state=ReviewState.SUBMITTED),
            athlete_group_id="athlete-1",
            event_group_id="event-1",
            routine_group_id="routine-1",
        )
