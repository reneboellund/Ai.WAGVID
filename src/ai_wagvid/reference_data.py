"""Validation and loading of research label maps and artifact references."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .model_adapters import LabelMapping


class ReferenceDataError(ValueError):
    pass


def load_label_map(path: Path) -> dict[int, LabelMapping]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if value.get("schema_version") != "label-map-v1":
        raise ReferenceDataError("unsupported label map schema")
    result: dict[int, LabelMapping] = {}
    source_labels: set[str] = set()
    for item in value.get("labels", []):
        index = item["source_index"]
        source = item["source_label"]
        status = item["status"]
        canonical = item.get("canonical_label")
        if index in result or source in source_labels:
            raise ReferenceDataError("source indices and labels must be unique")
        if status == "mapped" and not canonical:
            raise ReferenceDataError("mapped labels require canonical_label")
        if status not in {"mapped", "ambiguous", "excluded"}:
            raise ReferenceDataError(f"invalid mapping status: {status}")
        result[index] = LabelMapping(source, canonical, status)
        source_labels.add(source)
    if not result:
        raise ReferenceDataError("label map cannot be empty")
    return result


@dataclass(frozen=True)
class ArtifactCheck:
    artifact_id: str
    path: Path
    status: str
    actual_sha256: str | None
    expected_sha256: str | None
    reason: str | None = None


def verify_artifacts(manifest_path: Path, *, artifact_root: Path) -> tuple[ArtifactCheck, ...]:
    value: dict[str, Any] = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    if value.get("schema_version") != "research-artifacts-v1":
        raise ReferenceDataError("unsupported artifact manifest schema")
    checks = []
    root = artifact_root.resolve()
    for item in value.get("artifacts", []):
        path = (root / item["local_path"]).resolve()
        if root not in path.parents:
            raise ReferenceDataError("artifact path escapes artifact root")
        expected = item.get("sha256")
        if not path.is_file():
            checks.append(ArtifactCheck(item["id"], path, "missing", None, expected, "not downloaded"))
            continue
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
        actual = digest.hexdigest()
        status = "verified" if expected and actual == expected else "unverified"
        reason = None if status == "verified" else "checksum absent or mismatched"
        checks.append(ArtifactCheck(item["id"], path, status, actual, expected, reason))
    return tuple(checks)
