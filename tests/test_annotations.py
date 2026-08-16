from dataclasses import replace
from datetime import UTC, datetime

import pytest

from ai_wagvid.annotations import (
    AnnotationKind,
    AnnotationRevision,
    ReviewState,
    adjudicate,
    export_annotation_label,
    revise_annotation,
    validate_revision_chain,
)
from ai_wagvid.evidence import EvidenceReference


def evidence():
    return EvidenceReference(
        "ev", "a" * 64, "b" * 64, "cam", 1, 3, 0.04, 0.12,
        None, None, "review-ui", "1",
    )


def first(state=ReviewState.SUBMITTED):
    return AnnotationRevision(
        "ann", 1, AnnotationKind.LANDING, evidence(), {"state": "possible-contact"},
        state, "reviewer-1", datetime(2026, 1, 1, tzinfo=UTC), comment="initial",
    )


def test_revision_chain_is_append_only_and_digest_linked():
    one = first()
    two = revise_annotation(
        one, payload={"state": "contact"}, state=ReviewState.ACCEPTED,
        author_id="reviewer-2", created_at=datetime(2026, 1, 2, tzinfo=UTC),
        comment="frame inspection",
    )
    validate_revision_chain((one, two))
    assert two.parent_digest == one.digest
    assert two.evidence == one.evidence


def test_tampered_revision_chain_is_rejected():
    one = first()
    two = revise_annotation(
        one, payload={"state": "contact"}, state=ReviewState.SUBMITTED,
        author_id="reviewer-2", created_at=datetime(2026, 1, 2, tzinfo=UTC), comment="review",
    )
    with pytest.raises(ValueError, match="parent digest"):
        validate_revision_chain((one, replace(two, parent_digest="0" * 64)))


def test_adjudication_requires_two_reviewers_and_known_revision():
    one = first()
    with pytest.raises(ValueError, match="two reviewers"):
        adjudicate(
            (one,), selected_revision_digest=one.digest, decision="accept",
            adjudicator_id="judge", created_at=datetime.now(UTC), rationale="checked",
        )
    two = revise_annotation(
        one, payload={"state": "flight"}, state=ReviewState.SUBMITTED,
        author_id="reviewer-2", created_at=datetime.now(UTC), comment="different view",
    )
    result = adjudicate(
        (one, two), selected_revision_digest=two.digest, decision="accept",
        adjudicator_id="judge", created_at=datetime.now(UTC), rationale="camera two resolves it",
    )
    assert result.selected_revision_digest == two.digest


def test_only_accepted_revision_can_be_exported_without_reviewer_identity():
    with pytest.raises(ValueError, match="accepted"):
        export_annotation_label(first(), athlete_group_id="a", event_group_id="e", routine_group_id="r")
    label = export_annotation_label(
        first(ReviewState.ACCEPTED), athlete_group_id="athlete-group",
        event_group_id="event-group", routine_group_id="routine-group",
    )
    assert "author_id" not in label
    assert label["groups"]["athlete"] == "athlete-group"
