"""Leakage-safe batch competition planning for post-event analysis.

A competition exchange record may contain an official result at ingest time. This module splits
that record into two trust domains:

1. an analysis task payload containing only the media/apparatus/rule execution context; and
2. a withheld official-result envelope retained by the control plane.

The official payload may be received early, but cannot be revealed to comparison/report code until
the corresponding AI analysis revision has an immutable freeze receipt. Athlete/team/competition
identity remains in the control-plane mapping and is intentionally absent from the worker payload.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from .domain import Apparatus


class CompetitionBatchError(ValueError):
    pass


class RoutineBatchState(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    AI_FROZEN = "ai-frozen"
    OFFICIAL_REVEALED = "official-revealed"
    COMPARISON_READY = "comparison-ready"
    NEEDS_REVIEW = "needs-review"
    COMPLETE = "complete"
    FAILED = "failed"
    CANCELLED = "cancelled"


_ALLOWED_TRANSITIONS: dict[RoutineBatchState, frozenset[RoutineBatchState]] = {
    RoutineBatchState.QUEUED: frozenset(
        {RoutineBatchState.RUNNING, RoutineBatchState.CANCELLED, RoutineBatchState.FAILED}
    ),
    RoutineBatchState.RUNNING: frozenset(
        {RoutineBatchState.AI_FROZEN, RoutineBatchState.CANCELLED, RoutineBatchState.FAILED}
    ),
    RoutineBatchState.AI_FROZEN: frozenset(
        {RoutineBatchState.OFFICIAL_REVEALED, RoutineBatchState.COMPLETE, RoutineBatchState.FAILED}
    ),
    RoutineBatchState.OFFICIAL_REVEALED: frozenset(
        {RoutineBatchState.COMPARISON_READY, RoutineBatchState.FAILED}
    ),
    RoutineBatchState.COMPARISON_READY: frozenset(
        {RoutineBatchState.NEEDS_REVIEW, RoutineBatchState.COMPLETE, RoutineBatchState.FAILED}
    ),
    RoutineBatchState.NEEDS_REVIEW: frozenset(
        {RoutineBatchState.COMPLETE, RoutineBatchState.FAILED}
    ),
    RoutineBatchState.COMPLETE: frozenset(),
    RoutineBatchState.FAILED: frozenset(),
    RoutineBatchState.CANCELLED: frozenset(),
}


@dataclass(frozen=True)
class MediaTaskRef:
    media_id: str
    sha256: str
    download_uri: str
    content_type: str
    camera_id: str | None = None
    view: str | None = None

    def __post_init__(self) -> None:
        if not self.media_id or not self.download_uri or not self.content_type.startswith("video/"):
            raise CompetitionBatchError("media task requires ID, URI and video content type")
        _require_sha256("media SHA-256", self.sha256)


@dataclass(frozen=True)
class AnalysisTask:
    """Control-plane task mapping plus a deliberately identity-minimized worker projection."""

    task_id: str
    idempotency_key: str
    source_record_digest: str
    competition_external_id: str
    routine_external_id: str
    athlete_external_id: str
    team_external_id: str | None
    apparatus: Apparatus
    performed_at: str
    rule_profile: str | None
    media: tuple[MediaTaskRef, ...]
    analysis_profile_digest: str
    requested_at: datetime

    def __post_init__(self) -> None:
        if (
            not self.task_id
            or not self.idempotency_key
            or not self.competition_external_id
            or not self.routine_external_id
            or not self.athlete_external_id
            or not self.performed_at
        ):
            raise CompetitionBatchError("analysis task stable identity/context is required")
        _require_sha256("source record digest", self.source_record_digest)
        _require_sha256("idempotency key", self.idempotency_key)
        _require_sha256("analysis profile digest", self.analysis_profile_digest)
        if self.requested_at.tzinfo is None or self.requested_at.utcoffset() is None:
            raise CompetitionBatchError("analysis task requested_at must be timezone-aware")
        if not self.media:
            raise CompetitionBatchError("analysis task requires at least one media asset")
        media_ids = [item.media_id for item in self.media]
        media_hashes = [item.sha256 for item in self.media]
        if len(media_ids) != len(set(media_ids)):
            raise CompetitionBatchError("analysis task media IDs must be unique")
        if len(media_hashes) != len(set(media_hashes)):
            raise CompetitionBatchError("analysis task cannot include duplicate media bytes")

    def worker_payload(self) -> dict[str, Any]:
        """Identity- and official-score-minimized execution payload.

        Task/idempotency IDs are opaque orchestration handles. Athlete/team/event/routine external
        IDs, source-record digest, performed-at context and all official/adjudication/learning data
        remain in the control plane and are not exposed as potential model features.
        """
        return {
            "schema": "ai.wagvid.competition-analysis-task.v1",
            "task_id": self.task_id,
            "idempotency_key": self.idempotency_key,
            "apparatus": self.apparatus.value,
            "rule_profile": self.rule_profile,
            "media": [asdict(item) for item in self.media],
            "analysis_profile_digest": self.analysis_profile_digest,
            "requested_at": self.requested_at.astimezone(UTC).isoformat(),
        }

    @property
    def digest(self) -> str:
        return _stable_digest(self.worker_payload())


@dataclass(frozen=True)
class WithheldOfficialResult:
    routine_external_id: str
    source_record_digest: str
    official_payload_json: str
    official_payload_digest: str
    received_at: datetime

    def __post_init__(self) -> None:
        if not self.routine_external_id:
            raise CompetitionBatchError("withheld official result requires routine ID")
        _require_sha256("source record digest", self.source_record_digest)
        _require_sha256("official payload digest", self.official_payload_digest)
        if self.received_at.tzinfo is None or self.received_at.utcoffset() is None:
            raise CompetitionBatchError("official result received_at must be timezone-aware")
        try:
            payload = json.loads(self.official_payload_json)
        except json.JSONDecodeError as error:
            raise CompetitionBatchError("withheld official payload is not valid JSON") from error
        if _stable_digest(payload) != self.official_payload_digest:
            raise CompetitionBatchError("withheld official payload digest mismatch")


@dataclass(frozen=True)
class FreezeReceipt:
    task_id: str
    task_digest: str
    analysis_id: str
    analysis_revision_id: str
    analysis_revision_digest: str
    rulepack_digest: str
    model_bundle_digest: str
    frozen_at: datetime

    def __post_init__(self) -> None:
        if not self.task_id or not self.analysis_id or not self.analysis_revision_id:
            raise CompetitionBatchError("freeze receipt task/analysis/revision identity is required")
        for label, value in (
            ("task digest", self.task_digest),
            ("analysis revision digest", self.analysis_revision_digest),
            ("rulepack digest", self.rulepack_digest),
            ("model bundle digest", self.model_bundle_digest),
        ):
            _require_sha256(label, value)
        if self.frozen_at.tzinfo is None or self.frozen_at.utcoffset() is None:
            raise CompetitionBatchError("freeze receipt frozen_at must be timezone-aware")

    @property
    def digest(self) -> str:
        payload = asdict(self)
        payload["frozen_at"] = self.frozen_at.astimezone(UTC).isoformat()
        return _stable_digest(payload)


@dataclass(frozen=True)
class RevealedOfficialResult:
    routine_external_id: str
    official_payload: Mapping[str, Any]
    official_payload_digest: str
    freeze_receipt_digest: str
    revealed_at: datetime

    def __post_init__(self) -> None:
        if not self.routine_external_id:
            raise CompetitionBatchError("revealed official result requires routine ID")
        _require_sha256("official payload digest", self.official_payload_digest)
        _require_sha256("freeze receipt digest", self.freeze_receipt_digest)
        if self.revealed_at.tzinfo is None or self.revealed_at.utcoffset() is None:
            raise CompetitionBatchError("official reveal timestamp must be timezone-aware")
        if _stable_digest(dict(self.official_payload)) != self.official_payload_digest:
            raise CompetitionBatchError("revealed official payload digest mismatch")

    @property
    def digest(self) -> str:
        return _stable_digest(
            {
                "routine_external_id": self.routine_external_id,
                "official_payload_digest": self.official_payload_digest,
                "freeze_receipt_digest": self.freeze_receipt_digest,
                "revealed_at": self.revealed_at.astimezone(UTC).isoformat(),
            }
        )


@dataclass(frozen=True)
class PlannedRoutine:
    task: AnalysisTask
    withheld_official: WithheldOfficialResult

    def __post_init__(self) -> None:
        if self.task.routine_external_id != self.withheld_official.routine_external_id:
            raise CompetitionBatchError("official result belongs to a different routine")
        if self.task.source_record_digest != self.withheld_official.source_record_digest:
            raise CompetitionBatchError("task and withheld official result came from different records")


@dataclass(frozen=True)
class ExcludedRoutine:
    source_record_digest: str
    competition_external_id: str
    routine_external_id: str
    reasons: tuple[str, ...]

    def __post_init__(self) -> None:
        _require_sha256("source record digest", self.source_record_digest)
        if not self.reasons:
            raise CompetitionBatchError("excluded routine requires at least one reason")


@dataclass(frozen=True)
class CompetitionBatchPlan:
    batch_id: str
    requested_at: datetime
    analysis_profile_digest: str
    routines: tuple[PlannedRoutine, ...]
    excluded: tuple[ExcludedRoutine, ...]

    def __post_init__(self) -> None:
        if not self.batch_id:
            raise CompetitionBatchError("batch_id is required")
        if self.requested_at.tzinfo is None or self.requested_at.utcoffset() is None:
            raise CompetitionBatchError("batch requested_at must be timezone-aware")
        _require_sha256("analysis profile digest", self.analysis_profile_digest)
        task_ids = [item.task.task_id for item in self.routines]
        idempotency_keys = [item.task.idempotency_key for item in self.routines]
        routine_keys = [
            (item.task.competition_external_id, item.task.routine_external_id)
            for item in self.routines
        ]
        if len(routine_keys) != len(set(routine_keys)):
            raise CompetitionBatchError("batch cannot plan the same competition routine twice")
        if len(task_ids) != len(set(task_ids)):
            raise CompetitionBatchError("batch task IDs must be unique")
        if len(idempotency_keys) != len(set(idempotency_keys)):
            raise CompetitionBatchError("batch idempotency keys must be unique")

    @property
    def digest(self) -> str:
        return _stable_digest(
            {
                "batch_id": self.batch_id,
                "requested_at": self.requested_at.astimezone(UTC).isoformat(),
                "analysis_profile_digest": self.analysis_profile_digest,
                "tasks": [item.task.digest for item in self.routines],
                "control_mappings": [
                    {
                        "competition_external_id": item.task.competition_external_id,
                        "routine_external_id": item.task.routine_external_id,
                        "source_record_digest": item.task.source_record_digest,
                    }
                    for item in self.routines
                ],
                "withheld_official_digests": [
                    item.withheld_official.official_payload_digest for item in self.routines
                ],
                "excluded": [asdict(item) for item in self.excluded],
            }
        )


@dataclass(frozen=True)
class RoutineBatchEvent:
    event_id: str
    task_id: str
    state: RoutineBatchState
    occurred_at: datetime
    actor: str
    detail_digest: str | None = None
    prior_event_digest: str | None = None

    def __post_init__(self) -> None:
        if not self.event_id or not self.task_id or not self.actor:
            raise CompetitionBatchError("batch event identity, task and actor are required")
        if self.occurred_at.tzinfo is None or self.occurred_at.utcoffset() is None:
            raise CompetitionBatchError("batch event occurred_at must be timezone-aware")
        if self.detail_digest is not None:
            _require_sha256("batch event detail digest", self.detail_digest)
        if self.prior_event_digest is not None:
            _require_sha256("prior event digest", self.prior_event_digest)

    @property
    def digest(self) -> str:
        payload = asdict(self)
        payload["state"] = self.state.value
        payload["occurred_at"] = self.occurred_at.astimezone(UTC).isoformat()
        return _stable_digest(payload)


class RoutineBatchJournal:
    """Append-only lifecycle for one task with explicit legal transitions."""

    def __init__(self, task: AnalysisTask, events: Iterable[RoutineBatchEvent] = ()) -> None:
        self.task = task
        self._events: list[RoutineBatchEvent] = []
        for event in events:
            self.append(event)

    def append(self, event: RoutineBatchEvent) -> None:
        if event.task_id != self.task.task_id:
            raise CompetitionBatchError("batch event belongs to another task")
        if not self._events:
            if event.state is not RoutineBatchState.QUEUED:
                raise CompetitionBatchError("first batch event must be queued")
            if event.prior_event_digest is not None:
                raise CompetitionBatchError("first batch event cannot have prior digest")
        else:
            previous = self._events[-1]
            if event.occurred_at <= previous.occurred_at:
                raise CompetitionBatchError("batch event timestamps must increase")
            if event.prior_event_digest != previous.digest:
                raise CompetitionBatchError("batch event hash chain mismatch")
            if event.state not in _ALLOWED_TRANSITIONS[previous.state]:
                raise CompetitionBatchError(
                    f"illegal batch state transition: {previous.state.value}->{event.state.value}"
                )
        if any(existing.event_id == event.event_id for existing in self._events):
            raise CompetitionBatchError("batch event IDs must be unique")
        self._events.append(event)

    @property
    def events(self) -> tuple[RoutineBatchEvent, ...]:
        return tuple(self._events)

    @property
    def current_state(self) -> RoutineBatchState | None:
        return self._events[-1].state if self._events else None


def plan_competition_batch(
    records: Iterable[Mapping[str, Any]],
    *,
    batch_id: str,
    analysis_profile_digest: str,
    requested_at: datetime,
) -> CompetitionBatchPlan:
    if requested_at.tzinfo is None or requested_at.utcoffset() is None:
        raise CompetitionBatchError("requested_at must be timezone-aware")
    _require_sha256("analysis profile digest", analysis_profile_digest)
    planned: list[PlannedRoutine] = []
    excluded: list[ExcludedRoutine] = []
    for raw in records:
        record = dict(raw)
        record_digest = _stable_digest(record)
        competition = _mapping(record.get("competition"), "competition")
        routine = _mapping(record.get("routine"), "routine")
        rights = _mapping(record.get("rights"), "rights")
        official = _mapping(record.get("official_result"), "official_result")
        competition_id = _string(competition.get("external_id"), "competition.external_id")
        routine_id = _string(routine.get("external_id"), "routine.external_id")
        reasons = _analysis_exclusion_reasons(record, rights)
        if reasons:
            excluded.append(
                ExcludedRoutine(
                    source_record_digest=record_digest,
                    competition_external_id=competition_id,
                    routine_external_id=routine_id,
                    reasons=tuple(reasons),
                )
            )
            continue
        media = tuple(_media_ref(item) for item in _mapping_sequence(record.get("media"), "media"))
        try:
            apparatus = Apparatus(_string(routine.get("apparatus"), "routine.apparatus"))
        except ValueError as error:
            raise CompetitionBatchError(f"invalid routine apparatus: {routine.get('apparatus')}") from error
        rule_profile = _optional_string(competition.get("rule_profile"))
        # Idempotency deliberately excludes official/adjudication/learning payloads. Correcting an
        # official score must not change/re-run the independent AI analysis of the same media.
        idempotency_key = _stable_digest(
            {
                "competition_external_id": competition_id,
                "routine_external_id": routine_id,
                "apparatus": apparatus.value,
                "rule_profile": rule_profile,
                "analysis_profile_digest": analysis_profile_digest,
                "media_sha256": sorted(item.sha256 for item in media),
            }
        )
        task_id = f"task:{idempotency_key[:24]}"
        task = AnalysisTask(
            task_id=task_id,
            idempotency_key=idempotency_key,
            source_record_digest=record_digest,
            competition_external_id=competition_id,
            routine_external_id=routine_id,
            athlete_external_id=_string(
                routine.get("athlete_external_id"), "routine.athlete_external_id"
            ),
            team_external_id=_optional_string(routine.get("team_external_id")),
            apparatus=apparatus,
            performed_at=_string(routine.get("performed_at"), "routine.performed_at"),
            rule_profile=rule_profile,
            media=media,
            analysis_profile_digest=analysis_profile_digest,
            requested_at=requested_at,
        )
        official_json = json.dumps(official, sort_keys=True, separators=(",", ":"))
        official_digest = _stable_digest(official)
        planned.append(
            PlannedRoutine(
                task=task,
                withheld_official=WithheldOfficialResult(
                    routine_external_id=routine_id,
                    source_record_digest=record_digest,
                    official_payload_json=official_json,
                    official_payload_digest=official_digest,
                    received_at=requested_at,
                ),
            )
        )
    return CompetitionBatchPlan(
        batch_id=batch_id,
        requested_at=requested_at,
        analysis_profile_digest=analysis_profile_digest,
        routines=tuple(
            sorted(
                planned,
                key=lambda item: (
                    item.task.competition_external_id,
                    item.task.routine_external_id,
                ),
            )
        ),
        excluded=tuple(
            sorted(excluded, key=lambda item: (item.competition_external_id, item.routine_external_id))
        ),
    )


def reveal_official_result(
    planned: PlannedRoutine,
    freeze: FreezeReceipt,
    *,
    revealed_at: datetime,
) -> RevealedOfficialResult:
    if freeze.task_id != planned.task.task_id or freeze.task_digest != planned.task.digest:
        raise CompetitionBatchError("freeze receipt does not belong to planned analysis task")
    if planned.task.source_record_digest != planned.withheld_official.source_record_digest:
        raise CompetitionBatchError("withheld official result source does not match task mapping")
    if revealed_at.tzinfo is None or revealed_at.utcoffset() is None:
        raise CompetitionBatchError("revealed_at must be timezone-aware")
    if revealed_at <= freeze.frozen_at:
        raise CompetitionBatchError("official result reveal must occur strictly after AI freeze")
    payload = json.loads(planned.withheld_official.official_payload_json)
    return RevealedOfficialResult(
        routine_external_id=planned.task.routine_external_id,
        official_payload=payload,
        official_payload_digest=planned.withheld_official.official_payload_digest,
        freeze_receipt_digest=freeze.digest,
        revealed_at=revealed_at,
    )


@dataclass(frozen=True)
class DisagreementRecord:
    routine_external_id: str
    apparatus: Apparatus
    category: str
    element_family: str | None
    deduction_category: str | None
    camera_condition: str | None
    delta_milli_points: int
    material: bool
    comparison_digest: str

    def __post_init__(self) -> None:
        if not self.routine_external_id or not self.category:
            raise CompetitionBatchError("disagreement routine/category are required")
        _require_sha256("comparison digest", self.comparison_digest)
        if isinstance(self.delta_milli_points, bool) or not isinstance(self.delta_milli_points, int):
            raise CompetitionBatchError("delta_milli_points must be an integer")


@dataclass(frozen=True)
class DisagreementAggregate:
    dimension: str
    key: str
    routine_count: int
    material_count: int
    total_absolute_delta_milli_points: int
    maximum_absolute_delta_milli_points: int


def aggregate_disagreements(
    records: Iterable[DisagreementRecord],
    *,
    dimension: str,
) -> tuple[DisagreementAggregate, ...]:
    extractors = {
        "apparatus": lambda item: item.apparatus.value,
        "category": lambda item: item.category,
        "element_family": lambda item: item.element_family or "<unavailable>",
        "deduction_category": lambda item: item.deduction_category or "<unavailable>",
        "camera_condition": lambda item: item.camera_condition or "<unavailable>",
    }
    extractor = extractors.get(dimension)
    if extractor is None:
        raise CompetitionBatchError(f"unsupported disagreement aggregation dimension: {dimension}")
    grouped: dict[str, list[DisagreementRecord]] = {}
    for item in records:
        grouped.setdefault(extractor(item), []).append(item)
    result = []
    for key, values in sorted(grouped.items()):
        routine_ids = {item.routine_external_id for item in values}
        absolutes = [abs(item.delta_milli_points) for item in values]
        result.append(
            DisagreementAggregate(
                dimension=dimension,
                key=key,
                routine_count=len(routine_ids),
                material_count=sum(1 for item in values if item.material),
                total_absolute_delta_milli_points=sum(absolutes),
                maximum_absolute_delta_milli_points=max(absolutes) if absolutes else 0,
            )
        )
    return tuple(result)


def _analysis_exclusion_reasons(record: Mapping[str, Any], rights: Mapping[str, Any]) -> list[str]:
    reasons: list[str] = []
    if record.get("schema") != "ai.wagvid.competition-video.v1":
        reasons.append("unsupported-record-schema")
    if rights.get("analysis_allowed") is not True:
        reasons.append("analysis-not-authorized")
    if rights.get("download_allowed") is not True:
        reasons.append("media-download-not-authorized")
    media = record.get("media")
    if not isinstance(media, list) or not media:
        reasons.append("media-unavailable")
    return reasons


def _media_ref(payload: Mapping[str, Any]) -> MediaTaskRef:
    return MediaTaskRef(
        media_id=_string(payload.get("media_id"), "media.media_id"),
        sha256=_string(payload.get("sha256"), "media.sha256"),
        download_uri=_string(payload.get("download_uri"), "media.download_uri"),
        content_type=_string(payload.get("content_type"), "media.content_type"),
        camera_id=_optional_string(payload.get("camera_id")),
        view=_optional_string(payload.get("view")),
    )


def _stable_digest(payload: Any) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


def _require_sha256(label: str, value: str) -> None:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise CompetitionBatchError(f"{label} must be lowercase SHA-256 hexadecimal")


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise CompetitionBatchError(f"{label} must be an object")
    return value


def _mapping_sequence(value: Any, label: str) -> tuple[Mapping[str, Any], ...]:
    if not isinstance(value, list):
        raise CompetitionBatchError(f"{label} must be an array")
    return tuple(_mapping(item, label) for item in value)


def _string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise CompetitionBatchError(f"{label} must be a non-empty string")
    return value


def _optional_string(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise CompetitionBatchError("optional string value must be non-empty when present")
    return value
