"""Versioned, idempotent KIGA competition/video exchange boundary."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, time
from decimal import Decimal
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.db import transaction
from jsonschema import Draft202012Validator, FormatChecker

from .models import (
    Event,
    ExternalMediaReference,
    Gymnast,
    OfficialResultSnapshot,
    Organization,
    Routine,
)


class KigaImportError(ValueError):
    pass


@dataclass(frozen=True)
class KigaPreview:
    valid: bool
    errors: tuple[str, ...]
    actions: tuple[str, ...]
    payload: dict[str, Any] | None


def preview_kiga_record(
    organization: Organization,
    content: str,
    *,
    schema_path: Path = Path("schemas/competition-video-v1.schema.json"),
) -> KigaPreview:
    try:
        payload = json.loads(content)
    except json.JSONDecodeError as error:
        return KigaPreview(False, (f"Invalid JSON: {error}",), (), None)
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    errors = [
        f"{'/'.join(map(str, error.absolute_path)) or '<root>'}: {error.message}"
        for error in sorted(
            Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(payload),
            key=lambda item: list(item.absolute_path),
        )
    ]
    if errors:
        return KigaPreview(False, tuple(errors), (), payload)
    routine_data = payload["routine"]
    athlete = organization.gymnasts.filter(kiga_id=routine_data["athlete_external_id"]).first()
    if not athlete:
        errors.append(
            f"No active gymnast mapping for KIGA athlete {routine_data['athlete_external_id']}"
        )
    elif athlete.archived_at:
        errors.append("Mapped gymnast is archived")
    if athlete:
        allowed = {
            Gymnast.Discipline.WAG: {"VT", "UB", "BB", "FX"},
            Gymnast.Discipline.MAG: {"VT", "FX", "PH", "SR", "PB", "HB"},
        }
        if routine_data["apparatus"] not in allowed[athlete.discipline]:
            errors.append("Apparatus is incompatible with the mapped gymnast discipline")
    try:
        ZoneInfo(payload["competition"]["timezone"])
    except ZoneInfoNotFoundError:
        errors.append("Competition timezone is not recognized")
    actions = (
        f"upsert competition {payload['competition']['external_id']}",
        f"upsert routine {routine_data['external_id']}",
        f"catalogue {len(payload['media'])} media reference(s)",
        f"append official result {payload['official_result'].get('result_version', 'unversioned')}",
    )
    return KigaPreview(not errors, tuple(errors), actions, payload)


def _datetime(value: str) -> datetime:
    return datetime.fromisoformat(value)


@transaction.atomic
def commit_kiga_record(
    organization: Organization, preview: KigaPreview
) -> tuple[Event, Routine, list[ExternalMediaReference], OfficialResultSnapshot]:
    if not preview.valid or not preview.payload:
        raise KigaImportError("KIGA preview is not commit-ready")
    payload = preview.payload
    competition = payload["competition"]
    routine_data = payload["routine"]
    rights = payload["rights"]
    gymnast = Gymnast.objects.select_for_update().get(
        organization=organization,
        kiga_id=routine_data["athlete_external_id"],
        archived_at__isnull=True,
    )
    zone = ZoneInfo(competition["timezone"])
    start_date = datetime.fromisoformat(competition["start_date"]).date()
    end_date_raw = competition.get("end_date")
    defaults = {
        "name": competition["name"],
        "kind": Event.Kind.COMPETITION,
        "starts_at": datetime.combine(start_date, time.min, tzinfo=zone),
        "ends_at": (
            datetime.combine(datetime.fromisoformat(end_date_raw).date(), time.max, tzinfo=zone)
            if end_date_raw
            else None
        ),
        "venue": competition.get("venue") or "",
        "timezone_name": competition["timezone"],
        "city": competition.get("city") or "",
        "country_code": competition.get("country_code") or "",
        "organizer": competition.get("organizer") or "",
        "federation": competition.get("federation") or "",
        "competition_level": competition.get("competition_level") or "",
        "rule_profile": competition.get("rule_profile") or "",
        "external_source": competition.get("provider") or "KIGA",
    }
    event, _ = Event.objects.update_or_create(
        organization=organization, external_id=competition["external_id"], defaults=defaults
    )
    routine, _ = Routine.objects.update_or_create(
        event=event,
        external_id=routine_data["external_id"],
        defaults={
            "organization": organization,
            "gymnast": gymnast,
            "apparatus": routine_data["apparatus"],
            "category": routine_data.get("competition_category") or "",
            "age_category": routine_data.get("age_category") or "",
            "round_name": routine_data.get("round") or "",
            "rotation": routine_data.get("rotation"),
            "start_order": routine_data.get("start_order"),
            "performed_at": _datetime(routine_data["performed_at"]),
            "rulepack_id": competition.get("rule_profile") or "unresolved",
        },
    )
    references = []
    provider = competition.get("provider") or "KIGA"
    for media in payload["media"]:
        reference, _ = ExternalMediaReference.objects.update_or_create(
            organization=organization,
            provider=provider,
            external_media_id=media["media_id"],
            defaults={
                "routine": routine,
                "download_uri": media["download_uri"],
                "sha256": media["sha256"],
                "captured_at": _datetime(media["captured_at"]),
                "content_type": media["content_type"],
                "size_bytes": media.get("size_bytes"),
                "duration_ms": media.get("duration_ms"),
                "camera_id": media.get("camera_id") or "",
                "view": media.get("view") or "",
                "download_allowed": rights["download_allowed"],
                "analysis_allowed": rights["analysis_allowed"],
                "training_allowed": rights["training_allowed"],
                "retention_until": rights.get("retention_until"),
                "consent_reference": rights.get("consent_reference") or "",
                "access_policy": rights.get("access_policy") or "",
                "state": (
                    ExternalMediaReference.State.READY
                    if rights["download_allowed"] and rights["analysis_allowed"]
                    else ExternalMediaReference.State.BLOCKED
                ),
            },
        )
        references.append(reference)
    official = payload["official_result"]
    scores = official["scores"]
    version = official.get("result_version") or official["captured_at"]
    snapshot, snapshot_created = OfficialResultSnapshot.objects.get_or_create(
        routine=routine,
        provider=provider,
        result_version=version,
        defaults={
            "source": official["source"],
            "status": official["status"],
            "d_score": scores.get("d"),
            "e_score": scores.get("e"),
            "artistry": scores.get("artistry"),
            "neutral": scores.get("neutral"),
            "final_score": scores["final"],
            "source_captured_at": _datetime(official["captured_at"]),
        },
    )
    if not snapshot_created:
        expected = {
            "status": official["status"],
            "d_score": Decimal(str(scores["d"])) if scores.get("d") is not None else None,
            "e_score": Decimal(str(scores["e"])) if scores.get("e") is not None else None,
            "neutral": (
                Decimal(str(scores["neutral"])) if scores.get("neutral") is not None else None
            ),
            "final_score": Decimal(str(scores["final"])),
        }
        if any(getattr(snapshot, field) != value for field, value in expected.items()):
            raise KigaImportError("Official result version was reused with changed values")
    if official["status"] != "withdrawn":
        routine.official_d_score = Decimal(str(scores["d"])) if scores.get("d") is not None else None
        routine.official_e_score = Decimal(str(scores["e"])) if scores.get("e") is not None else None
        routine.official_neutral = (
            Decimal(str(scores["neutral"])) if scores.get("neutral") is not None else None
        )
        routine.official_final_score = Decimal(str(scores["final"]))
        routine.official_frozen_at = _datetime(official["captured_at"])
        routine.save(
            update_fields=[
                "official_d_score",
                "official_e_score",
                "official_neutral",
                "official_final_score",
                "official_frozen_at",
                "updated_at",
            ]
        )
    return event, routine, references, snapshot
