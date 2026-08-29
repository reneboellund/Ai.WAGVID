from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from ai_wagvid.domain import Apparatus
from ai_wagvid.score_comparison import ScoreLine
from ai_wagvid.score_verification import (
    AnalysisQualitySnapshot,
    DiscrepancyAdjudication,
    DiscrepancyAdjudicationLedger,
    DiscrepancyDecision,
    DiscrepancyReason,
    EvidenceLink,
    FrozenAnalysis,
    LedgerReference,
    OfficialScoreHistory,
    OfficialScoreVersion,
    RuleLink,
    ScoreVerificationError,
    compare_frozen_to_official,
    discrepancy_cases_from_comparison,
)

T0 = datetime(2026, 8, 17, 12, 0, tzinfo=UTC)
RULEPACK_DIGEST = "a" * 64


def ledger(schema: str, *, resolved: bool = True) -> LedgerReference:
    return LedgerReference(
        schema=schema,
        digest=("b" if schema.startswith("dscore") else "c") * 64,
        rulepack_id="fixture-rulepack@v1",
        rulepack_digest=RULEPACK_DIGEST,
        resolved=resolved,
        unresolved_refs=() if resolved else ("item-1",),
    )


def frozen() -> FrozenAnalysis:
    quality = AnalysisQualitySnapshot(
        media_id="media-1",
        source_sha256="d" * 64,
        apparatus=Apparatus.BB,
        calibration_state="valid",
        camera_suitability="suitable-with-known-limitations",
        limitations=("fixture-limitation",),
        model_digests=("e" * 64,),
    )
    return FrozenAnalysis(
        analysis_id="analysis-1",
        revision_id="revision-1",
        quality=quality,
        reconstructed_score=ScoreLine(
            d_score=Decimal("5.4"),
            e_score=Decimal("7.8"),
            neutral=Decimal("0.0"),
            final_score=Decimal("13.2"),
        ),
        d_ledger=ledger("dscore-ledger-v1"),
        deduction_ledger=ledger("deduction-ledger-v1"),
        rulepack_id="fixture-rulepack@v1",
        rulepack_digest=RULEPACK_DIGEST,
        software_digest="f" * 64,
        frozen_at=T0,
    )


def official(*, imported_at: datetime = T0 + timedelta(seconds=1), version: int = 1, status: str = "official") -> OfficialScoreVersion:
    return OfficialScoreVersion(
        official_result_id="official-1",
        version=version,
        score=ScoreLine(
            d_score=Decimal("5.2"),
            e_score=Decimal("7.9"),
            neutral=Decimal("0.0"),
            final_score=Decimal("13.1"),
        ),
        imported_at=imported_at,
        source_ref=f"result-version-{version}",
        status=status,
    )


def test_official_score_import_at_or_before_freeze_is_rejected_as_leakage_unsafe():
    for imported_at in (T0 - timedelta(seconds=1), T0):
        with pytest.raises(ScoreVerificationError, match="at/before AI freeze"):
            compare_frozen_to_official(
                frozen(),
                official(imported_at=imported_at),
                compared_at=T0 + timedelta(seconds=2),
            )


def test_post_freeze_official_comparison_is_digest_bound_and_decimal_exact():
    comparison = compare_frozen_to_official(
        frozen(),
        official(),
        compared_at=T0 + timedelta(seconds=2),
        threshold=Decimal("0.100"),
    )
    differences = {item.field: item for item in comparison.comparison.differences}
    assert differences["d_score"].delta == Decimal("0.2")
    assert differences["e_score"].delta == Decimal("-0.1")
    assert comparison.frozen_analysis_digest == frozen().digest
    assert len(comparison.digest) == 64


def test_frozen_analysis_rejects_mismatched_rulepack_ledger():
    base = frozen()
    wrong = LedgerReference(
        schema="dscore-ledger-v1",
        digest="1" * 64,
        rulepack_id="other-rulepack",
        rulepack_digest="2" * 64,
        resolved=True,
    )
    with pytest.raises(ScoreVerificationError, match="D ledger rulepack"):
        FrozenAnalysis(
            **{**base.__dict__, "d_ledger": wrong}
        )


def test_official_score_history_is_append_only_and_preserves_corrected_withdrawn_versions():
    first = official(version=1, status="official")
    corrected = OfficialScoreVersion(
        official_result_id="official-1",
        version=2,
        score=ScoreLine(Decimal("5.3"), Decimal("7.9"), Decimal("0.0"), Decimal("13.2")),
        imported_at=T0 + timedelta(seconds=3),
        source_ref="corrected-result",
        status="corrected",
    )
    withdrawn = OfficialScoreVersion(
        official_result_id="official-1",
        version=3,
        score=corrected.score,
        imported_at=T0 + timedelta(seconds=4),
        source_ref="withdrawal-record",
        status="withdrawn",
    )
    history = OfficialScoreHistory((first, corrected, withdrawn))
    assert history.versions == (first, corrected, withdrawn)
    assert history.current == withdrawn

    with pytest.raises(ScoreVerificationError, match="contiguous"):
        history.append(
            OfficialScoreVersion(
                official_result_id="official-1",
                version=5,
                score=withdrawn.score,
                imported_at=T0 + timedelta(seconds=5),
                source_ref="bad-gap",
            )
        )


def test_only_material_differences_become_discrepancy_cases():
    comparison = compare_frozen_to_official(
        frozen(), official(), compared_at=T0 + timedelta(seconds=2), threshold=Decimal("0.15")
    )
    cases = discrepancy_cases_from_comparison(comparison)
    assert [item.field for item in cases] == ["d_score"]
    assert cases[0].delta == Decimal("0.2")
    assert cases[0].review_ready is False


def test_substantive_adjudication_requires_evidence_and_rule_source_links():
    comparison = compare_frozen_to_official(
        frozen(), official(), compared_at=T0 + timedelta(seconds=2), threshold=Decimal("0.15")
    )
    case = discrepancy_cases_from_comparison(comparison)[0]
    ledger = DiscrepancyAdjudicationLedger((case,))
    with pytest.raises(ScoreVerificationError, match="requires both evidence and rule source"):
        ledger.append(
            DiscrepancyAdjudication(
                adjudication_id="adj-1",
                case_digest=case.digest,
                reviewer_id="reviewer-a",
                reviewer_qualification_ref="qualification-record-1",
                decision=DiscrepancyDecision.AI_SUPPORTED,
                reason_codes=(DiscrepancyReason.COUNTING,),
                notes="Cannot decide without linked evidence/rules",
                created_at=T0 + timedelta(seconds=3),
            )
        )

    unresolved = DiscrepancyAdjudication(
        adjudication_id="adj-unresolved",
        case_digest=case.digest,
        reviewer_id="reviewer-a",
        reviewer_qualification_ref="qualification-record-1",
        decision=DiscrepancyDecision.UNRESOLVED,
        reason_codes=(DiscrepancyReason.EVIDENCE_LIMITATION,),
        notes="Evidence package incomplete",
        created_at=T0 + timedelta(seconds=3),
    )
    ledger.append(unresolved)
    assert ledger.current(case.case_id) == unresolved


def test_evidence_and_rule_linked_case_supports_all_issue_adjudication_outcomes():
    comparison = compare_frozen_to_official(
        frozen(), official(), compared_at=T0 + timedelta(seconds=2), threshold=Decimal("0.15")
    )
    cases = discrepancy_cases_from_comparison(
        comparison,
        evidence_by_field={"d_score": (EvidenceLink("ev-1", "1" * 64),)},
        rules_by_field={"d_score": (RuleLink("fixture.counting", "source:section-x"),)},
        confidence_by_field_milli={"d_score": 900},
    )
    case = cases[0]
    assert case.review_ready is True
    for index, outcome in enumerate(DiscrepancyDecision):
        ledger = DiscrepancyAdjudicationLedger((case,))
        item = DiscrepancyAdjudication(
            adjudication_id=f"adj-{index}",
            case_digest=case.digest,
            reviewer_id="reviewer-a",
            reviewer_qualification_ref="qualification-record-1",
            decision=outcome,
            reason_codes=(DiscrepancyReason.COUNTING,),
            notes="Qualified review of synchronized evidence and rule source",
            created_at=T0 + timedelta(seconds=3),
        )
        ledger.append(item)
        assert ledger.current(case.case_id) == item


def test_adjudication_history_is_append_only_and_cannot_fork():
    comparison = compare_frozen_to_official(
        frozen(), official(), compared_at=T0 + timedelta(seconds=2), threshold=Decimal("0.15")
    )
    case = discrepancy_cases_from_comparison(
        comparison,
        evidence_by_field={"d_score": (EvidenceLink("ev-1", "1" * 64),)},
        rules_by_field={"d_score": (RuleLink("fixture.rule", "source:locator"),)},
    )[0]
    first = DiscrepancyAdjudication(
        adjudication_id="adj-1",
        case_digest=case.digest,
        reviewer_id="reviewer-a",
        reviewer_qualification_ref="qualification-a",
        decision=DiscrepancyDecision.UNRESOLVED,
        reason_codes=(DiscrepancyReason.RULE_INTERPRETATION,),
        notes="Needs superior review",
        created_at=T0 + timedelta(seconds=3),
    )
    second = DiscrepancyAdjudication(
        adjudication_id="adj-2",
        case_digest=case.digest,
        reviewer_id="reviewer-b",
        reviewer_qualification_ref="qualification-b",
        decision=DiscrepancyDecision.OFFICIAL_CONFIRMED,
        reason_codes=(DiscrepancyReason.RULE_INTERPRETATION,),
        notes="Superior review resolved interpretation",
        created_at=T0 + timedelta(seconds=4),
        supersedes_adjudication_id="adj-1",
    )
    ledger = DiscrepancyAdjudicationLedger((case,), (first, second))
    assert ledger.history(case.case_id) == (first, second)

    with pytest.raises(ScoreVerificationError, match="cannot fork"):
        ledger.append(
            DiscrepancyAdjudication(
                adjudication_id="adj-3",
                case_digest=case.digest,
                reviewer_id="reviewer-c",
                reviewer_qualification_ref="qualification-c",
                decision=DiscrepancyDecision.AI_SUPPORTED,
                reason_codes=(DiscrepancyReason.COUNTING,),
                notes="Conflicting fork",
                created_at=T0 + timedelta(seconds=5),
                supersedes_adjudication_id="adj-1",
            )
        )


def test_non_finite_score_values_are_rejected_before_freeze_or_import():
    base = frozen()
    with pytest.raises(ScoreVerificationError, match="must be finite"):
        FrozenAnalysis(
            **{
                **base.__dict__,
                "reconstructed_score": ScoreLine(Decimal("NaN"), None, None, None),
            }
        )
    with pytest.raises(ScoreVerificationError, match="must be finite"):
        OfficialScoreVersion(
            official_result_id="official-bad",
            version=1,
            score=ScoreLine(None, Decimal("Infinity"), None, None),
            imported_at=T0 + timedelta(seconds=1),
            source_ref="bad",
        )
