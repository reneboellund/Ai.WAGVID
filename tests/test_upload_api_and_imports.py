import hashlib
import json
import uuid
from datetime import UTC, datetime

import pytest
from django.test import override_settings
from django.urls import reverse

from wagvid_app.imports import commit_gymnast_import, preview_gymnast_csv
from wagvid_app.models import (
    AnalysisJob,
    Device,
    Gymnast,
    Level,
    MediaAsset,
    Organization,
    WorkerNode,
)
from wagvid_app.operations import extend_analysis_lease, lease_next_analysis


def create_capture_context():
    organization = Organization.objects.create(name="Club", slug="club")
    level = Level.objects.create(organization=organization, name="Trin 4")
    gymnast = Gymnast.objects.create(
        organization=organization,
        level=level,
        display_name="Test Gymnast",
        license_number="DK-1",
    )
    device = Device.objects.create(
        organization=organization,
        name="Phone",
        device_key="phone-1",
        state=Device.State.READY,
    )
    device.set_api_token("test-token")
    device.save(update_fields=["api_token_hash"])
    return organization, gymnast, device


def auth_headers():
    return {"HTTP_X_WAGVID_DEVICE": "phone-1", "HTTP_AUTHORIZATION": "Bearer test-token"}


@pytest.mark.django_db
@override_settings(WAGVID_MAX_UPLOAD_BYTES=1024, WAGVID_MAX_CHUNK_BYTES=512)
def test_authenticated_upload_open_chunk_finalize_is_idempotent(client, tmp_path, settings):
    settings.WAGVID_OBJECT_ROOT = tmp_path
    organization, gymnast, _ = create_capture_context()
    content = b"small-video-fixture"
    capture_id = uuid.uuid4()
    payload = {
        "capture_id": str(capture_id),
        "gymnast_id": str(gymnast.id),
        "idempotency_key": f"phone-1:{capture_id}",
        "local_filename": "video.mp4",
        "expected_bytes": len(content),
        "expected_sha256": hashlib.sha256(content).hexdigest(),
        "kind": "drill",
        "recorded_at": datetime.now(UTC).isoformat(),
    }
    opened = client.post(
        reverse("device-upload-open"),
        data=json.dumps(payload),
        content_type="application/json",
        **auth_headers(),
    )
    assert opened.status_code == 201
    upload_id = opened.json()["upload_id"]
    repeated = client.post(
        reverse("device-upload-open"),
        data=json.dumps(payload),
        content_type="application/json",
        **auth_headers(),
    )
    assert repeated.status_code == 200
    assert repeated.json()["upload_id"] == upload_id

    chunked = client.put(
        reverse("device-upload-chunk", args=[upload_id]),
        data=content,
        content_type="application/octet-stream",
        HTTP_X_UPLOAD_OFFSET="0",
        **auth_headers(),
    )
    assert chunked.status_code == 200
    finalized = client.post(reverse("device-upload-finalize", args=[upload_id]), **auth_headers())
    assert finalized.status_code == 201
    media = MediaAsset.objects.get(pk=finalized.json()["media_id"])
    assert media.organization == organization
    assert media.original_retained is True
    assert (tmp_path / media.object_key).read_bytes() == content


@pytest.mark.django_db
def test_upload_api_rejects_missing_device_credentials(client):
    assert (
        client.post(
            reverse("device-upload-open"), data="{}", content_type="application/json"
        ).status_code
        == 401
    )


@pytest.mark.django_db
def test_csv_preview_is_atomic_and_rejects_duplicates():
    organization = Organization.objects.create(name="Club", slug="club")
    Level.objects.create(organization=organization, name="Trin 4")
    invalid = preview_gymnast_csv(
        organization,
        "name,license_number,level\nOne,SAME,Trin 4\nTwo,SAME,Trin 4\n",
    )
    assert invalid.can_commit is False
    with pytest.raises(ValueError):
        commit_gymnast_import(organization, invalid)
    assert organization.gymnasts.count() == 0

    valid = preview_gymnast_csv(
        organization,
        "name,license_number,discipline,level,kiga_id\nOne,DK-1,MAG,Trin 4,KIGA-1\n",
    )
    created = commit_gymnast_import(organization, valid)
    assert [gymnast.license_number for gymnast in created] == ["DK-1"]
    assert created[0].discipline == Gymnast.Discipline.MAG

    invalid_discipline = preview_gymnast_csv(
        organization,
        "name,license_number,discipline,level\nTwo,DK-2,UNKNOWN,Trin 4\n",
    )
    assert invalid_discipline.can_commit is False


@pytest.mark.django_db
def test_worker_lease_is_owned_and_extended():
    organization, gymnast, _ = create_capture_context()
    media = MediaAsset.objects.create(
        organization=organization,
        gymnast=gymnast,
        kind=MediaAsset.Kind.DRILL,
        recorded_at=datetime.now(UTC),
    )
    job = AnalysisJob.objects.create(
        organization=organization,
        media=media,
        state=AnalysisJob.State.QUEUED,
        scope="single-skill",
        rulepack_id="test",
        model_profile="test",
    )
    worker = WorkerNode.objects.create(name="worker-1", state=WorkerNode.State.ONLINE)
    other = WorkerNode.objects.create(name="worker-2", state=WorkerNode.State.ONLINE)
    leased = lease_next_analysis(worker)
    assert leased.id == job.id
    assert leased.leased_by == worker
    assert leased.attempts == 1
    extend_analysis_lease(job.id, worker)
    with pytest.raises(ValueError):
        extend_analysis_lease(job.id, other)
