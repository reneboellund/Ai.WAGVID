import csv
import io
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


REQUIRED_GYMNAST_COLUMNS = {"name", "license_number", "level"}


def preview_gymnast_csv(organization: Organization, content: str) -> GymnastImportPreview:
    preview = GymnastImportPreview()
    reader = csv.DictReader(io.StringIO(content))
    missing = REQUIRED_GYMNAST_COLUMNS - set(reader.fieldnames or [])
    if missing:
        preview.errors.append(
            ImportErrorRow(1, "header", f"Missing columns: {', '.join(sorted(missing))}")
        )
        return preview
    existing = set(organization.gymnasts.values_list("license_number", flat=True))
    seen: set[str] = set()
    levels = set(organization.levels.filter(active=True).values_list("name", flat=True))
    for row_number, raw in enumerate(reader, start=2):
        row = {key: (value or "").strip() for key, value in raw.items()}
        license_number = row["license_number"]
        if not row["name"]:
            preview.errors.append(ImportErrorRow(row_number, "name", "Name is required"))
        if not license_number:
            preview.errors.append(
                ImportErrorRow(row_number, "license_number", "License number is required")
            )
        elif license_number in existing or license_number in seen:
            preview.errors.append(
                ImportErrorRow(row_number, "license_number", "Duplicate license number")
            )
        if row["level"] not in levels:
            preview.errors.append(ImportErrorRow(row_number, "level", "Unknown active level"))
        discipline = row.get("discipline", Gymnast.Discipline.WAG).upper()
        if discipline not in Gymnast.Discipline.values:
            preview.errors.append(
                ImportErrorRow(row_number, "discipline", "Discipline must be WAG or MAG")
            )
        row["discipline"] = discipline
        seen.add(license_number)
        if not any(error.row == row_number for error in preview.errors):
            preview.valid_rows.append(row)
    return preview


@transaction.atomic
def commit_gymnast_import(
    organization: Organization, preview: GymnastImportPreview
) -> list[Gymnast]:
    if not preview.can_commit:
        raise ValueError("Import preview is not commit-ready")
    levels = {level.name: level for level in organization.levels.filter(active=True)}
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
