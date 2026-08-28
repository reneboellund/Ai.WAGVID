"""Canonical public projections for apparatus promotion artifacts."""

from __future__ import annotations

from typing import Any

from .apparatus_promotion import (
    ApparatusBenchmarkReport,
    ApparatusModelBundle,
    ApparatusPromotionDecision,
)


def apparatus_model_bundle_payload(model: ApparatusModelBundle) -> dict[str, Any]:
    return {
        "schema": "ai.wagvid.apparatus-model-bundle.v1",
        "model_bundle_id": model.model_bundle_id,
        "apparatus": model.apparatus.value,
        "adapter_id": model.adapter_id,
        "adapter_version": model.adapter_version,
        "checkpoint_sha256": model.checkpoint_sha256,
        "config_sha256": model.config_sha256,
        "label_map_sha256": model.label_map_sha256,
        "training_dataset_manifest_sha256": model.training_dataset_manifest_sha256,
        "training_rights_ref": model.training_rights_ref,
        "framework": model.framework,
        "framework_version": model.framework_version,
        "created_at": model.created_at.isoformat(),
        "model_bundle_digest": model.digest,
    }


def apparatus_benchmark_payload(report: ApparatusBenchmarkReport) -> dict[str, Any]:
    return {
        "schema": "ai.wagvid.apparatus-benchmark-report.v1",
        "benchmark_id": report.benchmark_id,
        "apparatus": report.apparatus.value,
        "run_state": report.run_state.value,
        "model_bundle_digest": report.model_bundle_digest,
        "rulepack_digest": report.rulepack_digest,
        "benchmark_manifest_sha256": report.benchmark_manifest_sha256,
        "validation_dataset_manifest_sha256": report.validation_dataset_manifest_sha256,
        "split_manifest_sha256": report.split_manifest_sha256,
        "rights_ref": report.rights_ref,
        "hardware_runtime_manifest_sha256": report.hardware_runtime_manifest_sha256,
        "required_slice_ids": list(report.required_slice_ids),
        "executed_at": report.executed_at.isoformat() if report.executed_at else None,
        "benchmark_digest": report.digest,
        "slices": [
            {
                "slice_id": item.slice_id,
                "dimensions": [{"name": name, "value": value} for name, value in item.dimensions],
                "metrics": [
                    {
                        "metric_id": metric.metric_id,
                        "value_milli": metric.value_milli,
                        "threshold_milli": metric.threshold_milli,
                        "higher_is_better": metric.higher_is_better,
                        "passes": metric.passes,
                    }
                    for metric in item.metrics
                ],
                "status": item.status.value,
                "sample_count": item.sample_count,
                "failure_reason": item.failure_reason,
            }
            for item in report.slices
        ],
    }


def apparatus_promotion_payload(decision: ApparatusPromotionDecision) -> dict[str, Any]:
    return {
        "schema": "ai.wagvid.apparatus-promotion-decision.v1",
        "apparatus": decision.apparatus.value,
        "status": decision.status.value,
        "blockers": list(decision.blockers),
        "model_bundle_digest": decision.model_bundle_digest,
        "rulepack_digest": decision.rulepack_digest,
        "benchmark_digest": decision.benchmark_digest,
        "dscore_ledger_digest": decision.dscore_ledger_digest,
    }
