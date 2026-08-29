from copy import deepcopy
from datetime import UTC, datetime, timedelta

import pytest

from ai_wagvid.competition_batch import (
    CompetitionBatchError,
    DisagreementRecord,
    FreezeReceipt,
    RoutineBatchEvent,
    RoutineBatchJournal,
    RoutineBatchState,
    aggregate_disagreements,
    plan_competition_batch,
    reveal_official_result,
)
from ai_wagvid.domain import Apparatus

T0 = datetime(2026, 8, 17, 14, 0, tzinfo=UTC)
PROFILE_A = "a" * 64
PROFILE_B = "b" * 64


def record(*, routine_id: str = "routine-1", official_final: float = 13.1) -> dict:
    return {
        "schema": "ai.wagvid.competition-video.v1",
        "source_system": "KIGA",
        "competition": {
            "external_id": "competition-1",
            "name": "Fixture Competition",
            "date_start": "2026-08-16",
            "date_end": "2026-08-16",
            "timezone": "Europe/Copenhagen",
            "venue": "Fixture Hall",
            "location": "Fixture City",
            "organizer": "Fixture Organizer",
            "federation": "Fixture Federation",
            "rule_profile": "fixture-rule-profile",
        },
        "routine": {
            "external_id": routine_id,
            "athlete_external_id": "athlete-1",
            "team_external_id": None,
            "apparatus": "BB",
            "round": "qualification",
            "rotation": "1",
            "start_order": 3,
            "category": "fixture-category",
            "performed_at": "2026-08-16T10:15:00+02:00",
        },
        "media": [
            {
                "media_id": f"media-{routine_id}",
                "camera_id": "camera-1",
                "view": "side",
                "content_type": "video/mp4",
                "byte_size": 123456,
                "duration_ms": 70000,
                "sha256": "c" * 64,
                "download_uri": "https://example.invalid/media/token",
            }
        ],
        "official_result": {
            "captured_at": "2026-08-16T11:00:00+02:00",
            "status": "official",
            "d_score": 5.2,
            "e_score": 7.9,
            "artistry": None,
            "neutral": 0.0,
            "final_score": official_final,
        },
        "rights": {
            "view_allowed": True,
            "download_allowed": True,
            "analysis_allowed": True,
            "retention_allowed": True,
            "training_allowed": False,
            "consent_reference": "fixture-consent",
            "retention_class": "competition-review",
        },
        "linkage": {
            "analysis_return_uri": "https://kiga.invalid/routine/1/analysis",
            "evidence_return_uri": "https://kiga.invalid/routine/1/evidence",
        },
    }


def plan(value: dict, *, profile: str = PROFILE_A):
    return plan_competition_batch(
        (value,),
        batch_id="batch-1",
        analysis_profile_digest=profile,
        requested_at=T0,
    )


def freeze_for(planned, *, frozen_at: datetime = T0 + timedelta(minutes=5)) -> FreezeReceipt:
    task = planned.task
    return FreezeReceipt(
        task_id=task.task_id,
        task_digest=task.digest,
        analysis_id="analysis-1",
        analysis_revision_id="analysis-revision-1",
        analysis_revision_digest="d" * 64,
        rulepack_digest="e" * 64,
        model_bundle_digest="f" * 64,
        frozen_at=frozen_at,
    )


def test_worker_payload_excludes_official_and_identity_context():
    planned = plan(record()).routines[0]
    payload = planned.task.worker_payload()
    serialized = str(payload)

    assert set(payload) == {
        "schema",
        "task_id",
        "idempotency_key",
        "apparatus",
        "rule_profile",
        "media",
        "analysis_profile_digest",
        "requested_at",
    }
    for forbidden in (
        "official_result",
        "official_final",
        "athlete_external_id",
        "team_external_id",
        "competition_external_id",
        "routine_external_id",
        "source_record_digest",
        "performed_at",
        "training_allowed",
        "adjudication",
    ):
        assert forbidden not in serialized
    assert "13.1" not in serialized
    assert "athlete-1" not in serialized
    assert "competition-1" not in serialized


def test_corrected_official_score_changes_withheld_envelope_not_ai_task():
    first = plan(record(official_final=13.1)).routines[0]
    corrected = plan(record(official_final=13.4)).routines[0]

    assert first.task.idempotency_key == corrected.task.idempotency_key
    assert first.task.task_id == corrected.task.task_id
    assert first.task.worker_payload() == corrected.task.worker_payload()
    assert first.task.digest == corrected.task.digest
    assert first.task.source_record_digest != corrected.task.source_record_digest
    assert (
        first.withheld_official.official_payload_digest
        != corrected.withheld_official.official_payload_digest
    )


def test_analysis_profile_change_creates_new_independent_analysis_task():
    first = plan(record(), profile=PROFILE_A).routines[0]
    second = plan(record(), profile=PROFILE_B).routines[0]
    assert first.task.idempotency_key != second.task.idempotency_key
    assert first.task.task_id != second.task.task_id
    assert first.task.digest != second.task.digest


def test_training_permission_is_independent_from_analysis_permission():
    value = record()
    assert value["rights"]["training_allowed"] is False
    result = plan(value)
    assert len(result.routines) == 1
    assert result.excluded == ()


def test_analysis_or_download_denial_excludes_routine_without_queuing_it():
    denied_analysis = record(routine_id="routine-denied-analysis")
    denied_analysis["rights"]["analysis_allowed"] = False
    denied_download = record(routine_id="routine-denied-download")
    denied_download["rights"]["download_allowed"] = False

    batch = plan_competition_batch(
        (denied_analysis, denied_download),
        batch_id="batch-denied",
        analysis_profile_digest=PROFILE_A,
        requested_at=T0,
    )
    assert batch.routines == ()
    reasons = {item.routine_external_id: item.reasons for item in batch.excluded}
    assert reasons["routine-denied-analysis"] == ("analysis-not-authorized",)
    assert reasons["routine-denied-download"] == ("media-download-not-authorized",)


def test_official_payload_may_be_received_early_but_cannot_be_revealed_until_after_freeze():
    planned = plan(record()).routines[0]
    freeze = freeze_for(planned)
    assert planned.withheld_official.received_at < freeze.frozen_at

    for reveal_time in (freeze.frozen_at - timedelta(seconds=1), freeze.frozen_at):
        with pytest.raises(CompetitionBatchError, match="strictly after AI freeze"):
            reveal_official_result(planned, freeze, revealed_at=reveal_time)

    revealed = reveal_official_result(
        planned,
        freeze,
        revealed_at=freeze.frozen_at + timedelta(seconds=1),
    )
    assert revealed.official_payload["final_score"] == 13.1
    assert revealed.official_payload_digest == planned.withheld_official.official_payload_digest
    assert revealed.freeze_receipt_digest == freeze.digest


def test_freeze_receipt_from_another_task_cannot_unlock_official_result():
    first = plan(record(routine_id="routine-1")).routines[0]
    second = plan(record(routine_id="routine-2")).routines[0]
    wrong_freeze = freeze_for(second)
    with pytest.raises(CompetitionBatchError, match="does not belong"):
        reveal_official_result(
            first,
            wrong_freeze,
            revealed_at=wrong_freeze.frozen_at + timedelta(seconds=1),
        )


def event(event_id: str, task_id: str, state: RoutineBatchState, when: datetime, prior=None):
    return RoutineBatchEvent(
        event_id=event_id,
        task_id=task_id,
        state=state,
        occurred_at=when,
        actor="batch-control",
        prior_event_digest=prior,
    )


def test_batch_journal_enforces_hash_chained_legal_state_transitions():
    task = plan(record()).routines[0].task
    queued = event("e1", task.task_id, RoutineBatchState.QUEUED, T0)
    running = event(
        "e2",
        task.task_id,
        RoutineBatchState.RUNNING,
        T0 + timedelta(seconds=1),
        queued.digest,
    )
    frozen = event(
        "e3",
        task.task_id,
        RoutineBatchState.AI_FROZEN,
        T0 + timedelta(seconds=2),
        running.digest,
    )
    journal = RoutineBatchJournal(task, (queued, running, frozen))
    assert journal.current_state is RoutineBatchState.AI_FROZEN

    with pytest.raises(CompetitionBatchError, match="illegal batch state transition"):
        journal.append(
            event(
                "e4",
                task.task_id,
                RoutineBatchState.NEEDS_REVIEW,
                T0 + timedelta(seconds=3),
                frozen.digest,
            )
        )


def test_batch_journal_rejects_hash_chain_tampering():
    task = plan(record()).routines[0].task
    queued = event("e1", task.task_id, RoutineBatchState.QUEUED, T0)
    journal = RoutineBatchJournal(task, (queued,))
    with pytest.raises(CompetitionBatchError, match="hash chain mismatch"):
        journal.append(
            event(
                "e2",
                task.task_id,
                RoutineBatchState.RUNNING,
                T0 + timedelta(seconds=1),
                "0" * 64,
            )
        )


def test_same_competition_routine_cannot_be_planned_twice_in_one_batch():
    with pytest.raises(CompetitionBatchError, match="same competition routine twice"):
        plan_competition_batch(
            (record(), deepcopy(record())),
            batch_id="batch-duplicate",
            analysis_profile_digest=PROFILE_A,
            requested_at=T0,
        )


def test_disagreement_aggregation_is_descriptive_by_requested_dimension():
    records = (
        DisagreementRecord(
            routine_external_id="routine-1",
            apparatus=Apparatus.BB,
            category="d-score",
            element_family="leap",
            deduction_category=None,
            camera_condition="fixed-side",
            delta_milli_points=200,
            material=True,
            comparison_digest="1" * 64,
        ),
        DisagreementRecord(
            routine_external_id="routine-2",
            apparatus=Apparatus.BB,
            category="d-score",
            element_family="leap",
            deduction_category=None,
            camera_condition="broadcast",
            delta_milli_points=-100,
            material=False,
            comparison_digest="2" * 64,
        ),
        DisagreementRecord(
            routine_external_id="routine-3",
            apparatus=Apparatus.FX,
            category="execution",
            element_family=None,
            deduction_category="landing",
            camera_condition=None,
            delta_milli_points=300,
            material=True,
            comparison_digest="3" * 64,
        ),
    )
    by_apparatus = aggregate_disagreements(records, dimension="apparatus")
    bb = next(item for item in by_apparatus if item.key == "BB")
    assert bb.routine_count == 2
    assert bb.material_count == 1
    assert bb.total_absolute_delta_milli_points == 300
    assert bb.maximum_absolute_delta_milli_points == 200

    by_camera = aggregate_disagreements(records, dimension="camera_condition")
    assert {item.key for item in by_camera} == {"<unavailable>", "broadcast", "fixed-side"}
