# Vault analysis contract

## Purpose

`src/ai_wagvid/vault.py` defines the VT-specific evidence layer for issue #7. It remains pre-scoring:
no D/E/final score is calculated here and no FIG difficulty value is hard-coded. Accepted exact
identity may later feed the pinned deterministic rulepack/ledger in #6.

## Canonical phase timeline

The v1 phase vocabulary is:

`approach → hurdle → springboard-contact → pre-flight → table-support → repulsion → post-flight → landing → stabilization`

Each available phase is an exact millisecond interval with confidence and one or more immutable
evidence references that cover that interval. Partial timelines are allowed when source evidence does
not support every phase. The canonical builder validates both chronological timestamps and semantic
phase order; it does not invent omitted phases.

## Observations

Evidence-backed observation kinds cover board/table contact, repulsion, rotation, twist, body shape,
landing contact/displacement, fall/extra support and corridor/boundary candidates. Values remain
observable/candidate facts rather than deductions or final judging decisions.

Every observation keeps confidence, evidence references, optional calibration digest and explicit
limitations.

## Identity candidates

Vault identity remains uncertainty-first. Ranked element IDs/families plus `unknown_ood_milli` and
`other_known_milli` must sum to exactly 1000. Identity alternatives cite observation IDs; the bundle
rejects references to observations that do not exist.

No identity candidate carries a D value. Rulepack lookup belongs to #6 after review/acceptance.

## Calibration gate

Corridor/boundary capability is explicit:

- `available` requires a calibration digest;
- `unavailable` carries a reason;
- a corridor/boundary observation itself requires calibration;
- a bundle whose corridor/boundary capability is unavailable cannot contain a boundary observation.

Therefore missing geometry cannot be interpreted as evidence that no boundary/corridor issue
occurred.

## Public contract

`src/ai_wagvid/vault_exports.py` projects `ai.wagvid.vault-analysis.v1`, validated by
`schemas/vault-analysis-v1.schema.json`. The public schema is locked to `apparatus: VT` and rejects
D/E/final-score and official-result fields through `additionalProperties: false`.

## Remaining issue #7 work

Issue #7 remains open for real apparatus-specific inference and validation:

- trained/pinned board/table/landing event detection;
- vault family/entry/rotation/twist/body-shape candidate models;
- human review wiring to accepted exact identity;
- active rulepack lookup and #6 ledger integration;
- calibrated landing displacement/corridor measurement validation;
- multiple camera-angle and FPS benchmark slices;
- common/rare identity-confusion evaluation;
- evidence overlays/failure gallery and promotion through #15.

This contract batch claims no model-quality or hardware benchmark result.
