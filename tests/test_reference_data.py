from pathlib import Path

import pytest

from ai_wagvid.reference_data import ReferenceDataError, load_label_map, verify_artifacts


def test_starter_label_maps_are_valid_and_explicitly_unmapped():
    for path in Path("research/label-maps").glob("*.yaml"):
        labels = load_label_map(path)
        assert labels
        assert not any(item.status == "mapped" for item in labels.values())


def test_artifact_manifest_reports_absent_files_without_downloading(tmp_path):
    checks = verify_artifacts(Path("research/artifacts.yaml"), artifact_root=tmp_path)
    assert checks
    assert {item.status for item in checks} == {"missing"}


def test_label_map_rejects_duplicate_indices(tmp_path):
    path = tmp_path / "map.yaml"
    path.write_text("""schema_version: label-map-v1
labels:
  - {source_index: 0, source_label: a, status: excluded}
  - {source_index: 0, source_label: b, status: ambiguous}
""", encoding="utf-8")
    with pytest.raises(ReferenceDataError, match="unique"):
        load_label_map(path)
