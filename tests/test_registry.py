from copy import deepcopy
from pathlib import Path

from wagvid_rules.validation import (
    load_schema,
    load_yaml,
    validate_manifest,
    validate_registry,
)

ROOT = Path(__file__).parents[1]
SCHEMA = load_schema(ROOT / "schemas" / "rule-registry-v1.schema.json")
REGISTRY = load_yaml(ROOT / "rules" / "registry.yaml")
MANIFEST_SCHEMA = load_schema(ROOT / "schemas" / "rulepack-manifest-v1.schema.json")
MANIFEST = load_yaml(ROOT / "rules" / "rulepack-manifest.example.yaml")


def test_repository_registry_is_valid() -> None:
    assert validate_registry(REGISTRY, SCHEMA) == []


def test_duplicate_ids_are_rejected() -> None:
    registry = deepcopy(REGISTRY)
    registry["sources"].append(deepcopy(registry["sources"][0]))
    assert any("duplicate source id" in error for error in validate_registry(registry, SCHEMA))


def test_approved_source_requires_review_metadata() -> None:
    registry = deepcopy(REGISTRY)
    registry["sources"][0]["interpretation_status"] = "approved"
    assert any("needs review metadata" in error for error in validate_registry(registry, SCHEMA))


def test_retained_copy_requires_hash() -> None:
    registry = deepcopy(REGISTRY)
    registry["sources"][0]["retention"] = "licensed-copy"
    assert any("needs content_sha256" in error for error in validate_registry(registry, SCHEMA))


def test_example_manifest_is_valid() -> None:
    assert validate_manifest(MANIFEST, MANIFEST_SCHEMA, REGISTRY) == []


def test_manifest_rejects_unknown_source() -> None:
    manifest = deepcopy(MANIFEST)
    manifest["source_ids"].append("unknown-source")
    assert any(
        "unknown registry source id" in error
        for error in validate_manifest(manifest, MANIFEST_SCHEMA, REGISTRY)
    )


def test_approved_manifest_requires_frozen_reviewed_inputs() -> None:
    manifest = deepcopy(MANIFEST)
    manifest["status"] = "approved"
    errors = validate_manifest(manifest, MANIFEST_SCHEMA, REGISTRY)
    assert any("needs review metadata" in error for error in errors)
    assert any("requires current source" in error for error in errors)
    assert any("needs manifest_sha256" in error for error in errors)
