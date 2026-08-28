import hashlib
from datetime import UTC, datetime

import pytest
from django.contrib.auth.models import User
from django.urls import reverse

from wagvid_app.models import Gymnast, Level, MediaAsset, Membership, Organization
from wagvid_app.storage import LocalObjectStore


def _stored_media(client, tmp_path, settings, *, slug="media-club"):
    settings.WAGVID_OBJECT_ROOT = tmp_path
    settings.WAGVID_OBJECT_SIGNING_SECRET = "test-secret-that-is-at-least-32-characters"
    organization = Organization.objects.create(name="Club", slug=slug)
    user = User.objects.create_user(f"user-{slug}", password="secret")
    Membership.objects.create(user=user, organization=organization, role=Membership.Role.REVIEWER)
    level = Level.objects.create(organization=organization, name="Level")
    gymnast = Gymnast.objects.create(
        organization=organization, display_name="Gymnast", license_number=f"M-{slug}", level=level
    )
    payload = b"immutable-video"
    digest = hashlib.sha256(payload).hexdigest()
    key = f"{slug}/original.mp4"
    LocalObjectStore().put_verified(
        key,
        source=__import__("io").BytesIO(payload),
        expected_size=len(payload),
        expected_sha256=digest,
    )
    media = MediaAsset.objects.create(
        organization=organization,
        gymnast=gymnast,
        kind=MediaAsset.Kind.DRILL,
        state=MediaAsset.State.STORED,
        recorded_at=datetime.now(UTC),
        object_key=key,
        sha256=digest,
        size_bytes=len(payload),
        content_type="video/mp4",
        original_filename="training.mp4",
    )
    client.force_login(user)
    granted = client.post(reverse("media-object-grant", args=[media.id]))
    assert granted.status_code == 200
    return organization, media, payload, digest, granted.json()["url"]


@pytest.mark.django_db
def test_signed_media_grant_is_scoped_and_serves_verified_original(client, tmp_path, settings):
    organization, _media, payload, digest, url = _stored_media(client, tmp_path, settings)
    downloaded = client.get(url)
    assert downloaded.status_code == 200
    assert b"".join(downloaded.streaming_content) == payload
    assert downloaded["ETag"] == f'"{digest}"'
    assert downloaded["Accept-Ranges"] == "bytes"
    assert organization.audit_events.filter(action="media.access-granted").exists()


@pytest.mark.django_db
def test_signed_media_supports_single_byte_ranges_for_video_seeking(client, tmp_path, settings):
    _organization, _media, payload, digest, url = _stored_media(
        client, tmp_path, settings, slug="range-club"
    )

    partial = client.get(url, HTTP_RANGE="bytes=2-6")
    assert partial.status_code == 206
    assert b"".join(partial.streaming_content) == payload[2:7]
    assert partial["Content-Range"] == f"bytes 2-6/{len(payload)}"
    assert partial["Content-Length"] == "5"
    assert partial["Accept-Ranges"] == "bytes"
    assert partial["ETag"] == f'"{digest}"'

    suffix = client.get(url, HTTP_RANGE="bytes=-5")
    assert suffix.status_code == 206
    assert b"".join(suffix.streaming_content) == payload[-5:]

    open_ended = client.get(url, HTTP_RANGE="bytes=10-")
    assert open_ended.status_code == 206
    assert b"".join(open_ended.streaming_content) == payload[10:]


@pytest.mark.django_db
def test_signed_media_rejects_invalid_or_multiple_ranges(client, tmp_path, settings):
    _organization, _media, payload, _digest, url = _stored_media(
        client, tmp_path, settings, slug="invalid-range-club"
    )
    beyond = client.get(url, HTTP_RANGE="bytes=999-")
    assert beyond.status_code == 416
    assert beyond["Content-Range"] == f"bytes */{len(payload)}"

    multiple = client.get(url, HTTP_RANGE="bytes=0-1,3-4")
    assert multiple.status_code == 416


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
        organization=organization,
        gymnast=gymnast,
        kind=MediaAsset.Kind.DRILL,
        state=MediaAsset.State.STORED,
        recorded_at=datetime.now(UTC),
        object_key="missing.mp4",
        sha256="a" * 64,
    )
    url = reverse("media-object-download", args=[media.id])
    assert client.get(url).status_code == 403
    assert client.get(url + "?access=tampered.token").status_code == 403
