"""Model-profile readiness checks for reproducible apparatus benchmarks.

This complements the existing model catalogue: a structurally valid/runnable profile is not yet
benchmark-ready unless every real model component has an exact checkpoint/config artifact, immutable
hashes and an acquisition/rights record. Contract-only components remain explicit blockers.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence


class ModelReadinessError(ValueError):
    pass


@dataclass(frozen=True)
class ComponentReadiness:
    component_id: str
    ready: bool
    blockers: tuple[str, ...]
    checkpoint_digest: str | None
    config_digest: str
    artifact_ids: tuple[str, ...]


@dataclass(frozen=True)
class ProfileReadiness:
    profile_id: str
    ready: bool
    blockers: tuple[str, ...]
    components: tuple[ComponentReadiness, ...]


def evaluate_profile_readiness(
    *,
    catalog: Mapping[str, object],
    artifact_registry: Mapping[str, object],
    profile_id: str,
    component_artifact_map: Mapping[str, Sequence[str]],
) -> ProfileReadiness:
    components_raw = _sequence(catalog.get("components"), "catalog components")
    profiles_raw = _sequence(catalog.get("profiles"), "catalog profiles")
    artifacts_raw = _sequence(artifact_registry.get("artifacts"), "research artifacts")

    components = {_required_string(item, "id"): item for item in _objects(components_raw, "component")}
    profiles = {_required_string(item, "id"): item for item in _objects(profiles_raw, "profile")}
    artifacts = {_required_string(item, "id"): item for item in _objects(artifacts_raw, "artifact")}

    profile = profiles.get(profile_id)
    if profile is None:
        raise ModelReadinessError(f"unknown model profile: {profile_id}")
    profile_components = _string_sequence(profile.get("components"), "profile components")

    results: list[ComponentReadiness] = []
    profile_blockers: list[str] = []
    for component_id in profile_components:
        component = components.get(component_id)
        if component is None:
            profile_blockers.append(f"profile-component-missing:{component_id}")
            continue
        blockers: list[str] = []
        artifact_status = component.get("artifact_status")
        if artifact_status not in {"local-available", "validated"}:
            blockers.append(f"component-artifact-status:{artifact_status}")
        config_digest = _required_string(component, "config_digest")
        if not _is_sha256(config_digest) or set(config_digest) in ({"0"}, {"1"}, {"2"}, {"3"}, {"4"}, {"5"}, {"6"}, {"7"}, {"8"}, {"9"}):
            blockers.append("component-config-digest-placeholder-or-invalid")
        checkpoint = component.get("checkpoint_digest")
        capability = component.get("capability")
        requires_checkpoint = capability in {"perception", "action", "quality"}
        if requires_checkpoint and not _is_sha256(checkpoint):
            blockers.append("component-checkpoint-digest-missing")

        artifact_ids = tuple(component_artifact_map.get(component_id, ()))
        if requires_checkpoint and not artifact_ids:
            blockers.append("component-artifact-record-missing")
        for artifact_id in artifact_ids:
            artifact = artifacts.get(artifact_id)
            if artifact is None:
                blockers.append(f"artifact-not-registered:{artifact_id}")
                continue
            if artifact.get("acquisition_status") not in {"acquired", "verified", "validated"}:
                blockers.append(f"artifact-not-acquired:{artifact_id}")
            if not _is_sha256(artifact.get("sha256")):
                blockers.append(f"artifact-sha256-missing:{artifact_id}")
            if not _required_string(artifact, "source_url"):
                blockers.append(f"artifact-source-missing:{artifact_id}")

        normalized = tuple(sorted(set(blockers)))
        results.append(
            ComponentReadiness(
                component_id=component_id,
                ready=not normalized,
                blockers=normalized,
                checkpoint_digest=checkpoint if isinstance(checkpoint, str) else None,
                config_digest=config_digest,
                artifact_ids=artifact_ids,
            )
        )
        profile_blockers.extend(f"{component_id}:{item}" for item in normalized)

    normalized_profile = tuple(sorted(set(profile_blockers)))
    return ProfileReadiness(
        profile_id=profile_id,
        ready=not normalized_profile and len(results) == len(profile_components),
        blockers=normalized_profile,
        components=tuple(results),
    )


def _sequence(value: object, label: str) -> Sequence[object]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ModelReadinessError(f"{label} must be a sequence")
    return value


def _objects(values: Sequence[object], label: str) -> tuple[Mapping[str, object], ...]:
    result: list[Mapping[str, object]] = []
    for value in values:
        if not isinstance(value, Mapping):
            raise ModelReadinessError(f"{label} must be an object")
        result.append(value)
    return tuple(result)


def _required_string(mapping: Mapping[str, object], key: str) -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ModelReadinessError(f"{key} must be a non-empty string")
    return value


def _string_sequence(value: object, label: str) -> tuple[str, ...]:
    sequence = _sequence(value, label)
    result = tuple(sequence)
    if not result or any(not isinstance(item, str) or not item for item in result):
        raise ModelReadinessError(f"{label} must contain non-empty strings")
    return result  # type: ignore[return-value]


def _is_sha256(value: object) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(char in "0123456789abcdef" for char in value)
