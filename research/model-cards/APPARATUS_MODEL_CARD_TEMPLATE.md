# Ai.WAGVID apparatus model card

## Identity
- Apparatus: `VT | UB | BB | FX`
- Model bundle ID:
- Model bundle digest:
- Adapter ID/version:
- Framework/version:
- Checkpoint SHA-256:
- Config SHA-256:
- Label-map SHA-256:

## Training provenance
- Training dataset manifest SHA-256:
- Dataset/source references:
- Training-rights reference:
- Athlete/event/alternate-view split policy:
- Known excluded datasets/assets:

## Intended use
Post-routine/post-event WAG evidence analysis only.

Not authorized for live judging, official scoring, real-time judge assistance or automatic competition decisions.

## Outputs
Document exact output contract and which fields remain candidate/unknown/unavailable. State explicitly that the model does not calculate D/E/final score.

## Supported scope
Record validated apparatus, camera conditions, FPS classes, resolution, visibility/occlusion conditions and runtime backends.

## Known limitations / OOD
List known confusion families, unavailable measurements, low-confidence behavior and explicit unknown/OOD handling.

## Rulepack integration validation
- Reviewed rulepack ID:
- Rulepack digest:
- D-score policy digest:
- Qualified rules reviewer:
- Review date:
- Accepted-fact integration fixture/report:

The model itself must not encode FIG difficulty values as hidden scoring output. Exact accepted identities are looked up through the pinned deterministic rulepack.

## Benchmark
- Benchmark manifest SHA-256:
- Validation dataset manifest SHA-256:
- Leakage-safe split manifest SHA-256:
- Validation rights reference:
- Hardware/runtime manifest SHA-256:
- Benchmark report digest:
- Threshold declaration commit/digest:

### Required slice results
List every required slice as PASS / FAIL / UNSUPPORTED. Do not omit failed slices from the card.

### Metrics
Include top-1/top-k, OOD/unknown, timing/state metrics and apparatus-specific required metrics. Report sample counts with each result.

## Failure gallery
Reference evidence IDs/intervals for representative false positives, false negatives, timing failures, identity confusions, OOD errors and geometry/camera failures.

## Promotion status
- Current promotion gate:
- Blockers:
- Approved scope only:
- Reviewer/sign-off:

A synthetic contract/unit test is not model-quality validation and must not be listed as a passed real-world benchmark.
