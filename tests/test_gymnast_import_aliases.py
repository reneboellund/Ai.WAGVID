import pytest

from wagvid_app.imports import commit_gymnast_import, preview_gymnast_csv
from wagvid_app.models import Gymnast, Level, Organization


@pytest.mark.django_db
def test_gymnast_import_accepts_semicolon_alias_headers():
    organization = Organization.objects.create(name="Import Club", slug="import-club")
    Level.objects.create(organization=organization, name="Trin 4")
    preview = preview_gymnast_csv(
        organization,
        "Navn;Licensnummer;Niveau;Disciplin;KIGA ID\n"
        "Ada Import;DK-200;trin 4;WAG;KIGA-200\n",
    )
    assert preview.can_commit is True
    assert preview.valid_rows[0]["level"] == "Trin 4"
    assert preview.valid_rows[0]["discipline"] == Gymnast.Discipline.WAG
    created = commit_gymnast_import(organization, preview)
    assert created[0].kiga_id == "KIGA-200"


@pytest.mark.django_db
def test_gymnast_import_rejects_ambiguous_alias_columns():
    organization = Organization.objects.create(name="Alias Club", slug="alias-club")
    Level.objects.create(organization=organization, name="Trin 4")
    preview = preview_gymnast_csv(
        organization,
        "name,Navn,license_number,level\nOne,Other,DK-1,Trin 4\n",
    )
    assert preview.can_commit is False
    assert preview.errors[0].field == "header"
    assert "Ambiguous columns" in preview.errors[0].message
