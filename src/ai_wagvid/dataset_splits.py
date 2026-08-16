"""Leakage-safe deterministic dataset splits for gymnastics research."""

from __future__ import annotations

import hashlib
from collections import defaultdict
from dataclasses import dataclass
from enum import Enum


class Split(str, Enum):
    TRAIN = "train"
    VALIDATION = "validation"
    TEST = "test"


@dataclass(frozen=True)
class DatasetSample:
    sample_id: str
    dataset_id: str
    athlete_group_id: str
    event_group_id: str
    routine_group_id: str
    source_sha256: str

    def __post_init__(self) -> None:
        for name in ("sample_id", "dataset_id", "routine_group_id"):
            if not getattr(self, name):
                raise ValueError(f"{name} is required")
        if len(self.source_sha256) != 64 or any(
            character not in "0123456789abcdefABCDEF" for character in self.source_sha256
        ):
            raise ValueError("source_sha256 must be a 64-character hexadecimal digest")


@dataclass(frozen=True)
class SplitRatios:
    train: float = 0.7
    validation: float = 0.15
    test: float = 0.15

    def __post_init__(self) -> None:
        if min(self.train, self.validation, self.test) < 0:
            raise ValueError("split ratios cannot be negative")
        if abs(self.train + self.validation + self.test - 1) > 1e-9:
            raise ValueError("split ratios must sum to 1")


class _Groups:
    def __init__(self, ids: list[str]):
        self.parent = {item: item for item in ids}

    def find(self, item: str) -> str:
        parent = self.parent[item]
        if parent != item:
            self.parent[item] = self.find(parent)
        return self.parent[item]

    def union(self, left: str, right: str) -> None:
        left_root, right_root = self.find(left), self.find(right)
        if left_root != right_root:
            first, second = sorted((left_root, right_root))
            self.parent[second] = first


def _connected_components(samples: tuple[DatasetSample, ...]) -> dict[str, list[DatasetSample]]:
    if len({sample.sample_id for sample in samples}) != len(samples):
        raise ValueError("sample_id must be unique")
    groups = _Groups([sample.sample_id for sample in samples])
    seen: dict[tuple[str, str], str] = {}
    for sample in samples:
        keys = [
            ("routine", sample.routine_group_id),
            ("sha256", sample.source_sha256.lower()),
        ]
        if sample.athlete_group_id:
            keys.append(("athlete", sample.athlete_group_id))
        if sample.event_group_id:
            keys.append(("event", sample.event_group_id))
        for key in keys:
            if key in seen:
                groups.union(sample.sample_id, seen[key])
            else:
                seen[key] = sample.sample_id
    components: dict[str, list[DatasetSample]] = defaultdict(list)
    for sample in samples:
        components[groups.find(sample.sample_id)].append(sample)
    return dict(components)


def assign_splits(
    samples: tuple[DatasetSample, ...],
    *,
    salt: str,
    ratios: SplitRatios | None = None,
) -> dict[str, Split]:
    if not salt:
        raise ValueError("a versioned split salt is required")
    ratios = ratios or SplitRatios()
    assignments: dict[str, Split] = {}
    for component in _connected_components(samples).values():
        identity = "|".join(sorted(sample.sample_id for sample in component))
        digest = hashlib.sha256(f"{salt}|{identity}".encode()).digest()
        position = int.from_bytes(digest[:8], "big") / 2**64
        if position < ratios.train:
            split = Split.TRAIN
        elif position < ratios.train + ratios.validation:
            split = Split.VALIDATION
        else:
            split = Split.TEST
        assignments.update({sample.sample_id: split for sample in component})
    return assignments


def find_leakage(
    samples: tuple[DatasetSample, ...], assignments: dict[str, Split]
) -> dict[str, set[Split]]:
    missing = {sample.sample_id for sample in samples} - assignments.keys()
    if missing:
        raise ValueError(f"missing split assignments: {', '.join(sorted(missing))}")
    leaked: dict[str, set[Split]] = {}
    dimensions = {
        "athlete": lambda sample: sample.athlete_group_id,
        "event": lambda sample: sample.event_group_id,
        "routine": lambda sample: sample.routine_group_id,
        "sha256": lambda sample: sample.source_sha256.lower(),
    }
    for dimension, getter in dimensions.items():
        observed: dict[str, set[Split]] = defaultdict(set)
        for sample in samples:
            value = getter(sample)
            if value:
                observed[value].add(assignments[sample.sample_id])
        leaked.update(
            {
                f"{dimension}:{value}": splits
                for value, splits in observed.items()
                if len(splits) > 1
            }
        )
    return leaked
