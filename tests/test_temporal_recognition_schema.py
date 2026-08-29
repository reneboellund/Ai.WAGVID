import json
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

from ai_wagvid.domain import Apparatus
from ai_wagvid.temporal_exports import temporal_recognition_payload
from ai_wagvid.temporal_recognition import (
    CandidateProbabilityMass,
    DistinguishingObservation,
    ElementAlternative,
    MultiViewIntervalRef,
    TemporalElementCandidate,
    TemporalRecognitionBundle,
)

ROOT = Path(__file__).parents[1]
SCHEMA = json.loads(
    (ROOT / "schemas" / "temporal-recognition-v1.schema.json").read_text(encoding="utf-8")
)
VALIDATOR = Draft202012Validator(SCHEMA, format_checker=FormatChecker())
T0 = datetime(2026, 8, 17, 20, 0, tzinfo=UTC)


def payload() -> dict:
    observation = DistinguishingObservation(
        observation_id="obs-1",
        evidence_digest="1" * 64,
        attribute="body-shape",
        value="fixture-shape",
        confidence_milli=900,
    )
    candidate = TemporalElementCandidate(
        segment_id="segment-1",
        routine_id="routine-1",
        apparatus=Apparatus.BB,
        start_ms=1000,
        end_ms=2000,
        views=(
            MultiViewIntervalRef(
                media_sha256="2" * 64,
                camera_id="cam-side",
                start_ms=900,
                end_ms=2100,
                evidence_digest="3" * 64,
            ),
        ),
        observations=(observation,),
        probability=CandidateProbabilityMass(
            alternatives=(
                ElementAlternative(
                    element_id="BB.a",
                    family="family-a",
                    probability_milli=700,
                    distinguishing_observation_ids=("obs-1",),
                ),
            ),
            unknown_ood_milli=200,
            other_known_milli=100,
        ),
        model_bundle_digest="4" * 64,
        model_config_digest="5" * 64,
        perception_bundle_digest="6" * 64,
        sequence_context_digest="7" * 64,
        created_at=T0,
    )
    bundle = TemporalRecognitionBundle(
        bundle_id="bundle-1",
        routine_id="routine-1",
        apparatus=Apparatus.BB,
        candidates=(candidate,),
        model_bundle_digest="4" * 64,
        perception_bundle_digest="6" * 64,
        created_at=T0,
    )
    return temporal_recognition_payload(bundle)


def test_serializer_output_validates_against_public_schema():
    errors = list(VALIDATOR.iter_errors(payload()))
    assert errors == []


def test_public_temporal_payload_rejects_score_fields():
    value = payload()
    value["candidates"][0]["d_score"] = 5.4
    errors = list(VALIDATOR.iter_errors(value))
    assert any("Additional properties are not allowed" in error.message for error in errors)


def test_public_temporal_payload_rejects_official_result_context():
    value = payload()
    value["official_result"] = {"final": 13.1}
    errors = list(VALIDATOR.iter_errors(value))
    assert any("Additional properties are not allowed" in error.message for error in errors)


def test_schema_does_not_silently_accept_mutated_probability_shape():
    value = deepcopy(payload())
    value["candidates"][0]["probability"]["confidence"] = 0.99
    errors = list(VALIDATOR.iter_errors(value))
    assert any("Additional properties are not allowed" in error.message for error in errors)
