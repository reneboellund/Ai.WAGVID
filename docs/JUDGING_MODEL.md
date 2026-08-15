# Judging Model

## Purpose

Define how Ai.WAGVID represents WAG judging without conflating computer-vision confidence, human judgement and deterministic rules.

## Decision layers

### A. Observation
Raw or derived visual fact, e.g. body angle, contact event, foot position, boundary crossing candidate, landing displacement, support phase, flight time, rotation amount.

### B. Interpretation
Gymnastics meaning inferred from one or more observations, e.g. element candidate, connection candidate, landing error candidate, pause candidate.

### C. Rule application
Deterministic mapping from accepted interpretation(s) to the active ruleset.

### D. Panel decision
Human acceptance, correction, rejection or override.

These layers are stored separately.

## Score channels

Ai.WAGVID shall model at least:

- **D channel** — difficulty-related element recognition, composition requirements and connection/series logic.
- **E channel** — execution deduction candidates supported by observable evidence.
- **Artistry/composition quality channel** — where the Code requires qualitative assessments, represented as evidence-linked criteria rather than opaque single-model output.
- **Neutral/procedural channel** — timing, boundary or other penalties where visually/systemically observable and supported by the rule pack.
- **Final composition channel** — deterministic combination of the accepted panel/result inputs for the active competition profile.

## Confidence is not score probability

Model confidence expresses confidence in a machine observation/classification. It does not mean probability that a judge would award a specific score.

Required confidence data:
- `model_confidence`
- `evidence_quality`
- `rule_applicability` (`exact`, `conditional`, `ambiguous`)
- `human_review_state`

## Candidate-first recognition

An element recognizer returns top candidates rather than silently forcing one:

```json
{
  "segment_id": "seg_0042",
  "candidates": [
    {"element_id": "rulepack-element-id-a", "confidence": 0.81},
    {"element_id": "rulepack-element-id-b", "confidence": 0.16}
  ],
  "unknown_probability": 0.03,
  "review_required": true
}
```

## D-score construction record

Every constructed D result must expose its ledger:
- recognised/accepted elements in routine order;
- element identity and value from ruleset;
- whether counted/non-counted and why;
- repetition handling;
- composition requirements and fulfilment evidence;
- connections/series and evidence;
- any ruleset-specific bonuses/adjustments;
- unresolved ambiguity;
- total with exact intermediate arithmetic.

## Execution candidate record

Each candidate must contain:
- deduction family / criterion;
- affected element/phase or whole-routine scope;
- start/end time and frames;
- measured evidence where possible;
- severity candidates permitted by the rule pack;
- recommended severity, if enabled;
- confidence;
- camera suitability;
- human decision.

## Human panel modes

### AI hidden
Used for unbiased benchmark collection. Human judges score without seeing AI output.

### AI advisory
Judge sees AI suggestions and evidence but owns decisions.

### AI confirmation workflow
High-confidence machine detections can be rapidly confirmed; policy determines which categories are eligible.

### Superior review
Disagreements or policy-triggered items are escalated with synchronized replay and complete provenance.

## Judge disagreement analytics

For validation the system stores individual judge decisions where lawfully available and computes:
- AI vs each judge;
- AI vs panel median/mean as appropriate;
- inter-judge dispersion;
- element recognition agreement;
- deduction category/severity agreement;
- D-score exact-match rate;
- error by apparatus/skill family/camera condition.

## Prohibited shortcuts

- infer an element solely from official score/result metadata;
- use athlete identity as a scoring feature;
- use club/nation/ranking as a scoring feature;
- hide low confidence behind a rounded score;
- train/evaluate on the same routine split across datasets;
- allow official panel values to leak into live AI inference except in an explicit comparison channel after freeze.

## Output states

Every analysis ends in one of:
- `DRAFT_AI`
- `NEEDS_REVIEW`
- `HUMAN_CONFIRMED`
- `PANEL_CONFIRMED`
- `FROZEN`
- `INVALID_INPUT`
- `INCOMPLETE_EVIDENCE`

Competition publication policy may accept only selected states.
