import hashlib
from datetime import UTC, datetime

import pytest
from django.contrib.auth.models import User
from django.urls import reverse

from wagvid_app.media_timeline_store import (
    load_media_timeline,
    persist_media_timeline,
    timeline_exists,
    timeline_object_key,
)
from wagvid_app.models import Gymnast, Level, MediaAsset, Membership, Organization


def ffprobe_payload():
    return {
        "streams": [{"index": 0, "codec_type": "video", "time_base": "1/1000"}],
        "frames": [
            {
                "media_type": "video",
                "stream_index": 0,
                "pts": "0",
                "pkt_dts": "0",
                "best_effort_timestamp": "0",
                "duration": "40",
                "key_frame": 1,
            },
            {
                "media_type": "video",
                "stream_index": 0,
                "pts": "40",
                "pkt_dts": "40",
                "best_effort_timestamp": "40",
                "duration": "45",
                "key_frame": 0,
            },
            {
                "media_type": "video",
                "stream_index": 0,
                "pts": "85",
                "pkt_dts": "85",
                "best_effort_timestamp": "85",
                "duration": "35",
                "key_frame": 0,
            },
        ],
    }


def make_media(*, organization, gymnast):
    digest = hashlib.sha256(b"canonical-source").hexdigest()
    return MediaAsset.objects.create(
        organization=organization,
        gymnast=gymnast,
        kind=MediaAsset.Kind.DRILL,
        state=MediaAsset.State.STORED,
        recorded_at=datetime.now(UTC),
        object_key="org/source.mp4",
        sha256=digest,
        content_type="video/mp4",
    )


@pytest.mark.django_db
def test_canonical_timeline_sidecar_round_trip(tmp_path, settings):
    settings.WAGVID_OBJECT_ROOT = tmp_path
    organization = Organization.objects.create(name="Club", slug="timeline-club")
    level = Level.objects.create(organization=organization, name="Level")
    gymnast = Gymnast.objects.create(
        organization=organization, display_name="Ada", license_number="T-1", level=level
    )
    media = make_media(organization=organization, gymnast=gymnast)

    timeline = persist_media_timeline(media, ffprobe_payload())
    assert timeline_exists(media)
    assert timeline_object_key(media).endswith("canonical-media-timeline-v1.json")

    loaded = load_media_timeline(media)
    assert loaded.digest == timeline.digest
    assert [loaded.timestamp_s(index) for index in range(3)] == [0.0, 0.04, 0.085]
    assert loaded.diagnostics.variable_frame_rate is True


@pytest.mark.django_db
def test_timeline_api_is_org_scoped_and_returns_canonical_frame_times(client, tmp_path, settings):
    settings.WAGVID_OBJECT_ROOT = tmp_path
    organization = Organization.objects.create(name="Club", slug="timeline-api-club")
    level = Level.objects.create(organization=organization, name="Level")
    gymnast = Gymnast.objects.create(
        organization=organization, display_name="Ada", license_number="T-2", level=level
    )
    media = make_media(organization=organization, gymnast=gymnast)
    persist_media_timeline(media, ffprobe_payload())

    user = User.objects.create_user("timeline-reviewer", password="secret")
    Membership.objects.create(
        user=user, organization=organization, role=Membership.Role.REVIEWER
    )
    client.force_login(user)
    response = client.get(reverse("media-timeline", args=[media.id]))
    assert response.status_code == 200
    payload = response.json()
    assert payload["source_sha256"] == media.sha256
    assert len(payload["timeline_digest"]) == 64
    assert [item["timestamp_s"] for item in payload["frames"]] == [0.0, 0.04, 0.085]
    assert payload["frames"][0]["key_frame"] is True
    assert response["Cache-Control"] == "private, no-store"

    other = Organization.objects.create(name="Other", slug="timeline-other")
    other_user = User.objects.create_user("timeline-other-user", password="secret")
    Membership.objects.create(user=other_user, organization=other, role=Membership.Role.REVIEWER)
    client.force_login(other_user)
    assert client.get(reverse("media-timeline", args=[media.id])).status_code == 404


@pytest.mark.django_db
def test_timeline_api_reports_not_ready_without_sidecar(client, tmp_path, settings):
    settings.WAGVID_OBJECT_ROOT = tmp_path
    organization = Organization.objects.create(name="Club", slug="timeline-missing-club")
    level = Level.objects.create(organization=organization, name="Level")
    gymnast = Gymnast.objects.create(
        organization=organization, display_name="Ada", license_number="T-3", level=level
    )
    media = make_media(organization=organization, gymnast=gymnast)
    user = User.objects.create_user("timeline-missing-user", password="secret")
    Membership.objects.create(user=user, organization=organization, role=Membership.Role.REVIEWER)
    client.force_login(user)
    response = client.get(reverse("media-timeline", args=[media.id]))
    assert response.status_code == 404
    assert response.json()["error"] == "canonical-timeline-not-ready"
