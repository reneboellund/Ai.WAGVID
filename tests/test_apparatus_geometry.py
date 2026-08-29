from datetime import UTC, datetime, timedelta

import pytest

from ai_wagvid.apparatus_geometry import (
    Apparatus,
    ApparatusGeometryError,
    ApparatusGeometryRecord,
    ApparatusGeometryRegistry,
    BeamGeometry,
    FloorGeometry,
    ImagePoint,
    ImagePolygon,
    ImageSegment,
    UnevenBarsGeometry,
    VaultGeometry,
    require_geometry_capabilities,
)

T0 = datetime(2026, 8, 17, 9, 0, tzinfo=UTC)
SOURCE_SHA = "b" * 64


def polygon(*coords: tuple[float, float]) -> ImagePolygon:
    return ImagePolygon(tuple(ImagePoint(x, y) for x, y in coords))


def square() -> ImagePolygon:
    return polygon((0.1, 0.1), (0.9, 0.1), (0.9, 0.9), (0.1, 0.9))


def record(
    geometry_id: str,
    geometry,
    *,
    effective_from: datetime = T0,
    supersedes_id: str | None = None,
) -> ApparatusGeometryRecord:
    return ApparatusGeometryRecord(
        geometry_id=geometry_id,
        camera_id="cam-a",
        intrinsic_calibration_id="intrinsic-v1",
        extrinsic_calibration_id="extrinsic-v1",
        effective_from=effective_from,
        source_media_sha256=SOURCE_SHA,
        source_frame_index=120,
        method="manual-reviewed-v1",
        quality_score=0.95,
        geometry=geometry,
        supersedes_id=supersedes_id,
    )


def test_image_geometry_is_normalized_and_polygon_contains_boundary():
    floor = square()
    assert floor.area == pytest.approx(0.64)
    assert floor.contains(ImagePoint(0.5, 0.5)) is True
    assert floor.contains(ImagePoint(0.1, 0.5)) is True
    assert floor.contains(ImagePoint(0.05, 0.5)) is False

    with pytest.raises(ApparatusGeometryError, match="normalized"):
        ImagePoint(1.01, 0.5)


def test_polygon_rejects_degenerate_or_self_crossing_shapes():
    with pytest.raises(ApparatusGeometryError):
        polygon((0.0, 0.0), (1.0, 1.0), (0.0, 1.0), (1.0, 0.0))
    with pytest.raises(ApparatusGeometryError, match="non-zero length"):
        ImageSegment(ImagePoint(0.5, 0.5), ImagePoint(0.5, 0.5))


def test_beam_axis_must_be_supported_by_calibrated_beam_region():
    region = polygon((0.1, 0.45), (0.9, 0.45), (0.9, 0.55), (0.1, 0.55))
    geometry = BeamGeometry(
        beam_region=region,
        beam_axis=ImageSegment(ImagePoint(0.1, 0.5), ImagePoint(0.9, 0.5)),
    )
    assert geometry.capabilities == frozenset({"beam-region", "beam-axis", "beam-ends"})

    with pytest.raises(ApparatusGeometryError, match="axis start"):
        BeamGeometry(
            beam_region=region,
            beam_axis=ImageSegment(ImagePoint(0.0, 0.5), ImagePoint(0.9, 0.5)),
        )


def test_uneven_bars_expose_centers_without_claiming_metric_3d_geometry():
    geometry = UnevenBarsGeometry(
        high_bar_axis=ImageSegment(ImagePoint(0.55, 0.2), ImagePoint(0.75, 0.2)),
        low_bar_axis=ImageSegment(ImagePoint(0.25, 0.5), ImagePoint(0.45, 0.5)),
    )
    assert geometry.high_bar_center == ImagePoint(0.65, 0.2)
    assert geometry.low_bar_center == ImagePoint(0.35, 0.5)
    assert geometry.capabilities == frozenset({"high-bar-axis", "low-bar-axis", "bar-centers"})

    with pytest.raises(ApparatusGeometryError, match="different bars"):
        UnevenBarsGeometry(
            high_bar_axis=ImageSegment(ImagePoint(0.4, 0.3), ImagePoint(0.6, 0.3)),
            low_bar_axis=ImageSegment(ImagePoint(0.5, 0.2), ImagePoint(0.5, 0.4)),
        )


def test_vault_capabilities_only_include_geometry_that_was_calibrated():
    geometry = VaultGeometry(
        table_region=polygon((0.4, 0.2), (0.6, 0.2), (0.6, 0.35), (0.4, 0.35)),
        springboard_region=polygon((0.2, 0.65), (0.35, 0.65), (0.35, 0.75), (0.2, 0.75)),
    )
    assert geometry.capabilities == frozenset({"table-region", "springboard-region"})
    blockers = require_geometry_capabilities(record("vt-v1", geometry), "landing-region")
    assert blockers == ("missing-geometry:landing-region",)


def test_missing_floor_boundary_fails_closed_instead_of_implying_in_bounds():
    assert require_geometry_capabilities(None, "floor-boundary") == (
        "apparatus-geometry-unavailable",
    )
    floor = record("fx-v1", FloorGeometry(square()))
    assert require_geometry_capabilities(floor, "floor-boundary") == ()


def test_geometry_history_is_linear_immutable_and_timestamp_resolved():
    registry = ApparatusGeometryRegistry()
    first = record("fx-v1", FloorGeometry(square()))
    second = record(
        "fx-v2",
        FloorGeometry(polygon((0.12, 0.12), (0.88, 0.12), (0.88, 0.88), (0.12, 0.88))),
        effective_from=T0 + timedelta(days=1),
        supersedes_id="fx-v1",
    )
    registry.add(first)
    registry.add(second)

    assert registry.select("cam-a", Apparatus.FX, T0 + timedelta(hours=12)) == first
    assert registry.select("cam-a", Apparatus.FX, T0 + timedelta(days=2)) == second
    assert registry.history("cam-a", Apparatus.FX) == (first, second)

    with pytest.raises(ApparatusGeometryError, match="must supersede"):
        registry.add(
            record(
                "fx-v3",
                FloorGeometry(square()),
                effective_from=T0 + timedelta(days=3),
            )
        )

    with pytest.raises(ApparatusGeometryError, match="cannot fork"):
        registry.add(
            record(
                "fx-v4",
                FloorGeometry(square()),
                effective_from=T0 + timedelta(days=4),
                supersedes_id="fx-v1",
            )
        )


def test_geometry_digest_binds_source_frame_and_calibration_references():
    baseline = record("fx-v1", FloorGeometry(square()))
    same = record("fx-v1", FloorGeometry(square()))
    changed_frame = ApparatusGeometryRecord(
        **{
            **baseline.__dict__,
            "source_frame_index": baseline.source_frame_index + 1,
        }
    )
    assert baseline.digest == same.digest
    assert baseline.digest != changed_frame.digest
