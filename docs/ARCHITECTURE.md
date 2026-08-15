# System Architecture

## 1. Objective

Ai.WAGVID shall convert recorded or live WAG video into an auditable sequence of observations and judging hypotheses, then apply a versioned rule engine to produce explainable D-score construction, execution/artistry deduction candidates, neutral deduction candidates, and final score proposals where the selected operating mode allows it.

The system is intentionally split between **perception** and **rules**. Machine-learning components may infer what happened in the video; deterministic rule components decide how a validated observation maps to the selected FIG rule pack.

## 2. Logical components

### 2.1 Media Gateway
Responsibilities:
- file upload, RTSP/SRT/WebRTC/live capture adapters;
- FFmpeg normalization;
- frame timestamps and source clock preservation;
- proxy generation;
- multi-camera synchronisation;
- dropped-frame detection;
- camera metadata and calibration records;
- cryptographic content hash of originals.

### 2.2 Competition Context Service
Stores athlete, event, subdivision, apparatus, start order, age/category, competition rules profile, official result identifiers and timing metadata. It must not infer identity from biometrics unless explicitly enabled under a separate lawful policy.

### 2.3 Vision & Motion Layer
Replaceable model interfaces for:
- person detection/tracking;
- gymnast isolation;
- 2D pose;
- 3D pose / multi-view reconstruction where available;
- apparatus geometry;
- floor/boundary geometry;
- contact detection;
- flight phase detection;
- rotation/twist estimation;
- body-angle estimation;
- landing displacement;
- temporal embeddings.

All model outputs include model ID/version, confidence, input range and quality diagnostics.

### 2.4 Routine Segmenter
Creates a canonical timeline of phases and element candidates. It may expose multiple hypotheses instead of prematurely choosing one.

### 2.5 Apparatus Interpreters
Dedicated VT/UB/BB/FX logic converts generic motion evidence into apparatus-specific concepts. See `APPARATUS.md`.

### 2.6 Element Recognition Service
Matches motion/phase evidence against the versioned element catalogue. Output is a ranked candidate set with distinguishing evidence and uncertainty.

### 2.7 Judging Evidence Service
Creates immutable evidence objects for every material decision:
- frame/time range;
- camera(s);
- overlay/pose snapshot references;
- measured quantities;
- candidate elements/deductions;
- rule reference;
- reviewer annotations.

### 2.8 Rule Engine
Deterministic engine with versioned rule packs. It handles element values, composition requirements, connection logic, counting rules, repeated-element treatment, D-score assembly, neutral penalties, and other rule-derived calculations that can be expressed deterministically.

### 2.9 Execution / Artistry Assist
Produces deduction **candidates** tied to evidence. It shall not collapse ambiguous visual observations into false precision. Each candidate includes category, severity options, evidence quality and confidence.

### 2.10 Score Composer
Combines accepted observations and rule-engine outputs according to the active judging profile. Human decisions and AI suggestions remain separately visible.

### 2.11 Human Review UI
Frame-accurate review with:
- timeline;
- candidate element chips;
- accept/reject/change controls;
- synchronized camera replay;
- pose/geometry overlays;
- rule citation panel;
- deduction ledger;
- D-score construction view;
- audit history;
- panel comparison.

### 2.12 Live Event Orchestrator
Controls low-latency sessions, camera health, routine state, operator workflow, result freeze, review and failover. See `LIVE_COMPETITION.md`.

### 2.13 Validation & Benchmark Service
Maintains labelled datasets, judge consensus targets, official-result comparisons, calibration tests, model metrics and regression gates.

### 2.14 Integration API
Stable REST/event contracts for KIGA and future scoring systems. KIGA consumes exported evidence/results; it must not call internal ML implementation details.

## 3. Deployment profiles

### Developer
Single Docker Compose stack, local video, local PostgreSQL/object storage, optional GPU.

### Club / Federation On-Prem
GPU inference node(s), local storage, browser clients, private LAN, no mandatory cloud dependency.

### Cloud Batch
Object storage + queue-based workers for historical video analysis.

### Competition Edge
Local redundant ingest and inference, strict clocking, UPS-aware deployment, local database/event bus, optional upstream replication. Competition operation must continue through internet loss.

## 4. Event-driven data flow

Suggested canonical events:
- `video.ingested`
- `camera.health.changed`
- `routine.started`
- `routine.ended`
- `segment.detected`
- `element.candidates.updated`
- `evidence.created`
- `deduction.candidate.created`
- `human.decision.recorded`
- `dscore.recomputed`
- `score.proposal.updated`
- `routine.frozen`
- `review.requested`
- `result.exported`

Events are append-only in competition mode.

## 5. Failure philosophy

The system shall fail **explicitly and safely**. Examples:
- insufficient frame rate => judging capability degraded and surfaced;
- camera loss => flag affected evidence, never synthesize missing frames;
- unknown element => preserve `UNKNOWN/CANDIDATE`, never force nearest class;
- rule-pack mismatch => block score publication;
- model unavailable => allow manual judging workflow where configured;
- multi-view desync => disable geometry requiring synchronized views;
- confidence below policy threshold => require review.

## 6. Explainability contract

For every accepted judging item the UI/API must answer:
1. What did the system observe?
2. Where in the video did it observe it?
3. Which model/algorithm produced the observation?
4. How confident was the observation?
5. Which rule maps that observation to the scoring consequence?
6. Was the decision AI-proposed, deterministic, or human-confirmed?
7. Has anyone overridden it, and why?

## 7. Security boundaries

- originals are immutable;
- derived clips reference source hashes;
- role separation: viewer, annotator, judge, superior judge/admin, system operator;
- signed/auditable configuration changes for competition mode;
- secrets outside repository;
- no public exposure of minors' footage by default;
- retention and deletion policies are configurable by event/data owner.

## 8. Architectural rule

No ML model is allowed to directly write a final score field. Models create observations/candidates; the score composer consumes accepted evidence through the rule engine and judging policy.
