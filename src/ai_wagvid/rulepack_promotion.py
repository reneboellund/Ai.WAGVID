"""Release-readiness checks for governed WAG rulepack snapshots.

The registry can be structurally valid while still being unreviewed/draft. Apparatus promotion must
not treat that as a release-approved scoring source.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence


class RulepackPromotionError(ValueError):
    pass


@dataclass(frozen=True)
class RulepackReadiness:
    rulepack_id: str
    ready: bool
    blockers: tuple[str, ...]
    manifest_sha256: str | None
    source_ids: tuple[str, ...]


def evaluate_rulepack_readiness(
    *,
    manifest: Mapping[str, object],
    registry: Mapping[str, object],
) -> RulepackReadiness:
    rulepack_id = _required_string(manifest, "rulepack_id")
    status = _required_string(manifest, "status")
    source_ids = _string_sequence(manifest.get("source_ids"), "source_ids")
    manifest_sha = manifest.get("manifest_sha256")
    review = manifest.get("review")

    blockers: list[str] = []
    if status != "approved":
        blockers.append("rulepack-manifest-not-approved")
    if not _is_sha256(manifest_sha):
        blockers.append("rulepack-manifest-sha256-missing-or-invalid")
    if not isinstance(review, Mapping) or not review:
        blockers.append("rulepack-review-metadata-missing")

    sources_raw = registry.get("sources")
    if not isinstance(sources_raw, Sequence) or isinstance(sources_raw, (str, bytes)):
        raise RulepackPromotionError("registry sources must be a sequence")
    sources_by_id: dict[str, Mapping[str, object]] = {}
    for source in sources_raw:
        if not isinstance(source, Mapping):
            raise RulepackPromotionError("registry source must be an object")
        source_id = _required_string(source, "id")
        sources_by_id[source_id] = source

    for source_id in source_ids:
        source = sources_by_id.get(source_id)
        if source is None:
            blockers.append(f"rulepack-source-missing:{source_id}")
            continue
        if source.get("status") != "current":
            blockers.append(f"rulepack-source-not-current:{source_id}")
        if source.get("interpretation_status") != "approved":
            blockers.append(f"rulepack-source-not-approved:{source_id}")
        source_review = source.get("review")
        if not isinstance(source_review, Mapping) or not source_review:
            blockers.append(f"rulepack-source-review-missing:{source_id}")
        retention = source.get("retention")
        if retention in {"licensed-copy", "archived-copy"} and not _is_sha256(source.get("content_sha256")):
            blockers.append(f"rulepack-retained-source-hash-missing:{source_id}")

    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, Sequence) or isinstance(artifacts, (str, bytes)):
        blockers.append("rulepack-artifacts-invalid")
    elif not artifacts:
        blockers.append("rulepack-artifacts-not-frozen")
    else:
        for index, artifact in enumerate(artifacts):
            if not isinstance(artifact, Mapping):
                blockers.append(f"rulepack-artifact-invalid:{index}")
                continue
            digest = artifact.get("sha256") or artifact.get("content_sha256")
            if not _is_sha256(digest):
                blockers.append(f"rulepack-artifact-hash-missing:{index}")

    normalized = tuple(sorted(set(blockers)))
    return RulepackReadiness(
        rulepack_id=rulepack_id,
        ready=not normalized,
        blockers=normalized,
        manifest_sha256=manifest_sha if isinstance(manifest_sha, str) else None,
        source_ids=source_ids,
    )


def _required_string(mapping: Mapping[str, object], key: str) -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or not value.strip():
        raise RulepackPromotionError(f"{key} must be a non-empty string")
    return value


def _string_sequence(value: object, label: str) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise RulepackPromotionError(f"{label} must be a sequence")
    result = tuple(value)
    if not result or any(not isinstance(item, str) or not item for item in result):
        raise RulepackPromotionError(f"{label} must contain non-empty strings")
    if len(result) != len(set(result)):
        raise RulepackPromotionError(f"{label} must be unique")
    return result


def _is_sha256(value: object) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(char in "0123456789abcdef" for char in value)
