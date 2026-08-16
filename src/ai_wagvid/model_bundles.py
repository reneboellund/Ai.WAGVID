"""Validated model component and runtime-profile catalogue."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator


class ModelBundleError(ValueError):
    pass


@dataclass(frozen=True)
class ResolvedProfile:
    profile_id: str
    mode: str
    apparatus: tuple[str, ...]
    components: tuple[dict[str, Any], ...]

    @property
    def runnable(self) -> bool:
        return all(item["artifact_status"] in {"local-available", "validated"} for item in self.components)


def load_model_catalog(path: Path, *, schema_path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    errors = sorted(Draft202012Validator(schema).iter_errors(value), key=lambda e: list(e.path))
    if errors:
        raise ModelBundleError(
            "; ".join(
                f"{'/'.join(map(str, error.path)) or '<root>'}: {error.message}"
                for error in errors
            )
        )
    component_ids = [item["id"] for item in value["components"]]
    profile_ids = [item["id"] for item in value["profiles"]]
    if len(component_ids) != len(set(component_ids)) or len(profile_ids) != len(set(profile_ids)):
        raise ModelBundleError("component and profile IDs must be unique")
    known = set(component_ids)
    for profile in value["profiles"]:
        missing = set(profile["components"]) - known
        if missing:
            raise ModelBundleError(
                f"profile {profile['id']} references unknown components: {', '.join(sorted(missing))}"
            )
        capabilities = {
            item["capability"]
            for item in value["components"]
            if item["id"] in profile["components"]
        }
        required = {"perception", "action", "interpretation"}
        if not required <= capabilities:
            raise ModelBundleError(f"profile {profile['id']} lacks required AI layer capabilities")
    return value


def resolve_profile(catalog: dict[str, Any], profile_id: str) -> ResolvedProfile:
    profiles = {item["id"]: item for item in catalog["profiles"]}
    try:
        profile = profiles[profile_id]
    except KeyError as error:
        raise ModelBundleError(f"unknown model profile: {profile_id}") from error
    components = {item["id"]: item for item in catalog["components"]}
    return ResolvedProfile(
        profile_id=profile["id"],
        mode=profile["mode"],
        apparatus=tuple(profile["apparatus"]),
        components=tuple(components[item] for item in profile["components"]),
    )
