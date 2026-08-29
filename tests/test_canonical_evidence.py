from datetime import UTC, datetime, timedelta
from fractions import Fraction

import pytest

from ai_wagvid.evidence import (
    CanonicalEvidenceReference,
    CanonicalEvidenceReview,
    CanonicalEvidenceReviewLedger,
    DerivedVisualization,
    EvidenceCalibrationBinding,
    EvidenceMismatch,
    EvidenceReviewDecision,
    VisualizationKind,
    canonical_interval_from_timeline,
    resolve_canonical_interval,
)
from ai_wagvid.media_timeline import FrameTimestamp, build_timeline

T0 = datetime(2026, 8, 17, 10, 0, tzinfo=UTC)


def timeline(source: str = "a" * 64, *, time_base: Fraction = Fraction(1, 90_000)):
    ticks = (0, 3_003, 6_006, 10_010, 13_013)
    return build_timeline(
        source_sha256=source,
        time_base=time_base,
        frames=tuple(
            FrameTimestamp(
                frame_index=index,
                pts=tick,
                dts=tick,
                best_effort_timestamp=tick,
                duration_ticks=None,
                key_frame=index == 0,
            )
            for index, tick in enumerate(ticks)
        ),
    )


def binding() -> EvidenceCalibrationBinding:
    return EvidenceCalibrationBinding(
        intrinsic_id="intrinsic-v2",
        intrinsic_digest="b" * 64,
        extrinsic_id="extrinsic-v3",
        extrinsic_digest="c" * 64,
        apparatus_geometry_id="bb-geometry-v4",
        apparatus_geometry_digest="d" * 64,
        synchronization_digest="e" * 64,
    )


def test_canonical_evidence_preserves_exact_ticks_and_rational_timebase():
    source = timeline()
    interval = canonical_interval_from_timeline(
        source,
        camera_id="cam-a",
        start_frame_index=1,
        end_frame_index=3,
        calibration=binding(),
    )

    assert interval.start_timestamp_ticks == 3_003
    assert interval.end_timestamp_ticks == 10_010
    assert interval.time_base == Fraction(1, 90_000)
    assert interval.start_seconds == Fraction(3_003, 90_000)
    assert interval.end_seconds == Fraction(10_010, 90_000)
    assert [frame.frame_index for frame in resolve_canonical_interval(interval, timeline=source)] == [1, 2, 3]


def test_canonical_evidence_rejects_changed_source_timeline_or_ticks():
    source = timeline()
    interval = canonical_interval_from_timeline(
        source,
        camera_id="cam-a",
        start_frame_index=1,
        end_frame_index=2,
    )

    with pytest.raises(EvidenceMismatch, match="timeline/source"):
        resolve_canonical_interval(interval, timeline=timeline("f" * 64))

    altered = build_timeline(
        source_sha256=source.source_sha256,
        time_base=source.time_base,
        frames=tuple(
            FrameTimestamp(
                frame_index=frame.frame_index,
                pts=frame.pts,
                dts=frame.dts,
                best_effort_timestamp=(frame.best_effort_timestamp + 1 if frame.frame_index == 2 else frame.best_effort_timestamp),
                duration_ticks=frame.duration_ticks,
                key_frame=frame.key_frame,
            )
            for frame in source.frames
        ),
    )
    with pytest.raises(EvidenceMismatch, match="timeline/source"):
        resolve_canonical_interval(interval, timeline=altered)


def test_calibration_bindings_require_id_and_digest_as_a_pair():
    with pytest.raises(ValueError, match="supplied together"):
        EvidenceCalibrationBinding(intrinsic_id="intrinsic-v1")
    with pytest.raises(ValueError, match="SHA-256"):
        EvidenceCalibrationBinding(
            intrinsic_id="intrinsic-v1",
            intrinsic_digest="not-a-digest",
        )


def test_multi_camera_evidence_has_one_source_digest_independent_of_visualizations():
    source = timeline()
    first = canonical_interval_from_timeline(
        source,
        camera_id="cam-a",
        start_frame_index=1,
        end_frame_index=3,
        calibration=binding(),
    )
    second = canonical_interval_from_timeline(
        source,
        camera_id="cam-b",
        start_frame_index=1,
        end_frame_index=3,
        calibration=EvidenceCalibrationBinding(synchronization_digest="9" * 64),
    )
    base = CanonicalEvidenceReference(
        evidence_id="ev-multicam-1",
        intervals=(first, second),
        created_at=T0,
        purpose="beam-series-review",
        producer="review-ui",
        producer_version="2",
    )
    visualization = DerivedVisualization(
        visualization_id="overlay-1",
        kind=VisualizationKind.POSE_OVERLAY,
        artifact_sha256="1" * 64,
        generator_name="pose-renderer",
        generator_digest="2" * 64,
        source_evidence_digest=base.source_digest,
        generated_at=T0 + timedelta(seconds=1),
    )
    with_overlay = CanonicalEvidenceReference(
        evidence_id=base.evidence_id,
        intervals=base.intervals,
        created_at=base.created_at,
        purpose=base.purpose,
        producer=base.producer,
        producer_version=base.producer_version,
        derived_visualizations=(visualization,),
    )

    assert base.source_digest == with_overlay.source_digest
    assert base.digest != with_overlay.digest
    assert visualization.is_original_evidence is False


def test_visualization_cannot_be_attached_to_different_source_evidence():
    source = timeline()
    interval = canonical_interval_from_timeline(
        source,
        camera_id="cam-a",
        start_frame_index=0,
        end_frame_index=1,
    )
    bad_visualization = DerivedVisualization(
        visualization_id="overlay-bad",
        kind=VisualizationKind.INTERPOLATED_VIEW,
        artifact_sha256="1" * 64,
        generator_name="interpolator",
        generator_digest="2" * 64,
        source_evidence_digest="3" * 64,
        generated_at=T0,
    )
    with pytest.raises(EvidenceMismatch, match="different source evidence"):
        CanonicalEvidenceReference(
            evidence_id="ev-1",
            intervals=(interval,),
            created_at=T0,
            purpose="frame-review",
            producer="review-ui",
            producer_version="2",
            derived_visualizations=(bad_visualization,),
        )


def test_material_review_history_is_append_only_and_cannot_fork():
    source = timeline()
    interval = canonical_interval_from_timeline(
        source,
        camera_id="cam-a",
        start_frame_index=1,
        end_frame_index=2,
    )
    evidence = CanonicalEvidenceReference(
        evidence_id="ev-review",
        intervals=(interval,),
        created_at=T0,
        purpose="element-identity",
        producer="model",
        producer_version="bundle-1",
    )
    first = CanonicalEvidenceReview(
        review_id="review-1",
        evidence_digest=evidence.digest,
        author_id="judge-a",
        decision=EvidenceReviewDecision.UNRESOLVED,
        reason="Two element identities remain plausible",
        created_at=T0 + timedelta(minutes=1),
    )
    second = CanonicalEvidenceReview(
        review_id="review-2",
        evidence_digest=evidence.digest,
        author_id="judge-b",
        decision=EvidenceReviewDecision.REVISED,
        reason="Second camera resolves body shape",
        created_at=T0 + timedelta(minutes=2),
        supersedes_review_id="review-1",
    )
    ledger = CanonicalEvidenceReviewLedger([first, second])
    assert ledger.current(evidence.digest) == second
    assert ledger.history(evidence.digest) == (first, second)

    with pytest.raises(ValueError, match="cannot fork"):
        ledger.append(
            CanonicalEvidenceReview(
                review_id="review-3",
                evidence_digest=evidence.digest,
                author_id="judge-c",
                decision=EvidenceReviewDecision.REJECTED,
                reason="Conflicting alternate review",
                created_at=T0 + timedelta(minutes=3),
                supersedes_review_id="review-1",
            )
        )
