from dataclasses import dataclass
from uuid import UUID

from django.db import transaction

from .models import AnalysisJob, Organization, UploadSession


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
