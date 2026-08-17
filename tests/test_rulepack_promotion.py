from pathlib import Path

from ai_wagvid.rulepack_promotion import evaluate_rulepack_readiness
from wagvid_rules.validation import load_yaml


ROOT = Path(__file__).parents[1]


def test_current_repository_example_rulepack_is_not_release_ready():
    manifest = load_yaml(ROOT / "rules" / "rulepack-manifest.example.yaml")
    registry = load_yaml(ROOT / "rules" / "registry.yaml")
    result = evaluate_rulepack_readiness(manifest=manifest, registry=registry)
    assert result.ready is False
    assert "rulepack-manifest-not-approved" in result.blockers
    assert "rulepack-manifest-sha256-missing-or-invalid" in result.blockers
    assert "rulepack-review-metadata-missing" in result.blockers
    assert any(item.startswith("rulepack-source-not-approved:") for item in result.blockers)


def test_reviewed_frozen_rulepack_snapshot_can_be_release_ready():
    source_id = "wag-source-fixture"
    registry = {
        "sources": [
            {
                "id": source_id,
                "status": "current",
                "interpretation_status": "approved",
                "review": {"reviewer": "qualified-wag-reviewer", "date": "2026-08-17"},
                "retention": "metadata-only",
                "content_sha256": None,
            }
        ]
    }
    manifest = {
        "rulepack_id": "FIG-WAG-fixture-approved",
        "status": "approved",
        "source_ids": [source_id],
        "manifest_sha256": "1" * 64,
        "review": {"reviewer": "qualified-wag-reviewer", "date": "2026-08-17"},
        "artifacts": [{"path": "rules/fixture.json", "sha256": "2" * 64}],
    }
    result = evaluate_rulepack_readiness(manifest=manifest, registry=registry)
    assert result.ready is True
    assert result.blockers == ()
