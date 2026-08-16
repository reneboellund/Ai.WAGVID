"""Validation and split materialisation for research dataset manifests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator, FormatChecker

from .dataset_splits import DatasetSample, SplitRatios, assign_splits


class DatasetManifestError(ValueError):
    """Raised when a manifest is structurally or semantically unsafe."""


def load_dataset_manifest(path: Path, *, schema_path: Path) -> dict[str, Any]:
    manifest = yaml.safe_load(path.read_text(encoding="utf-8"))
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    errors = sorted(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(manifest),
        key=lambda error: list(error.absolute_path),
    )
    if errors:
        details = "; ".join(
            f"{'/'.join(map(str, error.absolute_path)) or '<root>'}: {error.message}"
            for error in errors
        )
        raise DatasetManifestError(details)

    split = manifest["split_policy"]
    try:
        ratios = SplitRatios(split["train"], split["validation"], split["test"])
        samples = tuple(
            DatasetSample(
                sample_id=item["id"],
                dataset_id=manifest["dataset"]["id"],
                athlete_group_id=item["athlete_group_id"],
                event_group_id=item["event_group_id"],
                routine_group_id=item["routine_group_id"],
                source_sha256=item["source_sha256"],
            )
            for item in manifest["samples"]
        )
        assignments = assign_splits(samples, salt=split["salt"], ratios=ratios)
    except ValueError as error:
        raise DatasetManifestError(str(error)) from error

    manifest["assignments"] = {
        sample_id: assignment.value for sample_id, assignment in sorted(assignments.items())
    }
    return manifest
