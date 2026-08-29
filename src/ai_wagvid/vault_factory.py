"""Canonical construction path for vault analysis bundles."""

from __future__ import annotations

from datetime import datetime

from .vault import (
    VaultAnalysisBundle,
    VaultGeometryCapability,
    VaultIdentityCandidates,
    VaultObservation,
    VaultPhaseInterval,
    validate_required_phase_order,
)


def build_vault_analysis_bundle(
    *,
    analysis_id: str,
    routine_id: str,
    source_media_sha256: str,
    phases: tuple[VaultPhaseInterval, ...],
    observations: tuple[VaultObservation, ...],
    identity: VaultIdentityCandidates,
    corridor_boundary_capability: VaultGeometryCapability,
    model_bundle_digest: str,
    perception_bundle_digest: str,
    created_at: datetime,
    limitations: tuple[str, ...] = (),
) -> VaultAnalysisBundle:
    """Build a VT bundle only after canonical semantic phase-order validation."""
    validate_required_phase_order(phases)
    return VaultAnalysisBundle(
        analysis_id=analysis_id,
        routine_id=routine_id,
        source_media_sha256=source_media_sha256,
        phases=phases,
        observations=observations,
        identity=identity,
        corridor_boundary_capability=corridor_boundary_capability,
        model_bundle_digest=model_bundle_digest,
        perception_bundle_digest=perception_bundle_digest,
        created_at=created_at,
        limitations=limitations,
    )
