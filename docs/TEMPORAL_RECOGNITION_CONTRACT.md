# Temporal recognition contract

## Purpose

This contract is the pre-scoring boundary for issue #5. Temporal/action-model adapters may propose
where a skill occurs and which WAG element identities are plausible, but they do not calculate a D,
E, neutral or final score and they do not consume official-result context.

The implementation is in `src/ai_wagvid/temporal_recognition.py`; the public projection is
`src/ai_wagvid/temporal_exports.py`; the public schema is
`schemas/temporal-recognition-v1.schema.json`.

## Candidate identity and evidence

Each `TemporalElementCandidate` binds:

- one routine and apparatus;
- a canonical exact millisecond interval;
- one or more media/camera interval references that cover that interval;
- immutable evidence digests for every view;
- distinguishing observations with their own evidence digest and confidence;
- model bundle, model configuration and perception bundle digests;
- optional sequence-context digest;
- explicit limitations.

Multiple camera views remain separate references. Combining them does not erase camera/media
provenance.

## Probability accounting

A candidate uses integer milli-probabilities. Probability mass must total exactly `1000` across:

- ranked top-k known element alternatives;
- `unknown_ood_milli`;
- `other_known_milli` for known-class mass omitted from the truncated ranked list.

This prevents a short top-k list from appearing more certain merely because unreported probability
mass disappeared.

## Resolution policy

The default resolution policy is uncertainty-first:

- sufficiently high unknown/OOD mass resolves to `unknown`;
- evidence may support a `family-only` result while exact identity remains unresolved;
- exact automatic acceptance is disabled by default;
- exact automatic acceptance is possible only through an explicit policy with declared top-1 and
  margin thresholds.

Downstream deterministic scoring must not convert `unknown`, `family-only` or `needs-review` into a
fabricated exact element identity.

## Human decisions

Human element decisions require reviewer identity, qualification reference, reason, notes and exact
candidate digest.

If the chosen exact element is already present in the model top-k, the chosen family must match the
family attached to that ranked candidate. A conflicting element/family pair is rejected as internally
inconsistent.

A qualified reviewer may choose an exact element outside the top-k. That remains valid but is
recorded as `model_candidate_override=true`; it is not rewritten as though the model predicted the
human answer.

A family-only human decision is valid when exact identity cannot be resolved from available
evidence.

## Public export boundary

`ai.wagvid.temporal-recognition.v1` exports source intervals, evidence-backed observations, ranked
alternatives, explicit unknown/OOD mass and model/perception provenance. The schema uses
`additionalProperties: false`; D/E/final-score fields, official results and generic hidden
`confidence` fields are therefore invalid in this contract.

The public serializer output is regression-tested against the schema.

## Remaining issue #5 work

This contract does not claim that the temporal recognition model itself is production-ready. Issue
#5 remains open for:

- authoritative/complete reviewed source-label to WAG mapping;
- trained and checksummed temporal checkpoints;
- hierarchical family/phase/element model implementation and calibration;
- routine start/end and apparatus-phase validation where not already provided by upstream activity
  segmentation;
- full-routine segmentation metrics;
- top-1/top-k, OOD/unknown, confusion and difficulty-critical confusion benchmarks;
- alternate-camera leakage tests and real multi-camera evaluation;
- promotion through the release-validation gates in #15.

No official score/result data may be introduced as an inference feature while completing those
items.
