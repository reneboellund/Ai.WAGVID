# Temporal recognition branch status

Branch: `agent/temporal-recognition-core`

Current head at time of this status note: `9a7e832fb32f1c24a523ed4c5528eec7173be28e`.

Delivered in this branch:

- uncertainty-first temporal candidate domain contract;
- exact canonical millisecond intervals with separate multi-camera evidence refs;
- deterministic top-k ordering and exact 1000-milli probability accounting;
- explicit `unknown_ood_milli` and `other_known_milli` mass;
- family-only resolution when exact identity is unresolved;
- automatic exact identity disabled by default;
- qualified human exact/family decisions with explicit out-of-top-k model override;
- ranked-element/family consistency validation for human decisions;
- strict public serializer/schema with no D/E/final/official-result fields;
- regression fixtures for probability, OOD/family behavior, multi-camera provenance, human override and schema boundaries;
- documented integration contract in `docs/TEMPORAL_RECOGNITION_CONTRACT.md`.

Issue #5 remains open. This branch does not supply trained production checkpoints, complete authoritative label maps, calibrated hierarchical family/phase/element inference, or the full apparatus/camera/OOD benchmark evidence needed for model promotion.
