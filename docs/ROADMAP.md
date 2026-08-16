# Ai.WAGVID WAG/MAG Roadmap

This roadmap intentionally builds evidence infrastructure and rule correctness before attempting autonomous live scoring.

# M0 — Specification & FIG rule provenance

**Outcome:** repository contains a reviewed architecture and a machine-rule ingestion plan.

Deliverables:
- authoritative source registry;
- rule-pack schema;
- element catalogue schema;
- deduction schema;
- provenance/effective-date model;
- rule-test framework;
- apparatus capability matrix;
- data/privacy policy draft;
- annotation guidelines;
- initial API/schema contracts.

Exit gate: a qualified reviewer can trace every implemented rule to the intended official source/revision.

# M1 — Video ingest, calibration & annotation

Deliverables:
- video/file ingest;
- FFmpeg normalization;
- frame/time canonicalisation;
- source hashes;
- camera metadata;
- single-camera apparatus calibration;
- multi-camera sync model;
- browser frame-accurate annotation UI;
- annotations for segments, contacts, key phases, elements and deductions;
- dataset versioning/export;
- quality diagnostics.

Exit gate: labelled routines can be reproduced exactly from immutable source media.

# M2 — Pose, tracking, phase & element research baseline

Deliverables:
- gymnast detector/tracker;
- pose abstraction;
- apparatus geometry;
- contact/flight detector;
- temporal segmenter;
- hierarchical element classifier;
- unknown/OOD detection;
- model-run provenance;
- baseline datasets and model cards;
- per-apparatus benchmark report.

Exit gate: system produces evidence-linked element candidates, not just labels.

# M3 — Apparatus-specific D-score engine

Parallel workstreams:

## VT
- vault phase segmentation;
- family/identity candidates;
- rulepack mapping;
- D construction.

## UB
- contact topology;
- release/regrasp/bar-change recognition;
- element chain;
- connection logic;
- D construction.

## BB
- acro/dance/turn recognition;
- series continuity;
- composition evaluation;
- D construction.

## FX
- tumbling/dance/turn recognition;
- connection logic;
- composition evaluation;
- D construction.

Cross-cutting:
- repetition/counting rules;
- ambiguity alternatives;
- ledger visualization;
- known-routine fixtures.

Exit gate: reviewed element sequence yields deterministic, tested D construction for active rule pack.

# M4 — Execution, artistry & neutral assistance

Deliverables:
- deduction ontology tied to rule pack;
- measurable geometry/landing/body-shape detectors;
- severity-candidate logic;
- BB/FX criterion-specific artistry evidence UI;
- boundary/time/procedural candidate framework;
- deduction review ledger;
- judge agreement benchmark tools.

Exit gate: no deduction is presented without replayable evidence and legal rule mapping.

# M5 — Offline end-to-end analyser

Deliverables:
- upload routine;
- select/resolve apparatus and rule profile;
- automatic analysis job;
- analysis timeline;
- D ledger;
- E/artistry/neutral candidate panels;
- score proposal where complete;
- human edit/review;
- export report/JSON;
- reproducible re-analysis;
- batch jobs.

Exit gate: usable by coaches/analysts on recorded routines with clear uncertainty.

# M6 — Shadow judging

Deliverables:
- event/start-list import;
- live camera capture;
- routine arming/start/end workflow;
- AI hidden from official panel during benchmark;
- official result import after freeze;
- comparison dashboard;
- prospective benchmark protocol;
- camera/inference health telemetry.

Exit gate: complete event can be shadow-judged without disrupting official operation.

# M7 — Live judge assist

Deliverables:
- low-latency event pipeline;
- D-panel assistance view;
- execution review timeline;
- rapid replay/multi-view;
- superior/review station;
- reliability/failover controls;
- configuration freeze;
- audit log;
- scoring-system adapter sandbox.

Exit gate: predefined latency, reliability and judge usability targets met in controlled events.

# M8 — KIGA integration

Deliverables:
- `ai.wagvid.analysis.v1` schema;
- KIGA athlete/event mapping;
- analysis import/export;
- evidence deep links;
- historical trend fields;
- official-vs-AI comparison data;
- privacy-safe data transfer.

Exit gate: KIGA can consume validated results without accessing Ai.WAGVID internals.

# M9 — Competition-grade governance

Deliverables:
- formal validation package;
- model/rule release signing;
- operating procedures;
- user roles/permissions;
- audit export;
- incident handling;
- calibration procedure;
- hardware/camera minimums;
- failover rehearsal;
- external rules/legal review;
- governing-body/federation approval path where required.

This milestone is organisational/sporting as well as technical. Software completion alone does not authorise official judging use.

# Research backlog

- monocular vs multi-view 3D comparison;
- markerless rotation/twist estimation;
- contact inference using video + optional audio;
- high-frame-rate vs standard broadcast video performance;
- domain adaptation across venues;
- self-supervised gymnastics motion embeddings;
- rare-element few-shot recognition;
- uncertainty calibration;
- judge-consensus modelling without learning identity bias;
- active learning from human review;
- optional on-device/edge inference.
- FineGym, Gym288-Skeleton and OSL temporal-localization adapters with canonical label mapping;
- CaFlow-style AQA challenger retained as a separate, calibrated advisory channel;
- WAG/MAG apparatus-specific metric packs: BB wobble/turn/landing, UB handstand/swing/cast,
  FX pass/jump/landing/body-line, VT board/block/flight/landing, and MAG PH/SR/PB/HB equivalents;
- annotated-video renderer, canonical JSON/CSV exporters, REST endpoints and offline CLI;
- explicit coaching versus judge/research runtime profiles and multi-model fusion benchmarks.

# MAG expansion gate

MAG reuses the media, pose, evidence, review and rule-pack infrastructure but has its own apparatus,
element taxonomies and deduction semantics. PH, SR, PB and HB must receive independent rule sources,
fixtures and qualified review. Shared apparatus codes FX and VT remain discipline-qualified; a model
or rule pack may never infer the discipline from athlete identity or appearance.

# Suggested first vertical slice

Build **one complete offline apparatus path before all-apparatus breadth**:

`Video ingest → calibration → segmentation → element candidates → evidence UI → rulepack → D ledger → human correction → export`

Recommended first candidates: VT for simpler phase topology, or UB if the priority is maximum architectural stress-testing. The decision should be benchmark-driven rather than assumed.
