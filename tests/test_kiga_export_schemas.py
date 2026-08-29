from datetime import UTC, datetime
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

from ai_wagvid.kiga_export import build_export_revision, build_public_analysis_artifact
from ai_wagvid.kiga_integration import (
    AnalysisReviewState,
    PublicSchemaVersion,
    StableKigaIdentity,
    TrainingEligibility,
    TrainingRightsAssertion,
    make_notification,
)
from wagvid_rules.validation import load_schema

ROOT = Path(__file__).parents[1]
EXPORT_SCHEMA = load_schema(ROOT / "schemas" / "kiga-analysis-export-v1.schema.json")
NOTIFICATION_SCHEMA = load_schema(ROOT / "schemas" / "kiga-notification-v1.schema.json")
T0 = datetime(2026, 8, 17, 16, 30, tzinfo=UTC)


def make_export(review_state: AnalysisReviewState = AnalysisReviewState.REVIEWED):
    artifact = build_public_analysis_artifact(
        {
            "schema_version": "analysis-v1",
            "analysis_id": "analysis-1",
            "apparatus": "BB",
            "review_state": review_state.value,
            "evidence_refs": ["evidence-1"],
            "provenance": {"model_digest": "a" * 64},
        },
        schema=PublicSchemaVersion("analysis", 1),
        review_state=review_state,
    )
    identity = StableKigaIdentity("competition-1", "routine-1", "athlete-1")
    return build_export_revision(
        identity=identity,
        analysis_id="analysis-1",
        analysis_revision_id="revision-1",
        analysis_revision_digest="b" * 64,
        artifact=artifact,
        rulepack_digest="c" * 64,
        model_bundle_digest="d" * 64,
        software_digest="e" * 64,
        training_rights=TrainingRightsAssertion(
            eligibility=TrainingEligibility.DENIED,
            rights_reference="rights-1",
            rights_digest="f" * 64,
        ),
        created_at=T0,
    )


def test_reviewed_export_envelope_validates_against_public_schema():
    export = make_export()
    errors = list(
        Draft202012Validator(
            EXPORT_SCHEMA,
            format_checker=FormatChecker(),
        ).iter_errors(export.public_envelope())
    )
    assert errors == []


def test_provisional_export_envelope_validates_and_is_not_confirmed():
    export = make_export(AnalysisReviewState.NEEDS_REVIEW)
    payload = export.public_envelope()
    assert payload["disclosure"] == "provisional"
    errors = list(Draft202012Validator(EXPORT_SCHEMA).iter_errors(payload))
    assert errors == []


def test_notification_payload_validates_against_public_schema():
    export = make_export()
    notification = make_notification(
        export,
        destination_ref="kiga:event-channel",
        created_at=T0,
    )
    errors = list(
        Draft202012Validator(
            NOTIFICATION_SCHEMA,
            format_checker=FormatChecker(),
        ).iter_errors(notification.payload())
    )
    assert errors == []


def test_schemas_reject_false_confirmed_disclosure_on_unreviewed_export():
    export = make_export(AnalysisReviewState.NEEDS_REVIEW)
    payload = export.public_envelope()
    payload["disclosure"] = "confirmed"
    assert list(Draft202012Validator(EXPORT_SCHEMA).iter_errors(payload))

    notification = make_notification(
        export,
        destination_ref="kiga:event-channel",
        created_at=T0,
    ).payload()
    notification["disclosure"] = "confirmed"
    assert list(Draft202012Validator(NOTIFICATION_SCHEMA).iter_errors(notification))
