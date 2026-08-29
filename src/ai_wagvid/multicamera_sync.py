"""Multi-camera synchronization and drift modeling without fixed-FPS assumptions."""

from __future__ import annotations

import bisect
import itertools
import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum


class SynchronizationError(ValueError):
    pass


class SyncMethod(StrEnum):
    MANUAL = "manual"
    AUDIO = "audio"
    FLASH = "flash"
    TIMECODE = "timecode"
    PTP = "ptp"


@dataclass(frozen=True)
class SyncAnchor:
    camera_id: str
    source_time_seconds: float
    reference_time_seconds: float
    confidence: float
    method: SyncMethod

    def __post_init__(self) -> None:
        if not self.camera_id:
            raise SynchronizationError("camera_id is required")
        if not all(math.isfinite(value) for value in (self.source_time_seconds, self.reference_time_seconds, self.confidence)):
            raise SynchronizationError("synchronization anchor values must be finite")
        if not 0 < self.confidence <= 1:
            raise SynchronizationError("anchor confidence must be in (0, 1]")


@dataclass(frozen=True)
class ClockFitPolicy:
    minimum_span_seconds: float = 5.0
    maximum_absolute_drift_ppm: float = 2_000.0
    maximum_weighted_rmse_ms: float = 20.0
    maximum_extrapolation_seconds: float = 2.0

    def __post_init__(self) -> None:
        if self.minimum_span_seconds <= 0:
            raise SynchronizationError("minimum anchor span must be positive")
        if self.maximum_absolute_drift_ppm < 0 or self.maximum_weighted_rmse_ms < 0:
            raise SynchronizationError("fit limits cannot be negative")
        if self.maximum_extrapolation_seconds < 0:
            raise SynchronizationError("maximum extrapolation cannot be negative")


@dataclass(frozen=True)
class AffineClockModel:
    camera_id: str
    offset_seconds: float
    scale: float
    weighted_rmse_ms: float
    drift_ppm: float
    source_min_seconds: float
    source_max_seconds: float
    anchor_count: int
    methods: frozenset[SyncMethod]
    policy: ClockFitPolicy

    def __post_init__(self) -> None:
        if self.scale <= 0 or not math.isfinite(self.scale):
            raise SynchronizationError("clock scale must be positive and finite")
        if self.source_max_seconds <= self.source_min_seconds:
            raise SynchronizationError("clock model requires a positive source span")
        if self.anchor_count < 2:
            raise SynchronizationError("clock model requires at least two anchors")

    def to_reference(self, source_time_seconds: float, *, allow_extrapolation: bool = False) -> float:
        self._validate_source_time(source_time_seconds, allow_extrapolation=allow_extrapolation)
        return self.offset_seconds + self.scale * source_time_seconds

    def to_source(self, reference_time_seconds: float, *, allow_extrapolation: bool = False) -> float:
        if not math.isfinite(reference_time_seconds):
            raise SynchronizationError("reference timestamp must be finite")
        source = (reference_time_seconds - self.offset_seconds) / self.scale
        self._validate_source_time(source, allow_extrapolation=allow_extrapolation)
        return source

    def _validate_source_time(self, source: float, *, allow_extrapolation: bool) -> None:
        if not math.isfinite(source):
            raise SynchronizationError("source timestamp must be finite")
        if self.source_min_seconds <= source <= self.source_max_seconds:
            return
        if not allow_extrapolation:
            raise SynchronizationError("timestamp lies outside synchronization anchor span")
        distance = (
            self.source_min_seconds - source
            if source < self.source_min_seconds
            else source - self.source_max_seconds
        )
        if distance > self.policy.maximum_extrapolation_seconds:
            raise SynchronizationError("timestamp extrapolates beyond configured sync limit")


@dataclass(frozen=True)
class FrameStamp:
    index: int
    presentation_time_seconds: float

    def __post_init__(self) -> None:
        if self.index < 0 or not math.isfinite(self.presentation_time_seconds):
            raise SynchronizationError("invalid frame stamp")


@dataclass(frozen=True)
class SynchronizedFrame:
    camera_id: str
    frame: FrameStamp
    mapped_reference_time_seconds: float
    requested_reference_time_seconds: float
    error_ms: float


@dataclass(frozen=True)
class MultiCameraSyncSet:
    reference_camera_id: str
    models: Mapping[str, AffineClockModel]

    def __post_init__(self) -> None:
        if not self.reference_camera_id:
            raise SynchronizationError("reference camera id is required")
        if self.reference_camera_id in self.models:
            raise SynchronizationError("reference camera must not have a drift model against itself")
        if len(self.models) != len(set(self.models)):
            raise SynchronizationError("camera sync model IDs must be unique")


def fit_affine_clock_model(
    camera_id: str,
    anchors: Iterable[SyncAnchor],
    *,
    policy: ClockFitPolicy | None = None,
) -> AffineClockModel:
    policy = policy or ClockFitPolicy()
    values = tuple(anchor for anchor in anchors if anchor.camera_id == camera_id)
    if len(values) < 2:
        raise SynchronizationError("at least two anchors are required for drift estimation")
    ordered = tuple(sorted(values, key=lambda item: item.source_time_seconds))
    source_min = ordered[0].source_time_seconds
    source_max = ordered[-1].source_time_seconds
    span = source_max - source_min
    if span < policy.minimum_span_seconds:
        raise SynchronizationError(
            f"anchor span {span:.6f}s is below minimum {policy.minimum_span_seconds:.6f}s"
        )
    if any(
        right.source_time_seconds <= left.source_time_seconds
        for left, right in itertools.pairwise(ordered)
    ):
        raise SynchronizationError("source anchor timestamps must be strictly increasing")

    weights = [anchor.confidence * anchor.confidence for anchor in ordered]
    weight_sum = sum(weights)
    source_mean = sum(weight * anchor.source_time_seconds for weight, anchor in zip(weights, ordered)) / weight_sum
    reference_mean = sum(weight * anchor.reference_time_seconds for weight, anchor in zip(weights, ordered)) / weight_sum
    covariance = sum(
        weight
        * (anchor.source_time_seconds - source_mean)
        * (anchor.reference_time_seconds - reference_mean)
        for weight, anchor in zip(weights, ordered)
    )
    variance = sum(
        weight * (anchor.source_time_seconds - source_mean) ** 2
        for weight, anchor in zip(weights, ordered)
    )
    if variance <= 0:
        raise SynchronizationError("anchor source variance is zero")
    scale = covariance / variance
    if scale <= 0:
        raise SynchronizationError("estimated clock scale is non-positive")
    offset = reference_mean - scale * source_mean
    residuals = [
        anchor.reference_time_seconds - (offset + scale * anchor.source_time_seconds)
        for anchor in ordered
    ]
    weighted_rmse_ms = 1_000 * math.sqrt(
        sum(weight * residual * residual for weight, residual in zip(weights, residuals)) / weight_sum
    )
    drift_ppm = (scale - 1.0) * 1_000_000.0
    if abs(drift_ppm) > policy.maximum_absolute_drift_ppm:
        raise SynchronizationError(
            f"estimated drift {drift_ppm:.3f} ppm exceeds configured limit"
        )
    if weighted_rmse_ms > policy.maximum_weighted_rmse_ms:
        raise SynchronizationError(
            f"weighted sync RMSE {weighted_rmse_ms:.3f} ms exceeds configured limit"
        )
    return AffineClockModel(
        camera_id=camera_id,
        offset_seconds=offset,
        scale=scale,
        weighted_rmse_ms=weighted_rmse_ms,
        drift_ppm=drift_ppm,
        source_min_seconds=source_min,
        source_max_seconds=source_max,
        anchor_count=len(ordered),
        methods=frozenset(anchor.method for anchor in ordered),
        policy=policy,
    )


def validate_frame_timeline(frames: Iterable[FrameStamp]) -> tuple[FrameStamp, ...]:
    ordered = tuple(frames)
    if not ordered:
        raise SynchronizationError("frame timeline is empty")
    if any(frame.index != expected for expected, frame in enumerate(ordered)):
        raise SynchronizationError("frame indices must be contiguous from zero")
    if any(
        right.presentation_time_seconds < left.presentation_time_seconds
        for left, right in itertools.pairwise(ordered)
    ):
        raise SynchronizationError("frame presentation timestamps must be monotonic")
    return ordered


def select_synchronized_frame(
    model: AffineClockModel,
    frames: Iterable[FrameStamp],
    *,
    reference_time_seconds: float,
    tolerance_ms: float,
    allow_extrapolation: bool = False,
) -> SynchronizedFrame:
    if tolerance_ms < 0:
        raise SynchronizationError("frame synchronization tolerance cannot be negative")
    timeline = validate_frame_timeline(frames)
    source_target = model.to_source(reference_time_seconds, allow_extrapolation=allow_extrapolation)
    times = [frame.presentation_time_seconds for frame in timeline]
    position = bisect.bisect_left(times, source_target)
    candidates = []
    if position < len(timeline):
        candidates.append(timeline[position])
    if position > 0:
        candidates.append(timeline[position - 1])
    selected = min(candidates, key=lambda frame: (abs(frame.presentation_time_seconds - source_target), frame.index))
    mapped = model.to_reference(selected.presentation_time_seconds, allow_extrapolation=allow_extrapolation)
    error_ms = abs(mapped - reference_time_seconds) * 1_000
    if error_ms > tolerance_ms:
        raise SynchronizationError(
            f"nearest synchronized frame error {error_ms:.3f} ms exceeds tolerance"
        )
    return SynchronizedFrame(
        camera_id=model.camera_id,
        frame=selected,
        mapped_reference_time_seconds=mapped,
        requested_reference_time_seconds=reference_time_seconds,
        error_ms=error_ms,
    )


def synchronize_frame_set(
    sync_set: MultiCameraSyncSet,
    timelines: Mapping[str, Iterable[FrameStamp]],
    *,
    reference_time_seconds: float,
    tolerance_ms: float,
    allow_extrapolation: bool = False,
) -> Mapping[str, SynchronizedFrame]:
    results = {}
    for camera_id, model in sync_set.models.items():
        try:
            timeline = timelines[camera_id]
        except KeyError as error:
            raise SynchronizationError(f"missing frame timeline for camera {camera_id}") from error
        results[camera_id] = select_synchronized_frame(
            model,
            timeline,
            reference_time_seconds=reference_time_seconds,
            tolerance_ms=tolerance_ms,
            allow_extrapolation=allow_extrapolation,
        )
    return results
