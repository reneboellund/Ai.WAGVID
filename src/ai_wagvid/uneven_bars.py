"""Evidence-first uneven-bars contact topology and continuity contracts.

This layer records what bar/contact state is supported by video. It does not infer D/E/final score
or award connection value. Accepted topology can later feed temporal interpretation and #6.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from enum import StrEnum

from .domain import Apparatus


class UnevenBarsError(ValueError):
    pass


class BarIdentity(StrEnum):
    LOW = "low-bar"
    HIGH = "high-bar"
    UNKNOWN = "unknown"


class ContactState(StrEnum):
    HANG = "hang"
    SUPPORT = "support"
    RELEASED = "released"
    FLIGHT = "flight"
    REGRASP = "regrasp"
    FALL_OR_INTERRUPTION = "fall-or-interruption"
    UNKNOWN = "unknown"


class TopologyEventKind(StrEnum):
    CONTACT_START = "contact-start"
    CONTACT_END = "contact-end"
    RELEASE = "release"
    REGRASP = "regrasp"
    BAR_CHANGE = "bar-change"
    HANDSTAND_REGION = "handstand-region"
    TURN_PROGRESS = "turn-progress"
    FALL_OR_INTERRUPTION = "fall-or-interruption"


@dataclass(frozen=True)
class UBReferenceEvidence:
    evidence_id: str
    evidence_digest: str
    start_ms: int
    end_ms: int
    camera_id: str

    def __post_init__(self) -> None:
        if not self.evidence_id or not self.camera_id:
            raise UnevenBarsError("UB evidence identity and camera are required")
        _sha("evidence_digest", self.evidence_digest)
        _interval(self.start_ms, self.end_ms)

    @property
    def digest(self) -> str:
        return _digest(asdict(self))


@dataclass(frozen=True)
class UBContactInterval:
    contact_id: str
    start_ms: int
    end_ms: int
    state: ContactState
    bar: BarIdentity
    confidence_milli: int
    evidence: tuple[UBReferenceEvidence, ...]
    geometry_digest: str | None = None
    limitations: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.contact_id:
            raise UnevenBarsError("contact_id is required")
        _interval(self.start_ms, self.end_ms)
        _milli("contact confidence", self.confidence_milli)
        if not self.evidence:
            raise UnevenBarsError("contact interval requires evidence")
        if any(ref.start_ms > self.start_ms or ref.end_ms < self.end_ms for ref in self.evidence):
            raise UnevenBarsError("contact evidence must cover contact interval")
        if self.geometry_digest is not None:
            _sha("geometry_digest", self.geometry_digest)
        if self.bar is not BarIdentity.UNKNOWN and self.geometry_digest is None:
            raise UnevenBarsError("known bar identity requires calibrated bar geometry")
        if len(self.limitations) != len(set(self.limitations)):
            raise UnevenBarsError("contact limitations must be unique")

    @property
    def digest(self) -> str:
        return _digest({
            "contact_id": self.contact_id,
            "start_ms": self.start_ms,
            "end_ms": self.end_ms,
            "state": self.state.value,
            "bar": self.bar.value,
            "confidence_milli": self.confidence_milli,
            "evidence_digests": [item.digest for item in self.evidence],
            "geometry_digest": self.geometry_digest,
            "limitations": list(self.limitations),
        })


@dataclass(frozen=True)
class UBTopologyEvent:
    event_id: str
    kind: TopologyEventKind
    at_ms: int
    from_bar: BarIdentity
    to_bar: BarIdentity
    confidence_milli: int
    evidence: tuple[UBReferenceEvidence, ...]
    geometry_digest: str | None = None
    limitations: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.event_id:
            raise UnevenBarsError("topology event_id is required")
        if isinstance(self.at_ms, bool) or not isinstance(self.at_ms, int) or self.at_ms < 0:
            raise UnevenBarsError("topology event at_ms must be non-negative integer")
        _milli("topology event confidence", self.confidence_milli)
        if not self.evidence:
            raise UnevenBarsError("topology event requires evidence")
        if self.geometry_digest is not None:
            _sha("geometry_digest", self.geometry_digest)
        if (self.from_bar is not BarIdentity.UNKNOWN or self.to_bar is not BarIdentity.UNKNOWN) and self.geometry_digest is None:
            raise UnevenBarsError("topology event with known bar identity requires geometry")
        if self.kind is TopologyEventKind.BAR_CHANGE:
            if self.from_bar is BarIdentity.UNKNOWN or self.to_bar is BarIdentity.UNKNOWN:
                raise UnevenBarsError("bar-change event requires known from/to bar")
            if self.from_bar is self.to_bar:
                raise UnevenBarsError("bar-change event must change bar identity")
        if len(self.limitations) != len(set(self.limitations)):
            raise UnevenBarsError("topology event limitations must be unique")

    @property
    def digest(self) -> str:
        return _digest({
            "event_id": self.event_id,
            "kind": self.kind.value,
            "at_ms": self.at_ms,
            "from_bar": self.from_bar.value,
            "to_bar": self.to_bar.value,
            "confidence_milli": self.confidence_milli,
            "evidence_digests": [item.digest for item in self.evidence],
            "geometry_digest": self.geometry_digest,
            "limitations": list(self.limitations),
        })


@dataclass(frozen=True)
class UBElementCandidateRef:
    segment_id: str
    temporal_candidate_digest: str
    start_ms: int
    end_ms: int
    family: str | None
    element_id: str | None
    accepted: bool

    def __post_init__(self) -> None:
        if not self.segment_id:
            raise UnevenBarsError("UB element segment_id is required")
        _sha("temporal_candidate_digest", self.temporal_candidate_digest)
        _interval(self.start_ms, self.end_ms)
        if self.element_id is not None and not self.family:
            raise UnevenBarsError("exact UB element reference requires family")
        if not self.accepted and self.element_id is not None:
            raise UnevenBarsError("unaccepted UB candidate cannot be exposed as exact accepted element")


@dataclass(frozen=True)
class UBContinuityCandidate:
    continuity_id: str
    first_segment_id: str
    second_segment_id: str
    gap_ms: int
    evidence_event_ids: tuple[str, ...]
    state: str
    confidence_milli: int

    def __post_init__(self) -> None:
        if not self.continuity_id or not self.first_segment_id or not self.second_segment_id:
            raise UnevenBarsError("continuity identity/segments are required")
        if self.first_segment_id == self.second_segment_id:
            raise UnevenBarsError("continuity requires two distinct segments")
        if isinstance(self.gap_ms, bool) or not isinstance(self.gap_ms, int) or self.gap_ms < 0:
            raise UnevenBarsError("continuity gap_ms must be non-negative integer")
        _milli("continuity confidence", self.confidence_milli)
        if not self.evidence_event_ids:
            raise UnevenBarsError("continuity candidate requires topology event evidence")
        if self.state not in {"continuous", "interrupted", "unresolved"}:
            raise UnevenBarsError("invalid continuity state")


@dataclass(frozen=True)
class UnevenBarsTopologyBundle:
    analysis_id: str
    routine_id: str
    source_media_sha256: str
    contacts: tuple[UBContactInterval, ...]
    events: tuple[UBTopologyEvent, ...]
    elements: tuple[UBElementCandidateRef, ...]
    continuity: tuple[UBContinuityCandidate, ...]
    geometry_digest: str | None
    model_bundle_digest: str
    perception_bundle_digest: str
    created_at: datetime
    limitations: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.analysis_id or not self.routine_id:
            raise UnevenBarsError("UB analysis identity/routine are required")
        for label, value in (
            ("source_media_sha256", self.source_media_sha256),
            ("model_bundle_digest", self.model_bundle_digest),
            ("perception_bundle_digest", self.perception_bundle_digest),
        ):
            _sha(label, value)
        if self.geometry_digest is not None:
            _sha("geometry_digest", self.geometry_digest)
        _aware("created_at", self.created_at)
        contact_ids = [item.contact_id for item in self.contacts]
        event_ids = [item.event_id for item in self.events]
        element_ids = [item.segment_id for item in self.elements]
        continuity_ids = [item.continuity_id for item in self.continuity]
        for label, values in (
            ("contact", contact_ids), ("event", event_ids), ("element", element_ids), ("continuity", continuity_ids)
        ):
            if len(values) != len(set(values)):
                raise UnevenBarsError(f"UB {label} IDs must be unique")
        ordered_contacts = tuple(sorted(self.contacts, key=lambda item: (item.start_ms, item.end_ms, item.contact_id)))
        if ordered_contacts != self.contacts:
            raise UnevenBarsError("UB contacts must be chronological")
        ordered_events = tuple(sorted(self.events, key=lambda item: (item.at_ms, item.event_id)))
        if ordered_events != self.events:
            raise UnevenBarsError("UB topology events must be chronological")
        known_events = set(event_ids)
        known_elements = set(element_ids)
        for item in self.continuity:
            if item.first_segment_id not in known_elements or item.second_segment_id not in known_elements:
                raise UnevenBarsError("continuity references unknown element segment")
            missing = set(item.evidence_event_ids) - known_events
            if missing:
                raise UnevenBarsError("continuity references unknown topology events: " + ",".join(sorted(missing)))
        if self.geometry_digest is None:
            if any(item.bar is not BarIdentity.UNKNOWN for item in self.contacts):
                raise UnevenBarsError("bundle without geometry cannot contain known contact bar identity")
            if any(item.from_bar is not BarIdentity.UNKNOWN or item.to_bar is not BarIdentity.UNKNOWN for item in self.events):
                raise UnevenBarsError("bundle without geometry cannot contain known event bar identity")
        if len(self.limitations) != len(set(self.limitations)):
            raise UnevenBarsError("UB bundle limitations must be unique")

    @property
    def apparatus(self) -> Apparatus:
        return Apparatus.UB

    @property
    def digest(self) -> str:
        return _digest({
            "analysis_id": self.analysis_id,
            "routine_id": self.routine_id,
            "apparatus": self.apparatus.value,
            "source_media_sha256": self.source_media_sha256,
            "contact_digests": [item.digest for item in self.contacts],
            "event_digests": [item.digest for item in self.events],
            "elements": [asdict(item) for item in self.elements],
            "continuity": [asdict(item) for item in self.continuity],
            "geometry_digest": self.geometry_digest,
            "model_bundle_digest": self.model_bundle_digest,
            "perception_bundle_digest": self.perception_bundle_digest,
            "created_at": self.created_at.astimezone(UTC).isoformat(),
            "limitations": list(self.limitations),
        })


def _interval(start_ms: int, end_ms: int) -> None:
    if isinstance(start_ms, bool) or not isinstance(start_ms, int) or start_ms < 0:
        raise UnevenBarsError("start_ms must be non-negative integer")
    if isinstance(end_ms, bool) or not isinstance(end_ms, int) or end_ms <= start_ms:
        raise UnevenBarsError("end_ms must be integer after start_ms")


def _milli(label: str, value: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 1000:
        raise UnevenBarsError(f"{label} must be integer [0, 1000]")


def _sha(label: str, value: str) -> None:
    if len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        raise UnevenBarsError(f"{label} must be lowercase SHA-256 hexadecimal")


def _aware(label: str, value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise UnevenBarsError(f"{label} must be timezone-aware")


def _digest(payload: object) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()
