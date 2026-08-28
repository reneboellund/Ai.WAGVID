# Performance development and longitudinal analysis

Issues: #19 and #12

This branch implements the deterministic aggregation layer that turns **reviewed, evidence-backed observations** into strengths, point-loss groups, recurring technical patterns, transparent coach priorities and cautious longitudinal trends.

It does not diagnose causes from video and does not create a hidden all-purpose athlete quality score.

## Semantic layers

The public report keeps these layers structurally separate:

1. `observed-fact` — accepted evidence-backed observation from a routine.
2. `pattern` — recurrence of compatible accepted observations across one or more routines.
3. `coaching-hypothesis` — plausible explanation requiring coach review; never rewritten as an observed fact even after coach confirmation.
4. `suggested-training-focus` — possible practical focus; coach selection/rejection remains explicit.

Judging interpretation and score effects are expected to arrive from the score/deduction ledgers at integration. This performance layer does not recalculate them.

## Accepted observations only

`PerformanceObservation` requires:

- stable pseudonymous athlete group ID;
- stable routine/event grouping IDs;
- apparatus/category/pattern key;
- immutable evidence IDs + SHA-256 digests;
- source analysis digest;
- confidence in integer milli-units;
- explicit review state;
- point-loss units only for point-loss observations.

Patterns and reports reject proposed/rejected observations. A model proposal therefore cannot silently become a coach-development conclusion.

A routine snapshot also requires at least one accepted observation. An empty analysis is not interpreted as a perfect routine because `no accepted observations` and `no observable problems` are not equivalent facts.

## Pattern grouping

Pattern aggregation is deterministic and uses an upstream apparatus/rule-aware `pattern_key`. The core does not invent semantic similarity between unrelated categories.

A pattern records:

- occurrence count;
- distinct routine count;
- evidence count;
- point-loss sum where applicable;
- conservative confidence floor;
- exact observation and routine IDs.

Strength and point-loss observations never collapse into the same pattern merely because they share a category/key.

## Priority matrix

Point-loss priorities require a separate `CoachPriorityInput` for every pattern. The coach supplies:

- technical importance;
- actionability/trainability;
- rationale;
- coach identity.

Observation/model confidence is a different dimension and cannot populate actionability automatically.

`PriorityPolicy` uses an explicit lexicographic dimension order rather than a hidden weighted AI score. The serialized priority shows every dimension used, allowing a user to understand why Priority 1 ranked above Priority 2.

## Longitudinal snapshots

`RoutinePerformanceSnapshot` binds one immutable analysis revision for one athlete/routine/apparatus to:

- event and occurrence time;
- analysis revision ID + SHA-256;
- rulepack ID + SHA-256;
- model bundle SHA-256;
- composition signature;
- accepted observations.

Multiple re-analysis revisions may coexist in storage. A single trend series refuses to include two revisions of the same routine: the caller must explicitly select which immutable revision is being compared.

This prevents a future model from silently replacing the historical basis of a trend.

## Trend behavior

Each known category/polarity contributes one metric point for **every selected routine**. If a previously observed point-loss category disappears later, that later routine contributes zero rather than disappearing from the series.

- point-loss trends use accepted point-loss units;
- strength/neutral trends use occurrence counts unless a future reviewed metric contract supplies a domain-specific value;
- no generic aesthetic/quality score is invented.

The default trend comparison uses medians of earlier vs later halves and a configurable material-change threshold. This is descriptive, not causal inference.

Directions:

- `improving`
- `stable`
- `worsening`
- `insufficient-data`
- `not-comparable`

## Comparability/caveats

A rulepack digest change makes a numeric direction `not-comparable`; different scoring semantics are never merged into one trend.

Model bundle and composition changes are surfaced explicitly as caveats (`model-bundle-changed`, `composition-changed`). A direction may still be shown under the same rulepack, but UI/report consumers must show those caveats next to it.

Cross-athlete and cross-apparatus series are rejected. This core does not rank athletes or normalize athletes against one another.

## Public schemas

- `schemas/performance-report-v1.schema.json`
- `schemas/longitudinal-report-v1.schema.json`

Schema tests validate the actual normalized JSON produced by the code.

## Safety boundary for coaching text

The software may say that a recurring pattern was observed and suggest that a coach review an area. It must not infer from video alone:

- injury or pain;
- fatigue cause;
- fear/anxiety;
- motivation;
- training volume adequacy;
- strength/flexibility diagnosis;
- coach quality.

A coaching hypothesis remains labelled as a hypothesis even after human confirmation; its semantic provenance is preserved.

## Remaining integration work

Before #19/#12 can close:

- connect accepted #11 deduction observations and other apparatus observations to `PerformanceObservation` with canonical evidence digests;
- integrate D/composition facts so composition signatures are generated deterministically rather than supplied by fixture/caller code;
- define apparatus-aware pattern-key ontology and qualified coach review fixtures;
- persist coach priority inputs/hypothesis/focus revisions in the operational product shell;
- render strengths, point-loss, pattern, priority and trend panels in the canonical UI;
- implement event/batch job orchestration for complete competitions;
- select analysis revision explicitly for re-analysis comparisons in UI/API;
- validate trend usefulness and wording with qualified WAG coaches;
- coordinate stable KIGA export fields under #14.

No PR, merge, GitHub Actions run or medical/causal diagnosis capability is created by this branch.
