# Apparatus promotion gates

VT, UB, BB and FX are not complete merely because an apparatus evidence contract exists.

Promotion requires all of the following to bind to the same apparatus and immutable artifact set:

1. **Model bundle** — adapter/version, checkpoint SHA-256, config SHA-256, label-map SHA-256, training dataset manifest SHA-256, training-rights reference, framework/version and model-bundle digest.
2. **Accepted facts** — human-reviewed element/connection facts bound to the exact model bundle, evidence bundle and review-decision digest. Unreviewed candidates do not enter deterministic scoring.
3. **Pinned rulepack / D-score policy** — apparatus-matching rulepack ID/digest and policy digest reviewed by a qualified rules reviewer. The deterministic #6 engine evaluates only accepted facts.
4. **Executed benchmark** — immutable benchmark manifest, validation dataset manifest, leakage-safe split manifest, rights reference and hardware/runtime manifest. `planned` is never equivalent to `executed`.
5. **Required slices pass** — every required apparatus/camera/FPS/visibility/challenge slice must pass its thresholds declared before execution. A required failed or unsupported slice blocks promotion for that scope.

`src/ai_wagvid/apparatus_promotion.py` enforces these boundaries. Model, accepted-fact, benchmark, rulepack and D-score-ledger digests must agree. Missing or mismatched artifacts fail closed.

## Apparatus benchmark slice floor

The concrete benchmark manifest must include at least these families.

### VT
Fixed side camera standard/high FPS, broadcast camera, motion blur, partial occlusion, rare identity confusion, calibrated corridor and corridor unavailable. Measure phase/event timing, top-1/top-k identity, OOD/unknown, landing timing and geometry-capability correctness.

### UB
Fixed/broadcast cameras, release/flight, bar change, motion blur, partial occlusion, continuity-borderline and bar-geometry unavailable. Measure release/regrasp timing, bar identity, contact state, top-k element recall, continuity agreement and OOD/unknown.

### BB
Fixed/high/broadcast cameras, dance-vs-acro confusion, series-borderline, partial occlusion, geometry calibrated/unavailable. Measure top-k element recall, series agreement, pause timing, fall/off-beam events, geometry-capability correctness, criterion-evidence agreement and OOD/unknown.

### FX
Fixed-corner/broadcast cameras, partial floor visibility, motion blur, dance/acro/turn confusion, connection-borderline, boundary calibrated/unavailable and audio timing. Measure routine timing, tumbling segmentation, top-k identity, connection agreement, boundary-capability correctness, landing timing and OOD/unknown.

## Threshold governance

Thresholds must be written into the concrete benchmark manifest before the run. They may not be changed after seeing results to manufacture a pass. Required failed/unsupported slices remain explicit release blockers or explicitly unsupported release scope.

## Model cards

Every promoted apparatus model card must include:

- exact model bundle digest and all artifact hashes;
- source/training dataset and rights references;
- intended post-routine use only;
- supported apparatus/camera/FPS/visibility slices;
- unsupported/OOD behavior;
- benchmark manifest/report digests;
- known confusion families and failure gallery references;
- hardware/runtime manifest;
- rulepack/policy digest used for integration validation;
- no claim of live or official judging.

## Current status

The promotion gate itself can be tested with synthetic policies/results. Such tests validate integration logic only; they do **not** validate gymnastics model quality. Real apparatus promotion remains blocked until rights-cleared, reproducible model benchmark runs and qualified rulepack validation have been performed.
