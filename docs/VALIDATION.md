# Validation & Benchmark Strategy

## Annotation integrity

Annotation history uses `ai_wagvid.annotations.AnnotationRevision`. Each revision
contains immutable evidence, reviewer identity, timezone-aware creation time,
payload, state, comment and the previous revision digest. Validation rejects gaps,
identity changes and altered parents. Adjudication requires contributions from at
least two reviewers and an explicit rationale. Only accepted revisions may enter a
training-label export; reviewer identity is excluded while athlete/event/routine
grouping keys are retained for leakage-safe splitting.

UI/database persistence must store these revisions append-only. A correction adds
a revision; it never updates the meaning of an existing revision in place.

## Goal

Ai.WAGVID must be validated as a judging system, not merely as a computer-vision demo. Exact element recognition can still yield a wrong score if counting, connections or deductions are wrong; conversely a score can accidentally match while the underlying reasoning is wrong.

## Validation layers

### 1. Media integrity
Measure dropped frames, timestamp stability, camera sync, resolution, motion blur, occlusion and calibration quality.

### 2. Pose / geometry
Metrics by joint/phase/apparatus where ground truth is available. More important than one global pose metric is whether the measurement supports the judging distinction being attempted.

### 3. Segmentation
- routine start/end;
- element/phase boundaries;
- release/contact events;
- landing events;
- connection intervals.

### 4. Element recognition
- top-1/top-k accuracy;
- unknown detection;
- confusion by element family;
- difficulty-critical confusion rate;
- apparatus/category/camera stratification.

### 5. Rule engine
Must be deterministic and unit-tested independently of ML.

### 6. D-score
Track:
- exact D-score match;
- absolute error;
- element-ledger match;
- composition requirement match;
- connection match;
- reason for mismatch.

### 7. Execution/artistry deductions
Do not validate only against final E score. Compare criterion-level decisions against qualified judges and consensus references.

Metrics can include:
- detection precision/recall for observable error categories;
- severity agreement;
- weighted disagreement;
- judge-AI disagreement distribution;
- false-positive burden per routine.

### 8. Final judging workflow
Measure time-to-review, overrides, unresolved cases and operator/judge usability.

## Ground truth hierarchy

No single source is perfect. Store the reference type:

1. **Expert annotated element sequence** — preferred for recognition.
2. **Independent qualified-judge consensus** — preferred for judging criteria.
3. **Official D/E/result data** — useful comparison but not complete evidence of every underlying decision.
4. **Single judge annotation** — useful but labelled as such.
5. **Automatically inferred labels** — never treated as gold standard.

## Blind benchmark design

For serious evaluation:
- AI cannot read official scores before freeze;
- judges can be blinded to AI suggestions;
- same routine must not leak into train/test via alternate camera or re-encode;
- preferably hold out entire events and athletes;
- preserve difficult/rare skills in targeted challenge sets;
- report confidence intervals and sample counts.

## Benchmark suites

### B0 — Synthetic/unit fixtures
Rule-engine and geometry sanity tests.

### B1 — Curated skill clips
Clean single-skill recognition.

### B2 — Full routines
Real continuous routines for each apparatus.

### B3 — Adverse video
Occlusion, low light, compression, motion blur, unusual camera angles.

### B4 — Multi-camera competition
Synchronized competition footage.

### B5 — Shadow judging
Live-event prospective benchmark.

### B6 — Regression archive
Every confirmed production error becomes a permanent regression fixture where licensing permits.

## Apparatus stratification

Never publish only a combined WAG accuracy. Report VT/UB/BB/FX separately, and break down by relevant skill/error families.

## Promotion gates

### Offline research → training analysis
- stable ingest;
- evidence traceability;
- known failure modes surfaced;
- no silent rule errors.

### Training analysis → shadow judging
- end-to-end benchmarks;
- rulepack reviewed;
- camera-health policy;
- audit logs;
- prospective event test plan.

### Shadow → live assist
- predefined latency/reliability target met;
- qualified judge usability review;
- acceptable false-positive burden;
- failover rehearsed;
- strict score isolation.

### Live assist → any official scoring role
Requires governance outside normal software release: governing-body approval as applicable, documented validation, operational controls, event rules compatibility and accountable human authority.

## Bias and fairness checks

Judging must not use athlete identity, nationality, club, ranking, coach, historical scores or demographic proxies as performance features. Evaluate whether vision quality differs materially by lighting, leotard/background contrast, body morphology, camera angle or venue setup; mitigation belongs in capture/model design, not in score compensation.

## Reporting

Each released model should have a model card with:
- intended use;
- training data categories and licensing basis;
- benchmark datasets;
- per-apparatus metrics;
- known weak skill families;
- required camera conditions;
- out-of-scope cases;
- calibration/confidence behavior;
- version and hash.
