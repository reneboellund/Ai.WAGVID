# Apparatus benchmark preflight

A real VT/UB/BB/FX benchmark may start only after all required inputs are frozen.

## Model
- exact adapter ID/version recorded
- checkpoint downloaded/acquired and SHA-256 verified
- config SHA-256 verified
- label-map SHA-256 verified
- training dataset manifest SHA-256 recorded
- framework/runtime version pinned
- training/data rights reference recorded
- model card started

## Validation dataset
- rights-cleared validation manifest frozen
- media/annotation hashes frozen
- stable athlete/event/routine grouping IDs available
- athlete/competition/alternate-view leakage-safe split frozen
- no official result/score is exposed to model inference before immutable AI output freeze
- required camera/FPS/visibility/challenge slices have non-zero samples or are declared unsupported before the run

## Rulepack
- apparatus-specific rulepack ID and digest pinned
- D-score policy digest pinned
- policy references the active governed rule registry
- qualified rules reviewer and qualification reference recorded
- no model-produced difficulty value bypasses deterministic rulepack lookup

## Thresholds
- every promotion metric and direction is declared before execution
- threshold values are committed/versioned before execution
- required slice IDs are committed/versioned before execution
- OOD threshold/top-k parameter are fixed before execution
- no post-hoc threshold adjustment is allowed in the same benchmark report

## Runtime
- hardware/runtime manifest frozen
- model/container/software digests recorded
- deterministic seed/config where applicable
- source media remains rights/policy compliant for the selected worker
- no live/official judging workflow is enabled

## Execution/report
- benchmark state changes from `planned` to `executed` only after the run actually completes
- failed and unsupported required slices remain visible
- sample counts are reported with metrics
- false-positive/false-negative/timing/OOD failure references are retained for failure gallery
- report binds exact model bundle and rulepack digests
- promotion evaluation runs only after deterministic #6 ledger integration has been validated against accepted facts

Synthetic unit fixtures can validate evaluator/integration logic but do not satisfy this preflight as real model-quality evidence.
