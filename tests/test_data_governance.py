from datetime import UTC, datetime, timedelta

import pytest

from ai_wagvid.data_governance import (
    AuthorizedConfigChange,
    ConfigChangeLedger,
    DataGovernanceError,
    DatasetRightsRecord,
    DecisionSemanticLayer,
    DecisionState,
    DeletionDisposition,
    DeletionRequest,
    EvidenceKind,
    EvidenceProvenanceRef,
    FrozenConfigSnapshot,
    GovernedPermission,
    ProductionDecisionLedger,
    ProductionDecisionProvenance,
    RetentionRecord,
    RightsLifecycle,
    evaluate_deletion,
    freeze_configuration,
    pseudonymous_group_id,
)


T0 = datetime(2026, 8, 17, 18, 0, tzinfo=UTC)


def rights(*, permissions=None, lifecycle=RightsLifecycle.ACTIVE, valid_until=None, revoked_at=None):
    return DatasetRightsRecord(
        record_id="rights-1",
        source_reference="source-contract-1",
        source_digest="1" * 64,
        rights_reference="consent-licence-1",
        rights_digest="2" * 64,
        permissions=frozenset(
            permissions
            or {
                GovernedPermission.VIEW,
                GovernedPermission.DOWNLOAD,
                GovernedPermission.ANALYZE,
                GovernedPermission.RETAIN,
            }
        ),
        retention_class="competition-review",
        valid_from=T0,
        valid_until=valid_until,
        lifecycle=lifecycle,
        revoked_at=revoked_at,
    )


def test_pseudonymous_group_id_is_deterministic_nonreversible_and_namespace_scoped():
    secret = b"x" * 32
    one = pseudonymous_group_id(
        namespace="athlete",
        stable_source_id="kiga-athlete-123",
        secret=secret,
    )
    retry = pseudonymous_group_id(
        namespace="athlete",
        stable_source_id="kiga-athlete-123",
        secret=secret,
    )
    other_namespace = pseudonymous_group_id(
        namespace="event",
        stable_source_id="kiga-athlete-123",
        secret=secret,
    )
    other_secret = pseudonymous_group_id(
        namespace="athlete",
        stable_source_id="kiga-athlete-123",
        secret=b"y" * 32,
    )
    assert one == retry
    assert one != other_namespace
    assert one != other_secret
    assert "kiga-athlete-123" not in one

    with pytest.raises(DataGovernanceError, match="at least 32 bytes"):
        pseudonymous_group_id(
            namespace="athlete",
            stable_source_id="id",
            secret=b"weak",
        )


def test_training_permission_is_explicit_and_not_inferred_from_analysis_download_or_retention():
    record = rights()
    assert record.allows(GovernedPermission.ANALYZE, at=T0 + timedelta(minutes=1))
    assert record.allows(GovernedPermission.DOWNLOAD, at=T0 + timedelta(minutes=1))
    assert record.allows(GovernedPermission.RETAIN, at=T0 + timedelta(minutes=1))
    assert not record.allows(GovernedPermission.TRAIN, at=T0 + timedelta(minutes=1))

    training = rights(
        permissions={
            GovernedPermission.ANALYZE,
            GovernedPermission.TRAIN,
        }
    )
    assert training.allows(GovernedPermission.TRAIN, at=T0 + timedelta(minutes=1))


def test_expired_or_revoked_rights_deny_even_explicit_permissions():
    expired = rights(
        permissions={GovernedPermission.ANALYZE, GovernedPermission.TRAIN},
        valid_until=T0 + timedelta(minutes=10),
    )
    assert not expired.allows(GovernedPermission.ANALYZE, at=T0 + timedelta(minutes=10))

    revoked = rights(
        permissions={GovernedPermission.ANALYZE, GovernedPermission.TRAIN},
        lifecycle=RightsLifecycle.REVOKED,
        revoked_at=T0 + timedelta(minutes=5),
    )
    assert not revoked.allows(GovernedPermission.TRAIN, at=T0 + timedelta(minutes=6))


def retention(*, until=None, immutable_until=None, holds=()):
    return RetentionRecord(
        media_id="media-1",
        source_sha256="3" * 64,
        acquired_at=T0,
        retention_until=until,
        retention_class="competition-review",
        legal_hold_ids=tuple(holds),
        provider_immutable_until=immutable_until,
    )


def deletion_request() -> DeletionRequest:
    return DeletionRequest(
        request_id="delete-1",
        media_id="media-1",
        requested_by="operator-1",
        approved_by="admin-1",
        reason="Approved retention cleanup",
        requested_at=T0 + timedelta(minutes=1),
        correlation_id="correlation-1",
    )


def test_time_based_retention_and_provider_immutability_allow_quarantine_but_not_physical_delete():
    decision = evaluate_deletion(
        retention(
            until=T0 + timedelta(days=30),
            immutable_until=T0 + timedelta(days=90),
        ),
        deletion_request(),
        now=T0 + timedelta(days=10),
        rights=rights(),
    )
    assert decision.disposition is DeletionDisposition.QUARANTINE_ONLY
    assert "retention-window-active" in decision.blockers
    assert "provider-immutability-active" in decision.blockers
    assert decision.earliest_physical_delete_at == T0 + timedelta(days=90)


def test_legal_hold_and_active_provenance_references_hard_block_deletion():
    decision = evaluate_deletion(
        retention(holds=("legal-1",)),
        deletion_request(),
        now=T0 + timedelta(days=100),
        rights=rights(),
        active_evidence_refs=("evidence-1",),
        active_dataset_refs=("dataset-1",),
        active_export_refs=("export-1",),
    )
    assert decision.disposition is DeletionDisposition.BLOCKED
    assert set(decision.blockers) == {
        "legal-hold:legal-1",
        "active-evidence-ref:evidence-1",
        "active-dataset-ref:dataset-1",
        "active-export-ref:export-1",
    }
    assert decision.earliest_physical_delete_at is None


def test_provider_delete_denial_is_policy_state_not_transient_success():
    decision = evaluate_deletion(
        retention(),
        deletion_request(),
        now=T0 + timedelta(days=100),
        rights=rights(),
        provider_delete_allowed=False,
    )
    assert decision.disposition is DeletionDisposition.BLOCKED
    assert decision.blockers == ("provider-delete-denied",)


def test_physical_delete_is_allowed_only_after_all_governance_blockers_clear():
    decision = evaluate_deletion(
        retention(
            until=T0 + timedelta(days=30),
            immutable_until=T0 + timedelta(days=60),
        ),
        deletion_request(),
        now=T0 + timedelta(days=61),
        rights=rights(),
    )
    assert decision.disposition is DeletionDisposition.PHYSICAL_DELETE_ALLOWED
    assert decision.blockers == ()
    assert decision.earliest_physical_delete_at == T0 + timedelta(days=61)


def test_config_freeze_rejects_plaintext_secrets_but_allows_secret_references():
    with pytest.raises(DataGovernanceError, match="plaintext secret-like"):
        freeze_configuration(
            {
                "storage": {
                    "endpoint": "https://storage.invalid",
                    "access_key": "PLAINTEXT-KEY",
                }
            },
            snapshot_id="config-bad",
            organization_id="org-1",
            schema_version="config-v1",
            secret_references=(),
            created_at=T0,
        )

    frozen = freeze_configuration(
        {
            "storage": {
                "endpoint": "https://storage.invalid",
                "credential_ref": "secret://storage/runtime",
            },
            "limits": {"workers": 2},
        },
        snapshot_id="config-1",
        organization_id="org-1",
        schema_version="config-v1",
        secret_references=("secret://storage/runtime",),
        created_at=T0,
    )
    assert "PLAINTEXT" not in frozen.public_config_json
    assert frozen.secret_references == ("secret://storage/runtime",)
    assert len(frozen.config_digest) == 64


def test_config_freeze_is_canonical_for_mapping_order():
    one = freeze_configuration(
        {"b": 2, "a": {"x": 1}},
        snapshot_id="config-1",
        organization_id="org-1",
        schema_version="config-v1",
        secret_references=(),
        created_at=T0,
    )
    two = freeze_configuration(
        {"a": {"x": 1}, "b": 2},
        snapshot_id="config-2",
        organization_id="org-1",
        schema_version="config-v1",
        secret_references=(),
        created_at=T0 + timedelta(seconds=1),
    )
    assert one.config_digest == two.config_digest
    assert one.public_config_json == two.public_config_json


def make_change(
    change_id: str,
    from_digest: str,
    to_digest: str,
    when: datetime,
    prior=None,
) -> AuthorizedConfigChange:
    return AuthorizedConfigChange(
        change_id=change_id,
        organization_id="org-1",
        from_config_digest=from_digest,
        to_config_digest=to_digest,
        actor_id="operator-1",
        approver_id="admin-1",
        reason="Approved configuration change",
        correlation_id=f"corr-{change_id}",
        occurred_at=when,
        prior_change_digest=prior,
    )


def test_config_change_ledger_is_append_only_hash_chained_and_starts_from_current_digest():
    initial = freeze_configuration(
        {"workers": 1},
        snapshot_id="config-1",
        organization_id="org-1",
        schema_version="config-v1",
        secret_references=(),
        created_at=T0,
    )
    next_snapshot = freeze_configuration(
        {"workers": 2},
        snapshot_id="config-2",
        organization_id="org-1",
        schema_version="config-v1",
        secret_references=(),
        created_at=T0 + timedelta(minutes=1),
    )
    third_snapshot = freeze_configuration(
        {"workers": 3},
        snapshot_id="config-3",
        organization_id="org-1",
        schema_version="config-v1",
        secret_references=(),
        created_at=T0 + timedelta(minutes=2),
    )
    first = make_change(
        "change-1",
        initial.config_digest,
        next_snapshot.config_digest,
        T0 + timedelta(minutes=1),
    )
    second = make_change(
        "change-2",
        next_snapshot.config_digest,
        third_snapshot.config_digest,
        T0 + timedelta(minutes=2),
        first.digest,
    )
    ledger = ConfigChangeLedger(initial, (first, second))
    assert ledger.current_config_digest == third_snapshot.config_digest

    with pytest.raises(DataGovernanceError, match="does not start from current"):
        ledger.append(
            make_change(
                "change-bad",
                initial.config_digest,
                "8" * 64,
                T0 + timedelta(minutes=3),
                second.digest,
            )
        )


def source_evidence() -> EvidenceProvenanceRef:
    return EvidenceProvenanceRef(
        evidence_id="evidence-source-1",
        evidence_digest="4" * 64,
        canonical_source_sha256="5" * 64,
        kind=EvidenceKind.SOURCE_INTERVAL,
        represented_as_original=True,
    )


def overlay_evidence() -> EvidenceProvenanceRef:
    return EvidenceProvenanceRef(
        evidence_id="overlay-1",
        evidence_digest="6" * 64,
        canonical_source_sha256="5" * 64,
        kind=EvidenceKind.OVERLAY,
        represented_as_original=False,
    )


def decision(
    decision_id: str,
    *,
    evidence,
    state=DecisionState.CONFIRMED,
    semantic=DecisionSemanticLayer.JUDGING_INTERPRETATION,
    material=True,
    calibration_digest="a" * 64,
    limitations=(),
    when=T0,
    supersedes=None,
):
    return ProductionDecisionProvenance(
        decision_id=decision_id,
        organization_id="org-1",
        object_ref="analysis-1:deduction-1",
        semantic_layer=semantic,
        state=state,
        material=material,
        authority_ref="qualified-reviewer:reviewer-1",
        evidence=tuple(evidence),
        rulepack_digest="7" * 64,
        model_bundle_digest="8" * 64,
        software_digest="9" * 64,
        config_digest="b" * 64,
        calibration_digest=calibration_digest,
        created_at=when,
        limitations=tuple(limitations),
        supersedes_decision_id=supersedes,
    )


def test_derived_visualization_cannot_claim_to_be_original_evidence():
    with pytest.raises(DataGovernanceError, match="cannot be represented as original"):
        EvidenceProvenanceRef(
            evidence_id="fake-original",
            evidence_digest="4" * 64,
            canonical_source_sha256="5" * 64,
            kind=EvidenceKind.INTERPOLATED,
            represented_as_original=True,
        )


def test_confirmed_material_decision_cannot_rely_only_on_generated_or_overlay_evidence():
    with pytest.raises(DataGovernanceError, match="requires canonical source-interval evidence"):
        decision("decision-generated-only", evidence=(overlay_evidence(),))

    accepted = decision(
        "decision-source-backed",
        evidence=(source_evidence(), overlay_evidence()),
    )
    assert len(accepted.digest) == 64


def test_missing_calibration_digest_must_be_an_explicit_limitation_for_observation_layers():
    with pytest.raises(DataGovernanceError, match="calibration provenance"):
        decision(
            "decision-no-calibration",
            evidence=(source_evidence(),),
            calibration_digest=None,
        )

    allowed = decision(
        "decision-calibration-unavailable",
        evidence=(source_evidence(),),
        calibration_digest=None,
        limitations=("calibration-unavailable:measurement-disabled",),
    )
    assert "calibration-unavailable" in allowed.limitations[0]


def test_production_decision_history_is_append_only_and_cannot_fork():
    first = decision(
        "decision-1",
        evidence=(source_evidence(),),
        state=DecisionState.UNRESOLVED,
        when=T0,
    )
    second = decision(
        "decision-2",
        evidence=(source_evidence(),),
        state=DecisionState.CONFIRMED,
        when=T0 + timedelta(minutes=1),
        supersedes="decision-1",
    )
    ledger = ProductionDecisionLedger((first, second))
    assert ledger.current("org-1", "analysis-1:deduction-1") == second

    with pytest.raises(DataGovernanceError, match="cannot fork"):
        ledger.append(
            decision(
                "decision-3",
                evidence=(source_evidence(),),
                state=DecisionState.REJECTED,
                when=T0 + timedelta(minutes=2),
                supersedes="decision-1",
            )
        )
