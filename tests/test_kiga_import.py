import copy
import io
import json
from decimal import Decimal
from pathlib import Path

import pytest
from django.contrib.auth.models import User
from django.urls import reverse
from jsonschema import Draft202012Validator, FormatChecker

from wagvid_app.kiga import KigaImportError, commit_kiga_record, preview_kiga_record
from wagvid_app.models import (
    Event,
    ExternalMediaReference,
    Gymnast,
    Level,
    Membership,
    OfficialResultSnapshot,
    Organization,
    Routine,
)


def record():
    return {
        "schema": "ai.wagvid.competition-video.v1",
        "record_id": "record-1",
        "created_at": "2026-08-16T12:00:00Z",
        "competition": {
            "external_id": "kiga-event-1",
            "provider": "KIGA",
            "name": "Nordic Cup",
            "start_date": "2026-08-20",
            "end_date": "2026-08-21",
            "timezone": "Europe/Copenhagen",
            "venue": "Arena",
            "city": "Aarhus",
            "country_code": "DK",
            "organizer": "Club",
            "federation": "Federation",
            "competition_level": "Senior",
            "rule_profile": "fig-wag@2025",
        },
        "routine": {
            "external_id": "kiga-routine-1",
            "athlete_external_id": "kiga-athlete-1",
            "team_external_id": None,
            "apparatus": "BB",
            "round": "Final",
            "rotation": 2,
            "start_order": 4,
            "performed_at": "2026-08-20T14:05:00+02:00",
            "age_category": "Senior",
            "competition_category": "A",
        },
        "media": [
            {
                "media_id": "kiga-media-1",
                "camera_id": "cam-1",
                "view": "side",
                "download_uri": "https://kiga.invalid/media/1",
                "sha256": "a" * 64,
                "captured_at": "2026-08-20T14:05:00+02:00",
                "content_type": "video/mp4",
                "size_bytes": 1000,
                "duration_ms": 90000,
            }
        ],
        "official_result": {
            "source": "KIGA result service",
            "status": "official",
            "captured_at": "2026-08-20T15:00:00+02:00",
            "result_version": "v1",
            "scores": {"d": 5.2, "e": 8.1, "artistry": None, "neutral": 0, "final": 13.3},
        },
        "rights": {
            "download_allowed": True,
            "analysis_allowed": True,
            "training_allowed": False,
            "retention_until": "2027-08-20",
            "consent_reference": "consent-1",
            "access_policy": "club-reviewers",
        },
    }


def setup_org(role=Membership.Role.ORGANIZATION_ADMIN):
    user = User.objects.create_user(f"kiga-{role}")
    organization = Organization.objects.create(name="KIGA Club", slug=f"kiga-{role}")
    Membership.objects.create(user=user, organization=organization, role=role)
    level = Level.objects.create(organization=organization, name="Senior")
    Gymnast.objects.create(
        organization=organization,
        level=level,
        display_name="Ada",
        license_number="KIGA-1",
        kiga_id="kiga-athlete-1",
    )
    return user, organization


@pytest.mark.django_db
def test_preview_requires_stable_gymnast_mapping_and_valid_discipline():
    _, organization = setup_org()
    missing = record()
    missing["routine"]["athlete_external_id"] = "unknown"
    preview = preview_kiga_record(organization, json.dumps(missing))
    assert not preview.valid and "No active gymnast mapping" in preview.errors[0]
    invalid = record()
    invalid["routine"]["apparatus"] = "PH"
    preview = preview_kiga_record(organization, json.dumps(invalid))
    assert not preview.valid


@pytest.mark.django_db
def test_commit_is_idempotent_and_preserves_versioned_result_and_rights():
    _, organization = setup_org()
    preview = preview_kiga_record(organization, json.dumps(record()))
    event, routine, references, snapshot = commit_kiga_record(organization, preview)
    commit_kiga_record(organization, preview)
    assert Event.objects.count() == Routine.objects.count() == 1
    assert ExternalMediaReference.objects.count() == OfficialResultSnapshot.objects.count() == 1
    assert event.timezone_name == "Europe/Copenhagen"
    assert routine.official_final_score == Decimal("13.300")
    assert references[0].state == ExternalMediaReference.State.READY
    assert references[0].training_allowed is False
    with pytest.raises(ValueError, match="append-only"):
        snapshot.delete()


@pytest.mark.django_db
def test_changed_official_values_require_new_result_version_and_rights_can_block_media():
    _, organization = setup_org()
    value = record()
    commit_kiga_record(organization, preview_kiga_record(organization, json.dumps(value)))
    value["official_result"]["scores"]["final"] = 13.2
    with pytest.raises(KigaImportError, match="reused"):
        commit_kiga_record(organization, preview_kiga_record(organization, json.dumps(value)))
    value["official_result"]["result_version"] = "v2"
    value["rights"]["analysis_allowed"] = False
    _, routine, references, _ = commit_kiga_record(
        organization, preview_kiga_record(organization, json.dumps(value))
    )
    assert OfficialResultSnapshot.objects.count() == 2
    assert routine.official_final_score == Decimal("13.200")
    assert references[0].state == ExternalMediaReference.State.BLOCKED


@pytest.mark.django_db
def test_admin_dry_run_commit_and_competition_ui(client):
    user, organization = setup_org()
    client.force_login(user)
    upload = io.BytesIO(json.dumps(record()).encode())
    upload.name = "kiga.json"
    preview = client.post(reverse("kiga-import-preview"), {"json_file": upload})
    assert preview.status_code == 200
    assert "Ingen data er skrevet endnu" in preview.content.decode()
    assert Event.objects.count() == 0
    committed = client.post(reverse("kiga-import-commit"))
    assert committed.status_code == 302
    page = client.get(reverse("competitions"))
    body = page.content.decode()
    assert "Nordic Cup" in body and "13,300" in body
    assert organization.audit_events.filter(action="kiga.competition-video-imported").exists()


@pytest.mark.django_db
def test_non_admin_cannot_import_and_withdrawn_result_does_not_replace_current(client):
    user, organization = setup_org(role=Membership.Role.COACH)
    client.force_login(user)
    upload = io.BytesIO(json.dumps(record()).encode())
    upload.name = "kiga.json"
    assert client.post(reverse("kiga-import-preview"), {"json_file": upload}).status_code == 403

    value = copy.deepcopy(record())
    value["official_result"]["status"] = "withdrawn"
    _, routine, _, _ = commit_kiga_record(
        organization, preview_kiga_record(organization, json.dumps(value))
    )
    assert routine.official_final_score is None


@pytest.mark.django_db
def test_kiga_round_trip_export_matches_schema_and_is_audited(client):
    user, organization = setup_org()
    _, routine, _, _ = commit_kiga_record(
        organization, preview_kiga_record(organization, json.dumps(record()))
    )
    client.force_login(user)
    response = client.get(reverse("kiga-routine-export", args=[routine.id]))
    assert response.status_code == 200
    schema = json.loads(Path("schemas/competition-video-v1.schema.json").read_text(encoding="utf-8"))
    assert list(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(response.json())
    ) == []
    assert response.json()["learning"]["eligible"] is False
    assert organization.audit_events.filter(action="kiga.routine-exported").exists()
