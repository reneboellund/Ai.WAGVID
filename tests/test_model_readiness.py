from pathlib import Path

import yaml

from ai_wagvid.model_readiness import evaluate_profile_readiness


ROOT = Path(__file__).parents[1]
CATALOG = yaml.safe_load((ROOT / "config" / "model-bundles.yaml").read_text(encoding="utf-8"))
ARTIFACTS = yaml.safe_load((ROOT / "research" / "artifacts.yaml").read_text(encoding="utf-8"))


CURRENT_ARTIFACT_MAP = {
    "mediapipe-pose@0.10": ("mediapipe-pose-landmarker",),
    "rtmpose-coco@1": ("rtmpose-checkpoint",),
    "yolo-pose-coco@8": ("yolo-pose-checkpoint",),
    "mmaction2-temporal@2": ("mmaction2-finegym-checkpoint",),
}


def test_current_competition_rtmpose_profile_is_not_benchmark_ready():
    result = evaluate_profile_readiness(
        catalog=CATALOG,
        artifact_registry=ARTIFACTS,
        profile_id="competition-rtmpose-planned@1",
        component_artifact_map=CURRENT_ARTIFACT_MAP,
    )
    assert result.ready is False
    assert any("rtmpose-coco@1:component-checkpoint-digest-missing" == item for item in result.blockers)
    assert any("rtmpose-coco@1:artifact-not-acquired:rtmpose-checkpoint" == item for item in result.blockers)
    assert any("mmaction2-temporal@2:component-checkpoint-digest-missing" == item for item in result.blockers)
    assert any("mmaction2-temporal@2:artifact-not-acquired:mmaction2-finegym-checkpoint" == item for item in result.blockers)


def test_contract_only_profile_is_not_mistaken_for_real_model_profile():
    result = evaluate_profile_readiness(
        catalog=CATALOG,
        artifact_registry=ARTIFACTS,
        profile_id="competition-research-contract@1",
        component_artifact_map=CURRENT_ARTIFACT_MAP,
    )
    assert result.ready is False
    assert any("component-artifact-status:contract-only" in item for item in result.blockers)


def test_synthetic_frozen_profile_can_be_ready():
    catalog = {
        "components": [
            {
                "id": "pose@1", "capability": "perception", "adapter": "Pose",
                "artifact_status": "validated", "config_digest": "a" * 64,
                "checkpoint_digest": "b" * 64, "limitations": [],
            },
            {
                "id": "action@1", "capability": "action", "adapter": "Action",
                "artifact_status": "validated", "config_digest": "c" * 64,
                "checkpoint_digest": "d" * 64, "limitations": [],
            },
            {
                "id": "interpret@1", "capability": "interpretation", "adapter": "Interpret",
                "artifact_status": "validated", "config_digest": "e" * 64,
                "checkpoint_digest": None, "limitations": [],
            },
        ],
        "profiles": [
            {"id": "profile@1", "mode": "benchmark", "components": ["pose@1", "action@1", "interpret@1"], "apparatus": ["VT"]}
        ],
    }
    artifacts = {
        "artifacts": [
            {"id": "pose-art", "source_url": "https://example.invalid/pose", "sha256": "b" * 64, "acquisition_status": "verified"},
            {"id": "action-art", "source_url": "https://example.invalid/action", "sha256": "d" * 64, "acquisition_status": "verified"},
        ]
    }
    result = evaluate_profile_readiness(
        catalog=catalog,
        artifact_registry=artifacts,
        profile_id="profile@1",
        component_artifact_map={"pose@1": ("pose-art",), "action@1": ("action-art",)},
    )
    assert result.ready is True
    assert result.blockers == ()
