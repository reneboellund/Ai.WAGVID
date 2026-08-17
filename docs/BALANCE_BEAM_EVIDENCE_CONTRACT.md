# Balance-beam evidence contract

## Purpose

`src/ai_wagvid/balance_beam.py` defines the BB-specific evidence layer for issue #9. It separates
measurable/observable video facts from deterministic D-score logic and from qualitative human
artistry decisions.

## Geometry

Beam geometry is an explicit capability with `available`/`unavailable` state, immutable geometry
digest and reason. Geometry-dependent observations such as alignment, foot/hand relationship and
off-beam evidence require a geometry digest. If the bundle geometry is unavailable, geometry-bound
observations are rejected. If geometry is available, observation digests must match the bundle's
geometry version.

## Observations

Observation kinds cover alignment, balance corrections, pauses/hesitations, foot/hand relationship,
fall/off-beam/remount, mount/dismount and criterion-specific artistry evidence. Every observation
references exact time, confidence and immutable evidence.

## Element and series references

BB element refs point to immutable temporal-candidate digests. Exact element identity is exposed only
when explicitly accepted. Series candidates contain at least two distinct segments, per-gap timing,
continuity evidence observation IDs, confidence and one of `continuous`, `interrupted` or
`unresolved`.

This layer does not award connection value. Accepted series/element facts later feed #6 under the
active pinned rulepack.

## Artistry

The machine may emit only `artistry-criterion-evidence`, tied to a named `criterion_id`. A human
criterion decision requires:

- the same criterion ID;
- one or more immutable artistry-observation digests;
- reviewer identity and qualification reference;
- accept/reject state;
- reason code and notes;
- timestamp and decision digest.

There is no aggregate `artistry_score` field in the domain or public schema. Qualitative judging
therefore remains criterion-specific, evidence-linked and attributable.

## Public export

`src/ai_wagvid/balance_beam_exports.py` emits `ai.wagvid.balance-beam-analysis.v1`, validated by
`schemas/balance-beam-analysis-v1.schema.json`. The public schema is locked to `apparatus: BB` and
rejects artistry-score, D/E/final-score and official-result fields.

## Remaining issue #9 work

Issue #9 remains open for real model/runtime and validation work:

- mount/dismount and acro/dance/turn candidate inference;
- persisted beam-axis/end/plane calibration binding;
- pause/hesitation and balance-correction calibration against qualified annotations;
- series/connection borderline validation;
- landing/alignment/off-beam measurement validation across camera angles;
- full-routine occlusion/failure benchmark slices;
- rulepack/#6 series/composition integration after accepted facts;
- criterion-specific artistry evidence validation with qualified reviewers;
- evidence overlays/failure gallery and #15 promotion evidence.

No aggregate artistry or model-quality result is claimed by this contract batch.
