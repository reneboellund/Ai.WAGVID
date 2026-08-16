from datetime import UTC, datetime, timedelta

import pytest
from django.utils import timezone

from wagvid_app.models import AnalysisJob, Gymnast, Level, MediaAsset, Organization, WorkerNode
from wagvid_app.operations import (
    InvalidStateTransition,
    fail_analysis,
    lease_next_analysis,
    report_analysis_progress,
    retry_analysis,
)


def make_job():
    organization = Organization.objects.create(name="Worker Club", slug="worker-club")
    level = Level.objects.create(organization=organization, name="Senior")
    gymnast = Gymnast.objects.create(
        organization=organization,
        level=level,
        display_name="Test Gymnast",
        license_number="WORK-1",
    )
    media = MediaAsset.objects.create(
        organization=organization,
        gymnast=gymnast,
        kind=MediaAsset.Kind.ROUTINE,
        state=MediaAsset.State.STORED,
        recorded_at=datetime.now(UTC),
    )
    return AnalysisJob.objects.create(
        organization=organization,
        media=media,
        state=AnalysisJob.State.QUEUED,
        scope="routine",
        rulepack_id="wag-test@1",
        model_profile="baseline",
    )


@pytest.mark.django_db
def test_worker_lease_and_progress_are_owned_monotonic_and_append_only():
    job = make_job()
    worker = WorkerNode.objects.create(name="worker-1", state=WorkerNode.State.ONLINE)
    stranger = WorkerNode.objects.create(name="worker-2", state=WorkerNode.State.ONLINE)
    leased = lease_next_analysis(worker, lease_seconds=60)
    assert leased.id == job.id
    assert leased.attempts == 1

    first = report_analysis_progress(job.id, worker, stage="probe", progress_percent=10)
    second = report_analysis_progress(job.id, worker, stage="pose", progress_percent=40)
    assert (first.sequence, second.sequence) == (1, 2)
    with pytest.raises(ValueError, match="backwards"):
        report_analysis_progress(job.id, worker, stage="bad", progress_percent=39)
    with pytest.raises(InvalidStateTransition, match="own"):
        report_analysis_progress(job.id, stranger, stage="bad", progress_percent=50)
    with pytest.raises(ValueError, match="append-only"):
        first.delete()


@pytest.mark.django_db
def test_expired_lease_is_recovered_and_old_worker_loses_ownership():
    job = make_job()
    first_worker = WorkerNode.objects.create(name="worker-1", state=WorkerNode.State.ONLINE)
    second_worker = WorkerNode.objects.create(name="worker-2", state=WorkerNode.State.ONLINE)
    leased = lease_next_analysis(first_worker)
    AnalysisJob.objects.filter(pk=leased.id).update(
        lease_expires_at=timezone.now() - timedelta(seconds=1)
    )
    recovered = lease_next_analysis(second_worker)
    assert recovered.id == job.id
    assert recovered.leased_by == second_worker
    assert recovered.attempts == 2
    with pytest.raises(InvalidStateTransition, match="own"):
        report_analysis_progress(job.id, first_worker, stage="stale", progress_percent=5)


@pytest.mark.django_db
def test_retryable_failure_requeues_but_attempt_limit_fails_terminally():
    job = make_job()
    worker = WorkerNode.objects.create(name="worker-1", state=WorkerNode.State.ONLINE)
    leased = lease_next_analysis(worker)
    failed = fail_analysis(
        leased.id, worker, error_code="MODEL_TIMEOUT", retryable=True, max_attempts=2
    )
    assert failed.state == AnalysisJob.State.FAILED_RETRYABLE
    assert failed.leased_by is None
    retry_analysis(job.id)
    leased_again = lease_next_analysis(worker)
    terminal = fail_analysis(
        leased_again.id, worker, error_code="MODEL_TIMEOUT", retryable=True, max_attempts=2
    )
    assert terminal.state == AnalysisJob.State.FAILED_TERMINAL
    with pytest.raises(InvalidStateTransition, match="retryable"):
        retry_analysis(job.id)
