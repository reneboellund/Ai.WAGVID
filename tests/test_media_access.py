import hashlib
from datetime import UTC, datetime

import pytest
from django.contrib.auth.models import User
from django.urls import reverse

from wagvid_app.models import Gymnast, Level, MediaAsset, Membership, Organization
from wagvid_app.storage import LocalObjectStore


@pytest.mark.django_db
def test_signed_media_grant_is_scoped_and_serves_verified_original(client, tmp_path, settings):
    settings.WAGVID_OBJECT_ROOT = tmp_path
    settings.WAGVID_OBJECT_SIGNING_SECRET = "test-secret-that-is-at-least-32-characters"
    organization = Organization.objects.create(name="Club", slug="media-club")
    user = User.objects.create_user("media-user", password="secret")
    Membership.objects.create(user=user, organization=organization, role=Membership.Role.REVIEWER)
    level = Level.objects.create(organization=organization, name="Level")
    gymnast = Gymnast.objects.create(
        organization=organization, display_name="Gymnast", license_number="M-1", level=level
    )
    payload = b"immutable-video"
    digest = hashlib.sha256(payload).hexdigest()
    LocalObjectStore().put_verified(
        "org/original.mp4", source=__import__("io").BytesIO(payload),
        expected_size=len(payload), expected_sha256=digest,
    )
    media = MediaAsset.objects.create(
        organization=organization, gymnast=gymnast, kind=MediaAsset.Kind.DRILL,
        state=MediaAsset.State.STORED, recorded_at=datetime.now(UTC),
        object_key="org/original.mp4", sha256=digest, size_bytes=len(payload),
        content_type="video/mp4", original_filename="training.mp4",
    )
    client.force_login(user)
    granted = client.post(reverse("media-object-grant", args=[media.id]))
    assert granted.status_code == 200
    downloaded = client.get(granted.json()["url"])
    assert downloaded.status_code == 200
    assert b"".join(downloaded.streaming_content) == payload
    assert downloaded["ETag"] == f'"{digest}"'
    assert organization.audit_events.filter(action="media.access-granted").exists()


@pytest.mark.django_db
def test_media_download_rejects_missing_or_tampered_token(client, tmp_path, settings):
    settings.WAGVID_OBJECT_ROOT = tmp_path
    settings.WAGVID_OBJECT_SIGNING_SECRET = "test-secret-that-is-at-least-32-characters"
    organization = Organization.objects.create(name="Club", slug="denied-club")
    level = Level.objects.create(organization=organization, name="Level")
    gymnast = Gymnast.objects.create(
        organization=organization, display_name="Gymnast", license_number="M-2", level=level
    )
    media = MediaAsset.objects.create(
        organization=organization, gymnast=gymnast, kind=MediaAsset.Kind.DRILL,
        state=MediaAsset.State.STORED, recorded_at=datetime.now(UTC),
        object_key="missing.mp4", sha256="a" * 64,
    )
    url = reverse("media-object-download", args=[media.id])
    assert client.get(url).status_code == 403
    assert client.get(url + "?access=tampered.token").status_code == 403
