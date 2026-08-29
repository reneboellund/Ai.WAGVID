from datetime import UTC, datetime
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

from ai_wagvid.data_governance import (
    DatasetRightsRecord,
    DecisionSemanticLayer,
    DecisionState,
    EvidenceKind,
    EvidenceProvenanceRef,
    GovernedPermission,
    ProductionDecisionProvenance,
)
from ai_wagvid.governance_exports import (
    dataset_rights_payload,
    production_decision_payload,
)
from wagvid_rules.validation import load_schema

ROOT = Path(__file__).parents[1]
RIGHTS_SCHEMA = load_schema(ROOT / "schemas" / "dataset-rights-v1.schema.json")
DECISION_SCHEMA = load_schema(
    ROOT / "schemas" / "production-decision-provenance-v1.schema.json"
)
T0 = datetime(2026, 8, 17, 18, 30, tzinfo=UTC)


def rights_record():
    return DatasetRightsRecord(
        record_id="rights-1",
        source_reference="dataset-source-1",
        source_digest="1" * 64,
        rights_reference="licence-consent-1",
        rights_digest="2" * 64,
        permissions=frozenset(
            {
                GovernedPermission.VIEW,
                GovernedPermission.ANALYZE,
                GovernedPermission.RETAIN,
            }
        ),
        retention_class="competition-review",
        valid_from=T0,
    )


def production_decision():
    source = EvidenceProvenanceRef(
        evidence_id="source-1",
        evidence_digest="3" * 64,
        canonical_source_sha256="4" * 64,
        kind=EvidenceKind.SOURCE_INTERVAL,
        represented_as_original=True,
    )
    overlay = EvidenceProvenanceRef(
        evidence_id="overlay-1",
        evidence_digest="5" * 64,
        canonical_source_sha256="4" * 64,
        kind=EvidenceKind.OVERLAY,
        represented_as_original=False,
    )
    return ProductionDecisionProvenance(
        decision_id="decision-1",
        organization_id="org-1",
        object_ref="analysis-1:deduction-1",
        semantic_layer=DecisionSemanticLayer.JUDGING_INTERPRETATION,
        state=DecisionState.CONFIRMED,
        material=True,
        authority_ref="qualified-reviewer:1",
        evidence=(source, overlay),
        rulepack_digest="6" * 64,
        model_bundle_digest="7" * 64,
        software_digest="8" * 64,
        config_digest="9" * 64,
        calibration_digest="a" * 64,
        created_at=T0,
    )


def test_dataset_rights_audit_payload_validates_schema():
    payload = dataset_rights_payload(rights_record())
    errors = list(
        Draft202012Validator(
            RIGHTS_SCHEMA,
            format_checker=FormatChecker(),
        ).iter_errors(payload)
    )
    assert errors == []
    assert "train" not in payload["permissions"]


def test_production_decision_audit_payload_validates_schema():
    payload = production_decision_payload(production_decision())
    errors = list(
        Draft202012Validator(
            DECISION_SCHEMA,
            format_checker=FormatChecker(),
        ).iter_errors(payload)
    )
    assert errors == []
    assert payload["evidence"][0]["kind"] == "source-interval"
    assert payload["evidence"][1]["kind"] == "overlay"


def test_schema_rejects_overlay_falsely_marked_as_original():
    payload = production_decision_payload(production_decision())
    payload["evidence"][1]["represented_as_original"] = True
    assert list(Draft202012Validator(DECISION_SCHEMA).iter_errors(payload))


def test_schema_rejects_confirmed_material_decision_without_source_interval():
    payload = production_decision_payload(production_decision())
    payload["evidence"] = [payload["evidence"][1]]
    assert list(Draft202012Validator(DECISION_SCHEMA).iter_errors(payload))
