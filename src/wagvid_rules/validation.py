"""Validate the authoritative rule registry and its cross-record invariants."""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator, FormatChecker


def load_yaml(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as stream:
        value = yaml.safe_load(stream)
    if not isinstance(value, dict):
        raise ValueError("registry root must be a mapping")
    return value


def load_schema(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as stream:
        return json.load(stream)


def validate_registry(registry: dict[str, Any], schema: dict[str, Any]) -> list[str]:
    errors = [
        f"schema:{'/'.join(map(str, error.absolute_path)) or '<root>'}: {error.message}"
        for error in Draft202012Validator(
            schema, format_checker=FormatChecker()
        ).iter_errors(registry)
    ]

    sources = registry.get("sources", [])
    if not isinstance(sources, list):
        return sorted(errors)

    source_ids = [source.get("id") for source in sources if isinstance(source, dict)]
    duplicates = {source_id for source_id in source_ids if source_ids.count(source_id) > 1}
    errors.extend(f"integrity: duplicate source id: {source_id}" for source_id in duplicates)
    known_ids = set(source_ids)

    for source in sources:
        if not isinstance(source, dict):
            continue
        source_id = source.get("id", "<unknown>")
        if source.get("cycle") != registry.get("cycle"):
            errors.append(f"integrity:{source_id}: source cycle differs from registry cycle")
        for replaced_id in source.get("supersedes", []):
            if replaced_id not in known_ids:
                errors.append(f"integrity:{source_id}: unknown supersedes id: {replaced_id}")
            if replaced_id == source_id:
                errors.append(f"integrity:{source_id}: source cannot supersede itself")
        replacement_id = source.get("superseded_by")
        if replacement_id is not None and replacement_id not in known_ids:
            errors.append(f"integrity:{source_id}: unknown superseded_by id: {replacement_id}")
        if source.get("interpretation_status") in {"reviewed", "approved"} and not source.get(
            "review"
        ):
            errors.append(f"integrity:{source_id}: reviewed/approved source needs review metadata")
        if source.get("retention") != "metadata-only" and not source.get("content_sha256"):
            errors.append(f"integrity:{source_id}: retained source needs content_sha256")
        start = source.get("effective_from")
        end = source.get("effective_until")
        if isinstance(start, date) and isinstance(end, date) and end < start:
            errors.append(f"integrity:{source_id}: effective_until precedes effective_from")

    return sorted(errors)


def validate_manifest(
    manifest: dict[str, Any], schema: dict[str, Any], registry: dict[str, Any]
) -> list[str]:
    """Validate a rule-pack manifest and references into the source registry."""
    errors = [
        f"schema:{'/'.join(map(str, error.absolute_path)) or '<root>'}: {error.message}"
        for error in Draft202012Validator(
            schema, format_checker=FormatChecker()
        ).iter_errors(manifest)
    ]
    sources = {
        source.get("id"): source
        for source in registry.get("sources", [])
        if isinstance(source, dict) and source.get("id")
    }
    for source_id in manifest.get("source_ids", []):
        if source_id not in sources:
            errors.append(f"integrity: unknown registry source id: {source_id}")

    if manifest.get("cycle") != registry.get("cycle"):
        errors.append("integrity: manifest cycle differs from registry cycle")

    status = manifest.get("status")
    if status in {"reviewed", "approved"} and not manifest.get("review"):
        errors.append("integrity: reviewed/approved manifest needs review metadata")
    if status == "approved":
        for source_id in manifest.get("source_ids", []):
            source = sources.get(source_id, {})
            if source.get("status") != "current":
                errors.append(
                    f"integrity: approved manifest requires current source: {source_id}"
                )
        for artifact in manifest.get("artifacts", []):
            if isinstance(artifact, dict) and not artifact.get("sha256"):
                errors.append(
                    f"integrity: approved manifest artifact needs sha256: {artifact.get('path')}"
                )
        if not manifest.get("manifest_sha256"):
            errors.append("integrity: approved manifest needs manifest_sha256")

    return sorted(errors)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    registry_parser = subparsers.add_parser("validate", help="validate source registry")
    registry_parser.add_argument("registry", type=Path)
    registry_parser.add_argument("--schema", type=Path)
    manifest_parser = subparsers.add_parser("manifest", help="validate rule-pack manifest")
    manifest_parser.add_argument("manifest", type=Path)
    manifest_parser.add_argument("--registry", type=Path, required=True)
    manifest_parser.add_argument("--schema", type=Path)
    args = parser.parse_args()
    root = Path(__file__).parents[2]
    if args.command == "validate":
        schema_path = args.schema or root / "schemas" / "rule-registry-v1.schema.json"
        errors = validate_registry(load_yaml(args.registry), load_schema(schema_path))
        target = args.registry
    else:
        schema_path = args.schema or root / "schemas" / "rulepack-manifest-v1.schema.json"
        errors = validate_manifest(
            load_yaml(args.manifest), load_schema(schema_path), load_yaml(args.registry)
        )
        target = args.manifest
    if errors:
        print("Validation failed:")
        for error in errors:
            print(f"- {error}")
        return 1
    print(f"Valid: {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
