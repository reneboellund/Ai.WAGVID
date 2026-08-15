# Ai.WAGVID

**AI-assisted Women's Artistic Gymnastics post-event video analysis, score verification and performance development platform**

> Status: architecture/specification phase. Independent project designed for later optional integration with KIGA.

Ai.WAGVID analyses recorded WAG competition and training routines against versioned international FIG / World Gymnastics rules. The project is deliberately focused on **after-the-routine analysis**, not live judging.

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

Initial ruleset target: **World Gymnastics / FIG WAG 2025–2028 cycle, current 2026 publications**.

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

## Explicitly out of scope

- real-time live judging;
- replacing a competition judging panel;
- real-time score publication;
- competition control/failover infrastructure intended only for live judging.

The architecture should remain technically capable of processing video efficiently, but low-latency operation is not a product requirement.

## Apparatus scope

- **VT** — Vault
- **UB** — Uneven Bars
- **BB** — Balance Beam
- **FX** — Floor Exercise

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

## Repository layout

```text
docs/
  ARCHITECTURE.md
  JUDGING_MODEL.md
  RULE_ENGINE.md
  APPARATUS.md
  DATA_MODEL.md
  PERFORMANCE_ANALYSIS.md
  SCORE_VERIFICATION.md
  VALIDATION.md
  KIGA_INTEGRATION.md
  ROADMAP.md
rules/
schemas/
src/
models/
examples/
tests/
```

## Proposed technology direction

- Python analysis/inference services;
- OpenCV / FFmpeg media pipeline;
- PyTorch-compatible vision/temporal models;
- 2D + optional multi-view 3D pose abstraction;
- FastAPI-compatible service boundary;
- PostgreSQL for structured records/provenance;
- object storage for original/proxy/evidence clips;
- browser-based analysis/review UI;
- containerised CPU/GPU deployment.

Technology choices remain replaceable behind interfaces until benchmarks justify them.

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
