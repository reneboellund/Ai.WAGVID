# Ai.WAGVID

**Evidence-based WAG/MAG video analysis for score review, judging research and athlete development**

> Status: active internal research and development. The repository contains a runnable Django
> application foundation, versioned rule-source governance, resumable video ingest, analysis-job
> orchestration, competition records and a human evidence-review workflow. AI model adapters and
> full apparatus rule packs remain under development.

Ai.WAGVID is an independent research platform for analysing recorded Women's Artistic Gymnastics
(WAG) and Men's Artistic Gymnastics (MAG) competition, routine, drill and training footage. It links
machine observations to exact video evidence, ranked element candidates and versioned rule-pack
interpretations. Official results and AI proposals are stored separately so qualified reviewers can
approve, correct or challenge individual findings. The historical product name is retained;
discipline and apparatus are explicit data, rule-pack and benchmark dimensions.

Its two primary product goals are:

1. **Score verification** — reconstruct what happened in the routine, identify recognised elements, D-score composition, execution/artistry/neutral deduction candidates, and compare the evidence-linked reconstruction with an official score.
2. **Performance development** — explain what was technically strong or weak, where points were lost, which recurring patterns limit the gymnast, and what should be prioritised in training.

The system should answer much more than “what score should this have received?”. It should help answer:

- Which elements were performed and which were uncertain?
- Which elements counted toward D-score and why?
- Were composition requirements and connections fulfilled?
- What deductions were observed, in list form, with amount/category/rule/evidence?
- At what exact moment did each issue occur?
- Which errors are isolated and which repeat across the routine or across competitions?
- What was done especially well?
- Where are the gymnast's strongest technical areas?
- Where are the biggest point-loss opportunities?
- Which problems appear to be execution, technique, consistency, composition choice or presentation-related?
- What should coach/gymnast prioritise next?
- How does this routine compare with earlier routines from the same gymnast when integrated with KIGA?

## Core principle

The system must never output a naked score or unexplained coaching conclusion. Every material judgement must be traceable to source video/camera, exact timecode or frame interval, detected motion evidence, recognised/candidate element, apparatus, rule-pack version, rule reference, confidence/ambiguity, deterministic score calculation where applicable, and human review/override history.

## Official rule baseline

Initial ruleset target: **World Gymnastics/FIG WAG and MAG 2025–2028 cycles, using the applicable
current publications and revisions**.

FIG / World Gymnastics publications remain the source of truth. Ai.WAGVID stores machine-readable interpretations, references, effective dates and tests; it is not an independent rule authority.

## Product modes

1. **Single Routine Deep Analysis** — upload one routine and receive complete technical, judging and development analysis.
2. **Score Verification** — reconstruct D/E/neutral evidence and compare with the official result without assuming the official score is automatically correct.
3. **Deduction Breakdown** — produce a chronological and grouped list of observed deductions with category, suggested severity, rule reference, confidence and video evidence.
4. **Technical Performance Analysis** — identify strengths, weaknesses, recurring technical patterns, amplitude/body-shape/landing/connection issues and other apparatus-specific observations.
5. **Coach Development Report** — convert evidence into prioritised training observations and actionable focus areas while clearly separating observed facts from coaching hypotheses.
6. **Batch Competition Analysis** — analyse many recorded routines after an event and compare patterns across athletes/apparatus/results.
7. **Longitudinal Athlete Analysis** — compare repeated routines over time and expose persistent or improving patterns; especially valuable through later KIGA integration.
8. **KIGA Integration** — export validated structured observations without making KIGA depend on the Ai.WAGVID runtime.

## Scope and deployment progression

The first supported product class is offline analysis of uploaded competition and training video.
Later milestones add event shadow mode, judge-assist review and low-latency evidence retrieval only
after accuracy, security, reliability and sporting-governance gates have been met.

The project does not currently replace a judging panel, publish official scores or autonomously
control a competition. AI output remains advisory unless a future authorised workflow explicitly
defines otherwise.

## Apparatus scope

- **VT** — Vault
- **UB** — Uneven Bars
- **BB** — Balance Beam
- **FX** — Floor Exercise (WAG/MAG)
- **PH** — Pommel Horse
- **SR** — Still Rings
- **PB** — Parallel Bars
- **HB** — Horizontal Bar

WAG and MAG use separate element catalogues and rule-pack interpretations even where they share an
apparatus code. Athlete identity or appearance must never be used to infer discipline or score.

## High-level pipeline

```text
Recorded competition / training video
   ↓
Ingest + timestamps + optional camera calibration
   ↓
Athlete / apparatus / boundary tracking
   ↓
2D/3D pose + temporal motion representation
   ↓
Phase / skill segmentation
   ↓
Element candidate recognition
   ↓
Apparatus-specific interpretation
   ├── difficulty / element identity
   ├── composition / requirements
   ├── connections / series
   ├── execution evidence
   ├── artistry evidence (where applicable)
   └── neutral / procedural evidence
   ↓
Versioned FIG rule engine
   ↓
Evidence-linked score reconstruction
   ↓
Technical performance analysis
   ├── deduction list
   ├── strengths
   ├── weaknesses
   ├── recurring patterns
   ├── point-loss map
   └── prioritised development observations
   ↓
Human review / official-score comparison / KIGA export
```

## Required analysis output

Every analysed routine should eventually be able to produce a structured report containing:

### Routine summary
- apparatus;
- event/athlete/routine identifiers;
- rule-pack version;
- source video quality/limitations;
- official score if supplied;
- reconstructed score status and confidence.

### Element-by-element timeline
For every identified or candidate element:
- timestamp/frame interval;
- element name/code/family;
- difficulty value;
- recognised characteristics;
- confidence and alternatives;
- whether it counts in D-score;
- connection/series relationship;
- linked execution observations;
- video evidence.

### D-score reconstruction
- counted elements;
- non-counted/repeated elements with reasons;
- composition requirements;
- connection value/series handling;
- all intermediate arithmetic;
- reconstructed D-score;
- difference from official D-score where known.

### Deduction list
A routine must support a human-readable list/table similar to:

| Time | Element/phase | Observation | FIG category | Suggested deduction | Confidence | Evidence |
|---|---|---|---|---:|---|---|
| 00:14.32 | Example element | landing step | execution / landing | 0.xx | high | frame/clip |

The exact deduction values/categories must come from the active rule pack; examples in documentation must not be treated as hard-coded rules.

The same deductions should also be groupable by:
- element;
- phase;
- deduction family;
- severity;
- apparatus;
- repeated technical pattern.

### Strengths
Evidence-backed positives such as:
- consistently controlled landings;
- strong amplitude where measurable;
- stable body alignment;
- clean connection timing;
- reliable handstand/turn/flight positions where applicable;
- secure beam work;
- efficient vault phases;
- technically consistent repeated skill family.

A “strength” must be derived from observed evidence, not reputation, ranking or athlete identity.

### Weaknesses / point-loss map
Rank issues by dimensions such as:
- estimated points lost;
- frequency;
- recurrence across routines;
- confidence;
- technical importance;
- whether the issue affects D-score, E-score, artistry or neutral deductions.

### Development recommendations
Recommendations must distinguish:
- **Observed fact** — directly supported by video/rules.
- **Pattern** — repeated supported observation.
- **Coaching hypothesis** — plausible explanation requiring coach confirmation.
- **Suggested training focus** — action area, not a claim about cause.

The system must not invent diagnoses, injuries, motivation, fatigue, fear, physical limitations or training-history explanations from video alone.

## Design requirements

- frame-accurate evidence and synchronized replay;
- multi-camera capable but fully useful with one suitable video;
- versioned rules and skill database;
- human-in-the-loop review;
- confidence-aware ambiguity handling;
- no silent rule fallback;
- reproducible calculations;
- clear separation between observation, judging interpretation and coaching interpretation;
- offline/on-premise deployment option;
- privacy-aware handling of minors and competition footage;
- API-first integration;
- independent from KIGA with a stable integration contract.

## Repository guide

```text
docs/                 architecture, judging, operations, research and integration decisions
research/             machine-readable research/model candidate registry
rules/                versioned rule-source registry and future rule packs
schemas/              public and internal JSON Schema contracts
src/ai_wagvid/        model-neutral capture, perception, action and interpretation contracts
src/wagvid_app/       Django domain, operational UI, upload and review workflows
src/wagvid_rules/     rule-registry validation library and CLI
templates/            responsive operational web interface
tests/                contract, schema, service, permission and workflow tests
```

## Proposed technology direction

- modular Django application for auth, permissions, models, admin, process views and APIs;
- Django templates + HTMX PWA for the operational browser UI;
- native Kotlin Android thin client using CameraX, Room and WorkManager;
- PostgreSQL for structured records/provenance and organization-scoped access;
- S3-compatible object storage for original/proxy/evidence media;
- durable background workers for FFmpeg, analysis, export and maintenance;
- ASGI WebSockets for authenticated device control; SSE/polling for dashboard progress;
- OpenCV/FFmpeg media processing and replaceable PyTorch-compatible vision/temporal adapters;
- containerised on-prem CPU/GPU deployment.

See `docs/ADR-0001-APPLICATION-SHELL.md`. Keep analysis/model implementations replaceable behind
interfaces; begin as a modular monolith and split services only when measured operational needs
justify the extra complexity.

Named technologies and datasets in the architecture documents are candidates behind common
contracts. Listing MediaPipe, YOLO-Pose, MMPose, MMAction2, FineGym, Gym288, OSL, GymPose or
CaFlow-style AQA does not mean every adapter or artifact is installed or validated. Promotion
requires provenance, rights, benchmark and operational review recorded in the research registry.

## Project phases

- **M0 — Specification & FIG rule provenance**
- **M1 — Video ingest, annotation and evidence system**
- **M2 — Pose / phase / element recognition research baseline**
- **M3 — Apparatus-specific element and D-score analysis**
- **M4 — Execution / artistry / neutral deduction evidence**
- **M5 — End-to-end score verification**
- **M6 — Technical performance, strengths/weaknesses and development analysis**
- **M7 — Batch competition and longitudinal comparison**
- **M8 — KIGA integration**
- **M9 — Validation, calibration and analysis-quality governance**

## Legal / sporting disclaimer

Ai.WAGVID is an independent analysis project and is not affiliated with or endorsed by FIG / World Gymnastics. It is intended to assist post-event review, technical analysis, coaching and score verification. Official competition results remain governed by the responsible federation/event processes. FIG rules, element tables and publications remain subject to their respective rights and official publication terms.


## Current implementation

Implemented foundations include:

- authoritative source metadata in `rules/registry.yaml`;
- JSON Schema validation through `schemas/rule-registry-v1.schema.json`;
- cross-record integrity checks and CLI in `src/wagvid_rules/`;
- governance for revisions, review, hashes and historical reproducibility;
- Django authentication, organisations, roles, gymnasts, WAG/MAG routines and competition events;
- device-authenticated resumable uploads with size and SHA-256 verification;
- durable analysis-job leasing and runtime readiness checks;
- official-versus-AI score records, evidence-linked deductions and reviewer decisions;
- CSV gymnast import/export and append-only audit history;
- model-neutral pose, temporal-action, interpretation and advisory AQA contracts.

The registry stores links and metadata; it does not redistribute the source PDFs.

## Local validation

```powershell
py -m pip install -e ".[dev]"
wagvid-rules validate rules/registry.yaml
py -m pytest -q
```

The continuous test suite currently covers rule governance, schemas, capture/upload behaviour,
runtime services, WAG/MAG data, web permissions and human review. See the latest pull request or CI
run for the authoritative test count rather than relying on a hard-coded number in this README.
