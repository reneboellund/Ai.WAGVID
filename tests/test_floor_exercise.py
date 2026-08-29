from datetime import UTC, datetime

import pytest

from ai_wagvid.floor_exercise import (
    FloorCapabilityState,
    FloorConnectionCandidate,
    FloorEvidenceRef,
    FloorExerciseBundle,
    FloorExerciseError,
    FloorGeometryCapability,
    FloorInterval,
    FloorIntervalKind,
    FloorObservation,
    FloorObservationKind,
    RoutineTiming,
    TimingSource,
)

T0 = datetime(2026, 8, 17, 20, 0, tzinfo=UTC)
POLYGON = "4" * 64


def evidence(start=0, end=10000):
    return FloorEvidenceRef("e1", "1" * 64, start, end, "camera-corner")


def timing():
    return RoutineTiming(
        start_ms=1000,
        end_ms=9000,
        source=TimingSource.COMBINED,
        timeline_digest="2" * 64,
        confidence_milli=900,
        evidence=(evidence(900, 9100),),
    )


def test_audio_timing_contract_contains_no_music_semantic_fields():
    item = RoutineTiming(
        start_ms=1000,
        end_ms=9000,
        source=TimingSource.AUDIO_TIMELINE,
        timeline_digest="2" * 64,
        confidence_milli=800,
        evidence=(evidence(900, 9100),),
    )
    assert item.duration_ms == 8000
    for forbidden in ("music_style", "artist", "language", "popularity"):
        assert not hasattr(item, forbidden)


def test_element_candidate_interval_requires_temporal_candidate_digest():
    with pytest.raises(FloorExerciseError, match="requires temporal candidate digest"):
        FloorInterval(
            interval_id="acro-1",
            kind=FloorIntervalKind.ACRO_CANDIDATE,
            start_ms=2000,
            end_ms=2500,
            confidence_milli=700,
            evidence=(evidence(1900, 2600),),
        )


def test_unaccepted_floor_candidate_cannot_claim_exact_identity():
    with pytest.raises(FloorExerciseError, match="unaccepted"):
        FloorInterval(
            interval_id="acro-1",
            kind=FloorIntervalKind.ACRO_CANDIDATE,
            start_ms=2000,
            end_ms=2500,
            confidence_milli=700,
            evidence=(evidence(1900, 2600),),
            temporal_candidate_digest="3" * 64,
            family="fixture-family",
            element_id="FX.fixture",
            accepted=False,
        )


def test_boundary_candidate_requires_floor_polygon_calibration():
    with pytest.raises(FloorExerciseError, match="requires calibrated floor polygon"):
        FloorObservation(
            observation_id="boundary-1",
            kind=FloorObservationKind.BOUNDARY_CANDIDATE,
            start_ms=3000,
            end_ms=3100,
            value="foot-near-boundary-candidate",
            confidence_milli=700,
            evidence=(evidence(2900, 3200),),
        )


def test_unavailable_geometry_cannot_emit_boundary_candidate():
    boundary = FloorObservation(
        observation_id="boundary-1",
        kind=FloorObservationKind.BOUNDARY_CANDIDATE,
        start_ms=3000,
        end_ms=3100,
        value="foot-near-boundary-candidate",
        confidence_milli=700,
        evidence=(evidence(2900, 3200),),
        floor_polygon_digest=POLYGON,
    )
    with pytest.raises(FloorExerciseError, match="cannot emit boundary"):
        FloorExerciseBundle(
            analysis_id="fx-1",
            routine_id="routine-1",
            source_media_sha256="5" * 64,
            timing=timing(),
            geometry=FloorGeometryCapability(FloorCapabilityState.UNAVAILABLE, None, "floor not fully visible"),
            intervals=(),
            observations=(boundary,),
            connections=(),
            model_bundle_digest="6" * 64,
            perception_bundle_digest="7" * 64,
            created_at=T0,
        )


def test_connection_requires_timing_evidence_observation():
    with pytest.raises(FloorExerciseError, match="requires timing evidence"):
        FloorConnectionCandidate(
            connection_id="connection-1",
            first_interval_id="acro-1",
            second_interval_id="acro-2",
            gap_ms=40,
            evidence_observation_ids=(),
            state="unresolved",
            confidence_milli=500,
        )


def test_bundle_rejects_interval_outside_routine_timing():
    interval = FloorInterval(
        interval_id="choreo-1",
        kind=FloorIntervalKind.CHOREOGRAPHY,
        start_ms=500,
        end_ms=1200,
        confidence_milli=700,
        evidence=(evidence(400, 1300),),
    )
    with pytest.raises(FloorExerciseError, match="inside routine timing"):
        FloorExerciseBundle(
            analysis_id="fx-1",
            routine_id="routine-1",
            source_media_sha256="5" * 64,
            timing=timing(),
            geometry=FloorGeometryCapability(FloorCapabilityState.UNAVAILABLE, None, "floor not calibrated"),
            intervals=(interval,),
            observations=(),
            connections=(),
            model_bundle_digest="6" * 64,
            perception_bundle_digest="7" * 64,
            created_at=T0,
        )


def test_valid_connection_is_evidence_state_not_connection_value():
    first = FloorInterval(
        interval_id="acro-1",
        kind=FloorIntervalKind.ACRO_CANDIDATE,
        start_ms=2000,
        end_ms=2400,
        confidence_milli=800,
        evidence=(evidence(1900, 2500),),
        temporal_candidate_digest="3" * 64,
    )
    second = FloorInterval(
        interval_id="acro-2",
        kind=FloorIntervalKind.ACRO_CANDIDATE,
        start_ms=2440,
        end_ms=2800,
        confidence_milli=800,
        evidence=(evidence(2400, 2900),),
        temporal_candidate_digest="8" * 64,
    )
    connection_observation = FloorObservation(
        observation_id="connection-timing-1",
        kind=FloorObservationKind.CONNECTION_TIMING,
        start_ms=2380,
        end_ms=2460,
        value="continuous-motion-candidate",
        confidence_milli=750,
        evidence=(evidence(2300, 2500),),
    )
    connection = FloorConnectionCandidate(
        connection_id="connection-1",
        first_interval_id="acro-1",
        second_interval_id="acro-2",
        gap_ms=40,
        evidence_observation_ids=("connection-timing-1",),
        state="continuous",
        confidence_milli=750,
    )
    bundle = FloorExerciseBundle(
        analysis_id="fx-1",
        routine_id="routine-1",
        source_media_sha256="5" * 64,
        timing=timing(),
        geometry=FloorGeometryCapability(FloorCapabilityState.UNAVAILABLE, None, "boundary capability unavailable"),
        intervals=(first, second),
        observations=(connection_observation,),
        connections=(connection,),
        model_bundle_digest="6" * 64,
        perception_bundle_digest="7" * 64,
        created_at=T0,
    )
    assert bundle.apparatus.value == "FX"
    assert not hasattr(connection, "connection_value")
    assert not hasattr(bundle, "d_score")
