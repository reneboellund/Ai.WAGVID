import copy
from pathlib import Path

import pytest
import yaml

from ai_wagvid.dataset_manifest import DatasetManifestError, load_dataset_manifest

SCHEMA = Path("schemas/dataset-manifest-v1.schema.json")


def manifest():
    return {
        "schema_version": "dataset-manifest-v1",
        "dataset": {
            "id": "approved-research-set",
            "version": "2026-08-16",
            "title": "Approved research fixture",
            "source_url": "https://example.invalid/dataset",
            "retrieved_at": "2026-08-16T10:00:00Z",
        },
        "governance": {
            "access_basis": "Written project approval",
            "approved_by": "research-owner",
            "approved_at": "2026-08-16T09:00:00Z",
            "allowed_uses": ["internal research"],
            "personal_data": "pseudonymous",
        },
        "split_policy": {"salt": "v1", "train": 0.7, "validation": 0.15, "test": 0.15},
        "samples": [
            {
                "id": "routine-a",
                "athlete_group_id": "athlete-1",
                "event_group_id": "event-1",
                "routine_group_id": "routine-1",
                "source_sha256": "a" * 64,
                "media_uri": "local://immutable/routine-a.mp4",
                "official_score": {"d_score": 5.2, "e_score": 8.1, "total": 13.3},
            },
            {
                "id": "routine-b",
                "athlete_group_id": "athlete-1",
                "event_group_id": "event-2",
                "routine_group_id": "routine-2",
                "source_sha256": "b" * 64,
                "media_uri": "local://immutable/routine-b.mp4",
            },
        ],
    }


def write(tmp_path, value):
    path = tmp_path / "manifest.yaml"
    path.write_text(yaml.safe_dump(value), encoding="utf-8")
    return path


def test_manifest_validates_and_materialises_leakage_safe_assignments(tmp_path):
    result = load_dataset_manifest(write(tmp_path, manifest()), schema_path=SCHEMA)
    assert result["assignments"]["routine-a"] == result["assignments"]["routine-b"]


@pytest.mark.parametrize(
    "mutation, message",
    [
        (lambda value: value["governance"].pop("approved_by"), "approved_by"),
        (lambda value: value["split_policy"].update(train=0.8), "sum to 1"),
        (lambda value: value["samples"].append(copy.deepcopy(value["samples"][0])), "unique"),
    ],
)
def test_manifest_fails_closed_for_missing_approval_bad_ratio_or_duplicate_id(
    tmp_path, mutation, message
):
    value = manifest()
    mutation(value)
    with pytest.raises(DatasetManifestError, match=message):
        load_dataset_manifest(write(tmp_path, value), schema_path=SCHEMA)
