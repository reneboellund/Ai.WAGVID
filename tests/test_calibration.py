from datetime import UTC, datetime

import pytest

from ai_wagvid.calibration import ApparatusCalibration, CameraClockMapping
from ai_wagvid.domain import Apparatus, TimeRange


def test_beam_calibration_roundtrip_identity_is_deterministic():
    calibration = ApparatusCalibration(
        "bb-cam-1-r1", "cam-1", Apparatus.BB, "a" * 64, 1, TimeRange(0, 60),
        {"beam_start": [0.1, 0.7], "beam_end": [0.9, 0.7]},
        datetime(2026, 1, 1, tzinfo=UTC), "reviewer-1",
    )
    assert len(calibration.digest) == 64


def test_floor_calibration_rejects_invalid_normalized_polygon():
    with pytest.raises(ValueError, match="normalized"):
        ApparatusCalibration(
            "fx-1", "cam", Apparatus.FX, "a" * 64, 1, TimeRange(0, 1),
            {"floor_polygon": [[0, 0], [2, 0], [0, 1]]},
            datetime.now(UTC), "reviewer",
        )


def test_camera_clock_mapping_surfaces_drift_uncertainty():
    mapping = CameraClockMapping("cam-2", "cam-1", -0.05, 100, (0, 10), 2, "b" * 64)
    assert mapping.to_reference_time(10) == pytest.approx(9.951)
    assert mapping.uncertainty_ms(20) > mapping.residual_error_ms
