from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from django.db import transaction
from django.db.models import F, Q
from django.utils import timezone

from .models import AnalysisJob, Gymnast, Organization, UploadSession, WorkerNode


class InvalidStateTransition(ValueError):
    pass


ANALYSIS_TRANSITIONS = {
    AnalysisJob.State.DRAFT: {AnalysisJob.State.QUEUED, AnalysisJob.State.CANCELLED},
    AnalysisJob.State.QUEUED: {
        AnalysisJob.State.RUNNING,
        AnalysisJob.State.BLOCKED,
        AnalysisJob.State.CANCELLED,
    },
    AnalysisJob.State.BLOCKED: {AnalysisJob.State.QUEUED, AnalysisJob.State.CANCELLED},
    AnalysisJob.State.RUNNING: {
        AnalysisJob.State.NEEDS_REVIEW,
        AnalysisJob.State.COMPLETED,
        AnalysisJob.State.FAILED_RETRYABLE,
        AnalysisJob.State.FAILED_TERMINAL,
        AnalysisJob.State.CANCELLED,
    },
    AnalysisJob.State.FAILED_RETRYABLE: {
        AnalysisJob.State.QUEUED,
        AnalysisJob.State.CANCELLED,
    },
    AnalysisJob.State.NEEDS_REVIEW: {AnalysisJob.State.COMPLETED},
}


@transaction.atomic
def transition_analysis(job_id: UUID, target: str, *, error_code: str = "") -> AnalysisJob:
    job = AnalysisJob.objects.select_for_update().get(pk=job_id)
    if target not in ANALYSIS_TRANSITIONS.get(job.state, set()):
        raise InvalidStateTransition(f"Cannot move analysis from {job.state} to {target}")
    job.state = target
    job.error_code = error_code
    if target == AnalysisJob.State.COMPLETED:
        job.progress_percent = 100
    job.save(update_fields=["state", "error_code", "progress_percent", "updated_at"])
    return job


@dataclass(frozen=True)
class UploadRequest:
    capture_id: UUID
    idempotency_key: str
    local_filename: str
    expected_bytes: int
    expected_sha256: str
    gymnast: Gymnast
    kind: str
    recorded_at: datetime


@transaction.atomic
def open_upload(organization: Organization, request: UploadRequest) -> tuple[UploadSession, bool]:
    existing = UploadSession.objects.filter(
        organization=organization, idempotency_key=request.idempotency_key
    ).first()
    if existing:
        same_request = (
            existing.capture_id == request.capture_id
            and existing.expected_bytes == request.expected_bytes
            and existing.expected_sha256 == request.expected_sha256
            and existing.gymnast_id == request.gymnast.id
            and existing.kind == request.kind
        )
        if not same_request:
            raise ValueError("Idempotency key was reused with a different upload")
        return existing, False
    session = UploadSession.objects.create(
        organization=organization,
        capture_id=request.capture_id,
        idempotency_key=request.idempotency_key,
        local_filename=request.local_filename,
        expected_bytes=request.expected_bytes,
        expected_sha256=request.expected_sha256,
        gymnast=request.gymnast,
        kind=request.kind,
        recorded_at=request.recorded_at,
    )
    return session, True


@transaction.atomic
def checkpoint_upload(session_id: UUID, received_bytes: int) -> UploadSession:
    session = UploadSession.objects.select_for_update().get(pk=session_id)
    if session.state in {UploadSession.State.COMPLETED, UploadSession.State.FAILED}:
        raise InvalidStateTransition(f"Upload is already {session.state}")
    if received_bytes < session.received_bytes or received_bytes > session.expected_bytes:
        raise ValueError("Invalid upload checkpoint")
    session.received_bytes = received_bytes
    session.state = UploadSession.State.UPLOADING
    session.save(update_fields=["received_bytes", "state", "updated_at"])
    return session


@transaction.atomic
def lease_next_analysis(worker: WorkerNode, *, lease_seconds: int = 300) -> AnalysisJob | None:
    now = timezone.now()
    job = (
        AnalysisJob.objects.select_for_update()
        .filter(
            Q(state=AnalysisJob.State.QUEUED)
            | Q(state=AnalysisJob.State.RUNNING, lease_expires_at__lt=now)
        )
        .order_by("created_at")
        .first()
    )
    if not job:
        return None
    job.state = AnalysisJob.State.RUNNING
    job.leased_by = worker
    job.lease_expires_at = now + timedelta(seconds=lease_seconds)
    job.attempts = F("attempts") + 1
    job.save(
        update_fields=[
            "state",
            "leased_by",
            "lease_expires_at",
            "attempts",
            "updated_at",
        ]
    )
    job.refresh_from_db()
    return job


@transaction.atomic
def extend_analysis_lease(job_id: UUID, worker: WorkerNode, *, lease_seconds: int = 300) -> None:
    updated = AnalysisJob.objects.filter(
        pk=job_id,
        leased_by=worker,
        state=AnalysisJob.State.RUNNING,
    ).update(lease_expires_at=timezone.now() + timedelta(seconds=lease_seconds))
    if updated != 1:
        raise InvalidStateTransition("Worker does not own this active lease")
