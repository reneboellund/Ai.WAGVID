from datetime import UTC, datetime

import pytest

from ai_wagvid.uneven_bars import (
    BarIdentity,
    ContactState,
    TopologyEventKind,
    UBContactInterval,
    UBContinuityCandidate,
    UBElementCandidateRef,
    UBReferenceEvidence,
    UBTopologyEvent,
    UnevenBarsError,
    UnevenBarsTopologyBundle,
)


T0 = datetime(2026, 8, 17, 20, 0, tzinfo=UTC)
GEOMETRY = "4" * 64


def evidence(start=0, end=1000):
    return UBReferenceEvidence(
        evidence_id=f"e-{start}-{end}",
        evidence_digest="1" * 64,
        start_ms=start,
        end_ms=end,
        camera_id="camera-side",
    )


def event(event_id, kind, at, *, from_bar=BarIdentity.UNKNOWN, to_bar=BarIdentity.UNKNOWN, geometry=None):
    return UBTopologyEvent(
        event_id=event_id,
        kind=kind,
        at_ms=at,
        from_bar=from_bar,
        to_bar=to_bar,
        confidence_milli=850,
        evidence=(evidence(max(0, at - 20), at + 20),),
        geometry_digest=geometry,
    )


def element(segment_id, start, end, *, accepted=False):
    return UBElementCandidateRef(
        segment_id=segment_id,
        temporal_candidate_digest=("2" if segment_id == "s1" else "3") * 64,
        start_ms=start,
        end_ms=end,
        family="fixture-family" if accepted else None,
        element_id="UB.fixture" if accepted else None,
        accepted=accepted,
    )


def test_known_bar_contact_requires_geometry():
    with pytest.raises(UnevenBarsError, match="requires calibrated bar geometry"):
        UBContactInterval(
            contact_id="c1",
            start_ms=100,
            end_ms=200,
            state=ContactState.HANG,
            bar=BarIdentity.HIGH,
            confidence_milli=900,
            evidence=(evidence(90, 210),),
            geometry_digest=None,
        )


def test_unknown_bar_contact_remains_valid_without_geometry():
    contact = UBContactInterval(
        contact_id="c1",
        start_ms=100,
        end_ms=200,
        state=ContactState.HANG,
        bar=BarIdentity.UNKNOWN,
        confidence_milli=700,
        evidence=(evidence(90, 210),),
    )
    assert contact.bar is BarIdentity.UNKNOWN


def test_bar_change_requires_two_known_different_bars():
    with pytest.raises(UnevenBarsError, match="known from/to"):
        event("bar-change", TopologyEventKind.BAR_CHANGE, 300, geometry=GEOMETRY)
    with pytest.raises(UnevenBarsError, match="must change"):
        event(
            "bar-change",
            TopologyEventKind.BAR_CHANGE,
            300,
            from_bar=BarIdentity.HIGH,
            to_bar=BarIdentity.HIGH,
            geometry=GEOMETRY,
        )


def test_unaccepted_candidate_cannot_claim_exact_identity():
    with pytest.raises(UnevenBarsError, match="unaccepted"):
        UBElementCandidateRef(
            segment_id="s1",
            temporal_candidate_digest="2" * 64,
            start_ms=100,
            end_ms=200,
            family="fixture-family",
            element_id="UB.fixture",
            accepted=False,
        )


def test_continuity_requires_topology_event_evidence():
    with pytest.raises(UnevenBarsError, match="requires topology event evidence"):
        UBContinuityCandidate(
            continuity_id="continuity-1",
            first_segment_id="s1",
            second_segment_id="s2",
            gap_ms=20,
            evidence_event_ids=(),
            state="continuous",
            confidence_milli=800,
        )


def test_bundle_rejects_continuity_referencing_unknown_event():
    with pytest.raises(UnevenBarsError, match="unknown topology events"):
        UnevenBarsTopologyBundle(
            analysis_id="ub-1",
            routine_id="routine-1",
            source_media_sha256="5" * 64,
            contacts=(),
            events=(),
            elements=(element("s1", 100, 200), element("s2", 220, 300)),
            continuity=(
                UBContinuityCandidate(
                    continuity_id="continuity-1",
                    first_segment_id="s1",
                    second_segment_id="s2",
                    gap_ms=20,
                    evidence_event_ids=("release-1",),
                    state="unresolved",
                    confidence_milli=500,
                ),
            ),
            geometry_digest=None,
            model_bundle_digest="6" * 64,
            perception_bundle_digest="7" * 64,
            created_at=T0,
        )


def test_release_regrasp_topology_can_support_continuity_without_awarding_connection():
    release = event(
        "release-1",
        TopologyEventKind.RELEASE,
        200,
        from_bar=BarIdentity.HIGH,
        to_bar=BarIdentity.UNKNOWN,
        geometry=GEOMETRY,
    )
    regrasp = event(
        "regrasp-1",
        TopologyEventKind.REGRASP,
        240,
        from_bar=BarIdentity.UNKNOWN,
        to_bar=BarIdentity.HIGH,
        geometry=GEOMETRY,
    )
    continuity = UBContinuityCandidate(
        continuity_id="continuity-1",
        first_segment_id="s1",
        second_segment_id="s2",
        gap_ms=40,
        evidence_event_ids=("release-1", "regrasp-1"),
        state="continuous",
        confidence_milli=800,
    )
    bundle = UnevenBarsTopologyBundle(
        analysis_id="ub-1",
        routine_id="routine-1",
        source_media_sha256="5" * 64,
        contacts=(),
        events=(release, regrasp),
        elements=(element("s1", 100, 200, accepted=True), element("s2", 240, 320, accepted=True)),
        continuity=(continuity,),
        geometry_digest=GEOMETRY,
        model_bundle_digest="6" * 64,
        perception_bundle_digest="7" * 64,
        created_at=T0,
    )
    assert bundle.apparatus.value == "UB"
    assert not hasattr(bundle, "connection_value")
    assert not hasattr(bundle, "d_score")


def test_bundle_without_geometry_rejects_known_bar_event():
    release = event(
        "release-1",
        TopologyEventKind.RELEASE,
        200,
        from_bar=BarIdentity.HIGH,
        to_bar=BarIdentity.UNKNOWN,
        geometry=GEOMETRY,
    )
    with pytest.raises(UnevenBarsError, match="bundle without geometry"):
        UnevenBarsTopologyBundle(
            analysis_id="ub-1",
            routine_id="routine-1",
            source_media_sha256="5" * 64,
            contacts=(),
            events=(release,),
            elements=(),
            continuity=(),
            geometry_digest=None,
            model_bundle_digest="6" * 64,
            perception_bundle_digest="7" * 64,
            created_at=T0,
        )
