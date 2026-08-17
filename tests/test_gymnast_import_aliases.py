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


@pytest.mark.django_db
def test_gymnast_import_rejects_existing_and_in_file_kiga_ids():
    organization = Organization.objects.create(name="Identity Club", slug="identity-club")
    level = Level.objects.create(organization=organization, name="Trin 4")
    Gymnast.objects.create(
        organization=organization,
        display_name="Existing",
        license_number="DK-EXISTING",
        level=level,
        kiga_id="KIGA-EXISTING",
    )
    preview = preview_gymnast_csv(
        organization,
        "name,license_number,level,kiga_id\n"
        "One,DK-1,Trin 4,KIGA-EXISTING\n"
        "Two,DK-2,Trin 4,KIGA-NEW\n"
        "Three,DK-3,Trin 4,KIGA-NEW\n",
    )
    assert preview.can_commit is False
    kiga_errors = [error for error in preview.errors if error.field == "kiga_id"]
    assert [error.row for error in kiga_errors] == [2, 4]


@pytest.mark.django_db
def test_gymnast_import_revalidates_kiga_identity_at_commit():
    organization = Organization.objects.create(name="Race Club", slug="race-club")
    level = Level.objects.create(organization=organization, name="Trin 4")
    preview = preview_gymnast_csv(
        organization,
        "name,license_number,level,kiga_id\nOne,DK-1,Trin 4,KIGA-RACE\n",
    )
    assert preview.can_commit is True
    Gymnast.objects.create(
        organization=organization,
        display_name="Concurrent",
        license_number="DK-2",
        level=level,
        kiga_id="KIGA-RACE",
    )
    with pytest.raises(ValueError, match="KIGA IDs now exist"):
        commit_gymnast_import(organization, preview)
