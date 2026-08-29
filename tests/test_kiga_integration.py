import json
from datetime import UTC, datetime, timedelta

import pytest

from ai_wagvid.kiga_export import (
    batch_bytes_digest,
    build_export_revision,
    build_public_analysis_artifact,
    canonical_batch_rows,
    parquet_rows_and_manifest,
    serialize_batch_json,
)
from ai_wagvid.kiga_integration import (
    AnalysisReviewState,
    BatchExportFormat,
    DisclosureState,
    EvidencePermission,
    KigaExportHistory,
    KigaIntegrationError,
    PublicSchemaVersion,
    StableKigaIdentity,
    TrainingEligibility,
    TrainingRightsAssertion,
    issue_evidence_grant,
    make_notification,
    negotiate_schema,
)

T0 = datetime(2026, 8, 17, 16, 0, tzinfo=UTC)
ANALYSIS_SCHEMA = PublicSchemaVersion("analysis", 1)


def analysis_payload(*, candidate_status: str = "accepted") -> dict:
    # Synthetic public contract fixture. The existing analysis-v1 serializer remains source of
    # truth; this adapter treats its output as an immutable public payload.
    return {
        "schema_version": "analysis-v1",
        "analysis_id": "analysis-1",
        "review_state": candidate_status,
        "apparatus": "BB",
        "rulepack_version": "fixture-rules@v1",
        "accepted_elements": [
            {
                "element_id": "fixture-element",
                "evidence_refs": ["evidence-1"],
            }
        ],
        "d_score": {"ledger_digest": "a" * 64, "resolved": True},
        "deductions": {"ledger_digest": "b" * 64, "unresolved": []},
        "provenance": {
            "model_digest": "c" * 64,
            "software_digest": "d" * 64,
        },
    }


def identity(routine: str = "routine-1") -> StableKigaIdentity:
    return StableKigaIdentity(
        competition_external_id="competition-1",
        routine_external_id=routine,
        athlete_external_id="athlete-1",
    )


def rights(eligibility: TrainingEligibility = TrainingEligibility.DENIED) -> TrainingRightsAssertion:
    return TrainingRightsAssertion(
        eligibility=eligibility,
        rights_reference="rights-1" if eligibility is not TrainingEligibility.UNKNOWN else None,
        rights_digest="e" * 64 if eligibility is not TrainingEligibility.UNKNOWN else None,
    )


def export_revision(
    *,
    routine: str = "routine-1",
    review_state: AnalysisReviewState = AnalysisReviewState.REVIEWED,
    revision_digest: str = "f" * 64,
    created_at: datetime = T0,
    supersedes: str | None = None,
):
    artifact = build_public_analysis_artifact(
        analysis_payload(),
        schema=ANALYSIS_SCHEMA,
        review_state=review_state,
    )
    return build_export_revision(
        identity=identity(routine),
        analysis_id="analysis-1",
        analysis_revision_id=f"revision-{revision_digest[0]}",
        analysis_revision_digest=revision_digest,
        artifact=artifact,
        rulepack_digest="1" * 64,
        model_bundle_digest="2" * 64,
        software_digest="3" * 64,
        training_rights=rights(),
        created_at=created_at,
        supersedes_export_id=supersedes,
    )


def test_schema_negotiation_selects_highest_mutually_supported_major():
    chosen = negotiate_schema(
        offered=(PublicSchemaVersion("analysis", 1), PublicSchemaVersion("analysis", 2)),
        supported=(PublicSchemaVersion("analysis", 1), PublicSchemaVersion("analysis", 3)),
        family="analysis",
    )
    assert chosen == PublicSchemaVersion("analysis", 1)

    with pytest.raises(KigaIntegrationError, match="no mutually supported schema"):
        negotiate_schema(
            offered=(PublicSchemaVersion("analysis", 2),),
            supported=(PublicSchemaVersion("analysis", 1),),
            family="analysis",
        )


def test_unreviewed_analysis_is_forced_provisional_not_confirmed():
    for state in (AnalysisReviewState.DRAFT, AnalysisReviewState.NEEDS_REVIEW):
        artifact = build_public_analysis_artifact(
            analysis_payload(candidate_status=state.value),
            schema=ANALYSIS_SCHEMA,
            review_state=state,
        )
        assert artifact.disclosure is DisclosureState.PROVISIONAL

    reviewed = build_public_analysis_artifact(
        analysis_payload(), schema=ANALYSIS_SCHEMA, review_state=AnalysisReviewState.REVIEWED
    )
    assert reviewed.disclosure is DisclosureState.CONFIRMED


def test_raw_model_internals_are_rejected_recursively_from_public_payload():
    forbidden_fields = (
        "tensor",
        "logits",
        "embedding",
        "feature_vector",
        "internal_class_index",
        "raw_model_output",
    )
    for field in forbidden_fields:
        payload = analysis_payload()
        payload["nested"] = {"deeper": {field: [0.1, 0.9]}}
        with pytest.raises(KigaIntegrationError, match="forbidden in public payload"):
            build_public_analysis_artifact(
                payload,
                schema=ANALYSIS_SCHEMA,
                review_state=AnalysisReviewState.REVIEWED,
            )


def test_nonfinite_numbers_are_rejected_before_public_json_is_created():
    for value in (float("nan"), float("inf"), float("-inf")):
        payload = analysis_payload()
        payload["bad_metric"] = value
        with pytest.raises(KigaIntegrationError, match="non-finite number"):
            build_public_analysis_artifact(
                payload,
                schema=ANALYSIS_SCHEMA,
                review_state=AnalysisReviewState.REVIEWED,
            )


def test_same_analysis_revision_and_payload_has_stable_export_id_on_retry():
    first = export_revision(created_at=T0)
    retry = export_revision(created_at=T0 + timedelta(minutes=1))
    assert first.export_id == retry.export_id
    assert first.artifact.payload_digest == retry.artifact.payload_digest
    # The immutable content ID is stable; created_at remains control-plane attempt metadata.
    assert first.created_at != retry.created_at


def test_new_analysis_revision_creates_new_export_id_and_history_requires_supersession():
    first = export_revision(revision_digest="f" * 64, created_at=T0)
    second = export_revision(
        revision_digest="a" * 64,
        created_at=T0 + timedelta(minutes=1),
        supersedes=first.export_id,
    )
    assert first.export_id != second.export_id
    history = KigaExportHistory((first, second))
    assert history.current == second

    third_without_supersession = export_revision(
        revision_digest="b" * 64,
        created_at=T0 + timedelta(minutes=2),
    )
    with pytest.raises(KigaIntegrationError, match="explicitly supersede"):
        history.append(third_without_supersession)


def test_public_envelope_uses_stable_ids_as_primary_mapping_and_preserves_disclosure():
    export = export_revision()
    envelope = export.public_envelope()
    assert envelope["competition_external_id"] == "competition-1"
    assert envelope["routine_external_id"] == "routine-1"
    assert envelope["athlete_external_id"] == "athlete-1"
    assert envelope["review_state"] == "reviewed"
    assert envelope["disclosure"] == "confirmed"
    assert "athlete_name" not in envelope
    assert envelope["analysis_payload_digest"] == export.artifact.payload_digest


def test_training_allowed_never_follows_from_analysis_or_download_access():
    denied = rights(TrainingEligibility.DENIED)
    assert denied.eligibility is TrainingEligibility.DENIED

    unknown = rights(TrainingEligibility.UNKNOWN)
    assert unknown.rights_reference is None
    assert unknown.rights_digest is None

    with pytest.raises(KigaIntegrationError, match="explicit rights reference"):
        TrainingRightsAssertion(
            eligibility=TrainingEligibility.ALLOWED,
            rights_reference=None,
            rights_digest=None,
        )

    allowed = rights(TrainingEligibility.ALLOWED)
    assert allowed.rights_reference == "rights-1"
    assert allowed.rights_digest == "e" * 64


def test_evidence_grant_stores_only_token_digest_and_enforces_scope_expiry_subject_and_permission():
    issued = issue_evidence_grant(
        evidence_id="evidence-1",
        evidence_digest="4" * 64,
        organization_id="org-1",
        subject_ref="kiga-user-1",
        permissions=(EvidencePermission.VIEW,),
        issued_at=T0,
        expires_at=T0 + timedelta(minutes=10),
    )
    assert issued.token
    assert issued.token not in str(issued.record)
    assert issued.record.token_digest != issued.token
    assert issued.record.authorizes(
        token=issued.token,
        permission=EvidencePermission.VIEW,
        now=T0 + timedelta(minutes=1),
        organization_id="org-1",
        subject_ref="kiga-user-1",
    )
    assert not issued.record.authorizes(
        token=issued.token,
        permission=EvidencePermission.DOWNLOAD,
        now=T0 + timedelta(minutes=1),
        organization_id="org-1",
        subject_ref="kiga-user-1",
    )
    assert not issued.record.authorizes(
        token=issued.token,
        permission=EvidencePermission.VIEW,
        now=T0 + timedelta(minutes=11),
        organization_id="org-1",
        subject_ref="kiga-user-1",
    )
    assert not issued.record.authorizes(
        token=issued.token,
        permission=EvidencePermission.VIEW,
        now=T0 + timedelta(minutes=1),
        organization_id="org-1",
        subject_ref="other-user",
    )
    assert not issued.record.authorizes(
        token="wrong-token",
        permission=EvidencePermission.VIEW,
        now=T0 + timedelta(minutes=1),
        organization_id="org-1",
        subject_ref="kiga-user-1",
    )


def test_notification_is_idempotent_for_same_export_and_destination():
    export = export_revision()
    first = make_notification(
        export,
        destination_ref="kiga:event-bus",
        created_at=T0 + timedelta(minutes=1),
    )
    retry = make_notification(
        export,
        destination_ref="kiga:event-bus",
        created_at=T0 + timedelta(minutes=2),
    )
    assert first.notification_id == retry.notification_id
    assert first.idempotency_key == retry.idempotency_key
    assert first.payload()["export_digest"] == export.digest


def test_json_and_parquet_paths_share_same_canonical_rows_and_member_digests():
    first = export_revision(routine="routine-1", revision_digest="f" * 64)
    second = export_revision(routine="routine-2", revision_digest="a" * 64)
    rows = canonical_batch_rows((second, first))
    assert [row["routine_external_id"] for row in rows] == ["routine-1", "routine-2"]

    json_manifest, payload = serialize_batch_json(
        (second, first), created_at=T0 + timedelta(minutes=5)
    )
    parquet_manifest, parquet_rows = parquet_rows_and_manifest(
        (second, first), created_at=T0 + timedelta(minutes=5)
    )
    assert json_manifest.format is BatchExportFormat.JSON
    assert parquet_manifest.format is BatchExportFormat.PARQUET
    assert json_manifest.export_digests == parquet_manifest.export_digests
    assert tuple(rows) == parquet_rows
    decoded = json.loads(payload)
    assert decoded["rows"] == list(rows)
    assert len(batch_bytes_digest(payload)) == 64


def test_batch_export_rejects_mixed_analysis_schema_versions():
    first = export_revision(routine="routine-1")
    artifact_v2 = build_public_analysis_artifact(
        analysis_payload(),
        schema=PublicSchemaVersion("analysis", 2),
        review_state=AnalysisReviewState.REVIEWED,
    )
    second = build_export_revision(
        identity=identity("routine-2"),
        analysis_id="analysis-2",
        analysis_revision_id="revision-2",
        analysis_revision_digest="9" * 64,
        artifact=artifact_v2,
        rulepack_digest="1" * 64,
        model_bundle_digest="2" * 64,
        software_digest="3" * 64,
        training_rights=rights(),
        created_at=T0,
    )
    with pytest.raises(KigaIntegrationError, match="one negotiated analysis schema"):
        serialize_batch_json((first, second), created_at=T0 + timedelta(minutes=1))
