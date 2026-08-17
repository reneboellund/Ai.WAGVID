import csv
import hashlib
import io
import json
import re
from dataclasses import dataclass, field

from django.db import transaction

from .models import Gymnast, Organization


@dataclass(frozen=True)
class ImportErrorRow:
    row: int
    field: str
    message: str


@dataclass
class GymnastImportPreview:
    valid_rows: list[dict[str, str]] = field(default_factory=list)
    errors: list[ImportErrorRow] = field(default_factory=list)

    @property
    def can_commit(self) -> bool:
        return bool(self.valid_rows) and not self.errors

    @property
    def digest(self) -> str:
        value = {
            "valid_rows": self.valid_rows,
            "errors": [error.__dict__ for error in self.errors],
        }
        encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(encoded).hexdigest()

    def error_report_csv(self) -> str:
        output = io.StringIO(newline="")
        writer = csv.writer(output)
        writer.writerow(["row", "field", "message"])
        for error in self.errors:
            writer.writerow([error.row, error.field, error.message])
        return output.getvalue()


REQUIRED_GYMNAST_COLUMNS = {"name", "license_number", "level"}
GYMNAST_COLUMN_ALIASES = {
    "name": "name",
    "navn": "name",
    "gymnast": "name",
    "gymnast_name": "name",
    "display_name": "name",
    "license_number": "license_number",
    "license": "license_number",
    "licens": "license_number",
    "licensnummer": "license_number",
    "licens_nummer": "license_number",
    "level": "level",
    "niveau": "level",
    "trin": "level",
    "discipline": "discipline",
    "disciplin": "discipline",
    "kiga_id": "kiga_id",
    "kiga": "kiga_id",
}
DISCIPLINE_ALIASES = {
    "WAG": Gymnast.Discipline.WAG,
    "KVINDER": Gymnast.Discipline.WAG,
    "WOMEN": Gymnast.Discipline.WAG,
    "MAG": Gymnast.Discipline.MAG,
    "MÆND": Gymnast.Discipline.MAG,
    "MAEND": Gymnast.Discipline.MAG,
    "MEN": Gymnast.Discipline.MAG,
}


def _normalize_header(value: str) -> str:
    normalized = value.lstrip("\ufeff").strip().lower()
    normalized = re.sub(r"[\s\-/]+", "_", normalized)
    return re.sub(r"_+", "_", normalized).strip("_")


def _dialect_for(content: str):
    try:
        return csv.Sniffer().sniff(content[:4096], delimiters=",;\t")
    except csv.Error:
        return csv.excel


def _header_map(fieldnames: list[str] | None) -> tuple[dict[str, str], list[str]]:
    mapping: dict[str, str] = {}
    canonical_sources: dict[str, list[str]] = {}
    for original in fieldnames or []:
        normalized = _normalize_header(original)
        canonical = GYMNAST_COLUMN_ALIASES.get(normalized, normalized)
        mapping[original] = canonical
        canonical_sources.setdefault(canonical, []).append(original)
    ambiguous = [
        canonical
        for canonical, sources in canonical_sources.items()
        if len(sources) > 1 and canonical in GYMNAST_COLUMN_ALIASES.values()
    ]
    return mapping, sorted(ambiguous)


def preview_gymnast_csv(organization: Organization, content: str) -> GymnastImportPreview:
    preview = GymnastImportPreview()
    reader = csv.DictReader(io.StringIO(content), dialect=_dialect_for(content))
    mapping, ambiguous = _header_map(reader.fieldnames)
    if ambiguous:
        preview.errors.append(
            ImportErrorRow(
                1,
                "header",
                "Ambiguous columns map to the same field: " + ", ".join(ambiguous),
            )
        )
        return preview
    canonical_headers = set(mapping.values())
    missing = REQUIRED_GYMNAST_COLUMNS - canonical_headers
    if missing:
        preview.errors.append(
            ImportErrorRow(1, "header", f"Missing columns: {', '.join(sorted(missing))}")
        )
        return preview

    existing_licenses = set(organization.gymnasts.values_list("license_number", flat=True))
    existing_kiga_ids = set(
        organization.gymnasts.exclude(kiga_id="").values_list("kiga_id", flat=True)
    )
    seen_licenses: set[str] = set()
    seen_kiga_ids: set[str] = set()
    levels_by_key = {
        level.name.casefold(): level.name
        for level in organization.levels.filter(active=True)
    }
    for row_number, raw in enumerate(reader, start=2):
        row = {
            mapping.get(key, _normalize_header(key)): (value or "").strip()
            for key, value in raw.items()
            if key is not None
        }
        license_number = row["license_number"]
        if not row["name"]:
            preview.errors.append(ImportErrorRow(row_number, "name", "Name is required"))
        if not license_number:
            preview.errors.append(
                ImportErrorRow(row_number, "license_number", "License number is required")
            )
        elif license_number in existing_licenses or license_number in seen_licenses:
            preview.errors.append(
                ImportErrorRow(row_number, "license_number", "Duplicate license number")
            )

        kiga_id = row.get("kiga_id", "").strip()
        row["kiga_id"] = kiga_id
        if kiga_id and (kiga_id in existing_kiga_ids or kiga_id in seen_kiga_ids):
            preview.errors.append(ImportErrorRow(row_number, "kiga_id", "Duplicate KIGA ID"))

        level_key = row["level"].casefold()
        canonical_level = levels_by_key.get(level_key)
        if canonical_level is None:
            preview.errors.append(ImportErrorRow(row_number, "level", "Unknown active level"))
        else:
            row["level"] = canonical_level

        raw_discipline = row.get("discipline", Gymnast.Discipline.WAG).strip().upper()
        discipline = DISCIPLINE_ALIASES.get(raw_discipline)
        if discipline is None:
            preview.errors.append(
                ImportErrorRow(row_number, "discipline", "Discipline must be WAG or MAG")
            )
        else:
            row["discipline"] = discipline

        if license_number:
            seen_licenses.add(license_number)
        if kiga_id:
            seen_kiga_ids.add(kiga_id)
        if not any(error.row == row_number for error in preview.errors):
            preview.valid_rows.append(row)
    return preview


@transaction.atomic
def commit_gymnast_import(
    organization: Organization, preview: GymnastImportPreview
) -> list[Gymnast]:
    if not preview.can_commit:
        raise ValueError("Import preview is not commit-ready")
    Organization.objects.select_for_update().get(pk=organization.pk)
    licenses = [row["license_number"] for row in preview.valid_rows]
    license_conflicts = set(
        Gymnast.objects.filter(
            organization=organization, license_number__in=licenses
        ).values_list("license_number", flat=True)
    )
    if license_conflicts:
        raise ValueError(
            "Import preview is stale; license numbers now exist: "
            + ", ".join(sorted(license_conflicts))
        )
    kiga_ids = [row.get("kiga_id", "") for row in preview.valid_rows if row.get("kiga_id", "")]
    kiga_conflicts = set(
        Gymnast.objects.filter(organization=organization, kiga_id__in=kiga_ids).values_list(
            "kiga_id", flat=True
        )
    )
    if kiga_conflicts:
        raise ValueError(
            "Import preview is stale; KIGA IDs now exist: " + ", ".join(sorted(kiga_conflicts))
        )
    levels = {level.name: level for level in organization.levels.filter(active=True)}
    missing_levels = {row["level"] for row in preview.valid_rows} - set(levels)
    if missing_levels:
        raise ValueError(
            "Import preview is stale; levels are no longer active: "
            + ", ".join(sorted(missing_levels))
        )
    created = [
        Gymnast(
            organization=organization,
            display_name=row["name"],
            license_number=row["license_number"],
            discipline=row["discipline"],
            level=levels[row["level"]],
            kiga_id=row.get("kiga_id", ""),
        )
        for row in preview.valid_rows
    ]
    return Gymnast.objects.bulk_create(created)
