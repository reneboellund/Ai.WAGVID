import hashlib
import io
import uuid
from datetime import UTC, datetime

import pytest

from wagvid_app.models import AnalysisJob, Gymnast, Level, MediaAsset, Organization
from wagvid_app.operations import (
    InvalidStateTransition,
    UploadRequest,
    checkpoint_upload,
    open_upload,
    transition_analysis,
)
from wagvid_app.storage import LocalObjectStore, ObjectIntegrityError


def test_verified_object_store_is_atomic_and_rejects_bad_checksum(tmp_path):
    payload = b"wagvid-video-fixture"
    digest = hashlib.sha256(payload).hexdigest()
    store = LocalObjectStore(tmp_path)
    stored = store.put_verified(
        "org/capture.mp4",
        io.BytesIO(payload),
        expected_size=len(payload),
        expected_sha256=digest,
    )
    assert stored.sha256 == digest
    assert store.exists(stored.key)
    with pytest.raises(ObjectIntegrityError):
        store.put_verified(
            "org/bad.mp4",
            io.BytesIO(payload),
            expected_size=len(payload),
            expected_sha256="0" * 64,
        )
    assert not store.exists("org/bad.mp4")


def test_object_store_rejects_path_escape(tmp_path):
    with pytest.raises(ValueError):
        LocalObjectStore(tmp_path).exists("../secret")


@pytest.mark.django_db
def test_upload_idempotency_and_forward_only_checkpoint():
    organization = Organization.objects.create(name="Club", slug="club")
    request = UploadRequest(
        capture_id=uuid.uuid4(),
        idempotency_key="android-1:capture-1",
        local_filename="capture.mp4",
        expected_bytes=100,
        expected_sha256="a" * 64,
    )
    first, created = open_upload(organization, request)
    repeated, repeated_created = open_upload(organization, request)
    assert created is True
    assert repeated_created is False
    assert repeated.pk == first.pk
    checkpoint_upload(first.id, 50)
    with pytest.raises(ValueError):
        checkpoint_upload(first.id, 49)


@pytest.mark.django_db
def test_analysis_state_machine_blocks_invalid_jump():
    organization = Organization.objects.create(name="Club", slug="club")
    level = Level.objects.create(organization=organization, name="Trin 1")
    gymnast = Gymnast.objects.create(
        organization=organization,
        level=level,
        display_name="Gymnast",
        license_number="L-1",
    )
    media = MediaAsset.objects.create(
        organization=organization,
        gymnast=gymnast,
        kind=MediaAsset.Kind.DRILL,
        recorded_at=datetime.now(UTC),
    )
    job = AnalysisJob.objects.create(
        organization=organization,
        media=media,
        scope="single-skill",
        rulepack_id="test",
        model_profile="test",
    )
    with pytest.raises(InvalidStateTransition):
        transition_analysis(job.id, AnalysisJob.State.COMPLETED)
    transition_analysis(job.id, AnalysisJob.State.QUEUED)
    transition_analysis(job.id, AnalysisJob.State.RUNNING)
    completed = transition_analysis(job.id, AnalysisJob.State.COMPLETED)
    assert completed.progress_percent == 100
