from datetime import UTC, datetime, timedelta

import pytest

from ai_wagvid.camera_calibration import (
    CalibrationError,
    CalibrationRegistry,
    CameraIdentity,
    ExtrinsicCalibration,
    IntrinsicCalibration,
)
from ai_wagvid.multicamera_sync import (
    AffineClockModel,
    ClockFitPolicy,
    FrameStamp,
    MultiCameraSyncSet,
    SyncAnchor,
    SyncMethod,
    SynchronizationError,
    fit_affine_clock_model,
    select_synchronized_frame,
    synchronize_frame_set,
    validate_frame_timeline,
)


PROVENANCE = "a" * 64
T0 = datetime(2026, 8, 17, 8, 0, tzinfo=UTC)


def camera(camera_id: str = "cam-a", fingerprint: str = "sha256:camera-a") -> CameraIdentity:
    return CameraIdentity(
        camera_id=camera_id,
        device_id=f"device-{camera_id}",
        hardware_fingerprint=fingerprint,
        display_name=f"Camera {camera_id}",
    )


def intrinsic(
    calibration_id: str,
    *,
    camera_id: str = "cam-a",
    effective_from: datetime = T0,
    supersedes_id: str | None = None,
) -> IntrinsicCalibration:
    return IntrinsicCalibration(
        calibration_id=calibration_id,
        camera_id=camera_id,
        effective_from=effective_from,
        image_width=1920,
        image_height=1080,
        fx=1200.0,
        fy=1198.0,
        cx=960.0,
        cy=540.0,
        distortion=(0.01, -0.02, 0.0, 0.0, 0.001),
        method="checkerboard-v1",
        sample_count=24,
        reprojection_rmse_px=0.21,
        provenance_sha256=PROVENANCE,
        supersedes_id=supersedes_id,
    )


def extrinsic(
    calibration_id: str,
    *,
    camera_id: str = "cam-a",
    effective_from: datetime = T0,
    supersedes_id: str | None = None,
    rotation: tuple[float, ...] = (1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0),
) -> ExtrinsicCalibration:
    return ExtrinsicCalibration(
        calibration_id=calibration_id,
        camera_id=camera_id,
        effective_from=effective_from,
        reference_frame="gym-hall-v1",
        rotation_row_major=rotation,
        translation_m=(1.0, 2.0, 3.0),
        alignment_rmse_m=0.006,
        sample_count=12,
        provenance_sha256=PROVENANCE,
        supersedes_id=supersedes_id,
    )


def test_camera_identity_and_hardware_fingerprint_are_immutable():
    registry = CalibrationRegistry([camera()])
    registry.add_camera(camera())

    with pytest.raises(CalibrationError, match="different hardware"):
        registry.add_camera(
            CameraIdentity(
                camera_id="cam-a",
                device_id="different-device",
                hardware_fingerprint="sha256:different",
                display_name="Replacement camera",
            )
        )

    with pytest.raises(CalibrationError, match="already registered"):
        registry.add_camera(camera("cam-b", fingerprint="sha256:camera-a"))


def test_calibration_history_is_append_only_and_timestamp_resolved():
    registry = CalibrationRegistry([camera()])
    first = intrinsic("intrinsic-v1")
    second = intrinsic(
        "intrinsic-v2",
        effective_from=T0 + timedelta(days=1),
        supersedes_id=first.calibration_id,
    )
    registry.add_intrinsic(first)
    registry.add_intrinsic(second)

    assert registry.select("cam-a", T0 + timedelta(hours=12)).intrinsic == first
    assert registry.select("cam-a", T0 + timedelta(days=2)).intrinsic == second
    assert registry.intrinsic_history("cam-a") == (first, second)

    with pytest.raises(CalibrationError, match="explicitly supersede"):
        registry.add_intrinsic(intrinsic("intrinsic-v3", effective_from=T0 + timedelta(days=3)))

    with pytest.raises(CalibrationError, match="cannot fork"):
        registry.add_intrinsic(
            intrinsic(
                "intrinsic-v4",
                effective_from=T0 + timedelta(days=4),
                supersedes_id=first.calibration_id,
            )
        )


def test_selection_before_first_calibration_fails_closed_with_warnings():
    registry = CalibrationRegistry([camera()])
    registry.add_intrinsic(intrinsic("intrinsic-v1", effective_from=T0 + timedelta(hours=1)))

    selection = registry.select("cam-a", T0)
    assert selection.analysis_ready is False
    assert selection.intrinsic is None
    assert selection.extrinsic is None
    assert selection.warnings == (
        "intrinsic-calibration-unavailable",
        "extrinsic-calibration-unavailable",
    )


def test_extrinsic_rotation_must_be_a_proper_rotation_not_a_reflection():
    reflection = (1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, -1.0)
    with pytest.raises(CalibrationError, match="determinant must be \+1"):
        extrinsic("extrinsic-reflection", rotation=reflection)


def test_calibration_digest_is_stable_and_changes_with_evidence():
    baseline = intrinsic("intrinsic-v1")
    same = intrinsic("intrinsic-v1")
    changed = IntrinsicCalibration(
        **{
            **baseline.__dict__,
            "reprojection_rmse_px": 0.22,
        }
    )
    assert baseline.digest == same.digest
    assert baseline.digest != changed.digest


def anchors_for(
    camera_id: str,
    *,
    offset: float,
    scale: float,
    source_times: tuple[float, ...] = (0.0, 10.0, 20.0),
) -> tuple[SyncAnchor, ...]:
    return tuple(
        SyncAnchor(
            camera_id=camera_id,
            source_time_seconds=source,
            reference_time_seconds=offset + scale * source,
            confidence=1.0,
            method=SyncMethod.FLASH,
        )
        for source in source_times
    )


def test_affine_clock_fit_recovers_offset_and_known_ppm_drift():
    model = fit_affine_clock_model(
        "cam-b",
        anchors_for("cam-b", offset=0.25, scale=1.0001),
    )
    assert model.offset_seconds == pytest.approx(0.25, abs=1e-12)
    assert model.scale == pytest.approx(1.0001, abs=1e-12)
    assert model.drift_ppm == pytest.approx(100.0, abs=1e-6)
    assert model.weighted_rmse_ms == pytest.approx(0.0, abs=1e-9)
    assert model.to_reference(12.5) == pytest.approx(12.75125)
    assert model.to_source(12.75125) == pytest.approx(12.5)


def test_clock_fit_rejects_residual_outlier_even_when_drift_limit_is_relaxed():
    anchors = list(anchors_for("cam-b", offset=0.0, scale=1.0))
    anchors[1] = SyncAnchor(
        camera_id="cam-b",
        source_time_seconds=10.0,
        reference_time_seconds=10.2,
        confidence=1.0,
        method=SyncMethod.MANUAL,
    )
    policy = ClockFitPolicy(
        maximum_absolute_drift_ppm=1_000_000.0,
        maximum_weighted_rmse_ms=5.0,
    )
    with pytest.raises(SynchronizationError, match="weighted sync RMSE"):
        fit_affine_clock_model("cam-b", anchors, policy=policy)


def identity_model(*, maximum_extrapolation_seconds: float = 2.0) -> AffineClockModel:
    return fit_affine_clock_model(
        "cam-b",
        anchors_for("cam-b", offset=0.0, scale=1.0, source_times=(0.0, 10.0)),
        policy=ClockFitPolicy(maximum_extrapolation_seconds=maximum_extrapolation_seconds),
    )


def test_clock_mapping_extrapolation_is_bounded_and_opt_in():
    model = identity_model(maximum_extrapolation_seconds=2.0)
    with pytest.raises(SynchronizationError, match="outside synchronization anchor span"):
        model.to_reference(-1.0)
    assert model.to_reference(-1.0, allow_extrapolation=True) == pytest.approx(-1.0)
    with pytest.raises(SynchronizationError, match="beyond configured sync limit"):
        model.to_reference(-2.1, allow_extrapolation=True)


def test_vfr_frame_selection_uses_presentation_timestamps_not_assumed_fps():
    model = identity_model()
    frames = (
        FrameStamp(0, 0.000),
        FrameStamp(1, 0.033),
        FrameStamp(2, 0.075),
        FrameStamp(3, 0.120),
    )
    selected = select_synchronized_frame(
        model,
        frames,
        reference_time_seconds=0.080,
        tolerance_ms=10.0,
    )
    assert selected.frame.index == 2
    assert selected.frame.presentation_time_seconds == pytest.approx(0.075)
    assert selected.error_ms == pytest.approx(5.0)

    with pytest.raises(SynchronizationError, match="exceeds tolerance"):
        select_synchronized_frame(
            model,
            frames,
            reference_time_seconds=0.080,
            tolerance_ms=1.0,
        )


def test_frame_timeline_rejects_non_monotonic_or_non_contiguous_data():
    with pytest.raises(SynchronizationError, match="contiguous"):
        validate_frame_timeline((FrameStamp(0, 0.0), FrameStamp(2, 0.04)))
    with pytest.raises(SynchronizationError, match="monotonic"):
        validate_frame_timeline((FrameStamp(0, 0.04), FrameStamp(1, 0.03)))


def test_multicamera_frame_set_requires_every_camera_timeline():
    model = identity_model()
    sync_set = MultiCameraSyncSet(reference_camera_id="cam-a", models={"cam-b": model})
    with pytest.raises(SynchronizationError, match="missing frame timeline"):
        synchronize_frame_set(
            sync_set,
            {},
            reference_time_seconds=1.0,
            tolerance_ms=20.0,
        )
