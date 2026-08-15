# Ai.WAGVID

**AI-assisted Women's Artistic Gymnastics video analysis and judging platform**

> Status: architecture/specification phase. Independent project designed for later optional integration with KIGA.

Ai.WAGVID is a research and production platform for analysing WAG routines from recorded or live video against versioned international FIG rules. The long-term goal is to provide reproducible element recognition, D-score construction, execution/artistry observations, neutral-deduction detection, evidence-linked judging assistance, competition review and eventually real-time judging assistance.

## Core principle

The system must never output a naked score. Every judgement must be traceable to source video/camera, exact timecode or frame interval, detected motion evidence, recognised/candidate element, apparatus, rule-pack version, rule reference, confidence/ambiguity, deterministic score calculation where applicable, and human review/override history.

## Official rule baseline

Initial ruleset target: **World Gymnastics / FIG WAG 2025–2028 cycle, current 2026 publications**.

Primary authoritative sources:

- WAG Code of Points 2025–2028 — current publication listed 2026-03-13
- Appendix to the Code of Points 2025–2028 — current publication listed 2026-05-25
- WAG Specific Judges' Rules 2025–2028 — current publication listed 2026-03-27
- WAG Help Desk, 2nd Edition, 16th cycle, April 2026
- applicable Technical Regulations / competition rules where competition context requires them

Official source index: `https://www.gymnastics.sport/site/rules/`

FIG documents remain the source of truth. Ai.WAGVID stores a machine-readable interpretation with provenance, effective dates and tests; it is not an independent rule authority.

## Product modes

1. **Offline Analysis** — upload competition/training video and receive detailed evidence-linked analysis.
2. **Batch Competition Analysis** — process many routines and compare AI analysis with official results.
3. **Shadow Judging** — run during competition without influencing official scores; compare later with panel results.
4. **Live Judge Assist** — low-latency element/deduction suggestions and evidence for authorised judges/operators.
5. **Competition Judging Research Mode** — experimental full scoring pipeline; promotion to official use requires rules permission, validation and governance.
6. **KIGA Integration** — export validated structured athlete/event/apparatus observations without making KIGA depend on the Ai.WAGVID runtime.

## Apparatus scope

- **VT** — Vault
- **UB** — Uneven Bars
- **BB** — Balance Beam
- **FX** — Floor Exercise

## High-level pipeline

```text
Camera / Video
   ↓
Ingest + synchronisation + calibration
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
Evidence-linked judging record
   ↓
Human review / panel comparison / KIGA export
```

## Design requirements

- multi-camera capable, but usable with one camera;
- frame-accurate evidence and synchronized replay;
- versioned rules and skill database;
- human-in-the-loop by design;
- confidence-aware: ambiguity is surfaced, never hidden;
- no silent rule fallback;
- reproducible calculations;
- immutable audit trail for competition use;
- offline/on-premise deployment option for clubs/federations;
- privacy-aware handling of minors and competition footage;
- API-first integration;
- independent from KIGA, with a stable integration contract.

## Repository layout

```text
docs/
  ARCHITECTURE.md
  JUDGING_MODEL.md
  RULE_ENGINE.md
  LIVE_COMPETITION.md
  APPARATUS.md
  DATA_MODEL.md
  VALIDATION.md
  KIGA_INTEGRATION.md
  ROADMAP.md
rules/
  README.md
schemas/
  README.md
src/
models/
examples/
tests/
```

## Non-goals for the first implementation

- claiming FIG certification;
- replacing a human panel before validation;
- training on unlicensed footage without a lawful basis;
- hard-coding one Code of Points revision into application logic;
- treating model confidence as judging certainty.

## Proposed technology direction

- Python inference/services;
- OpenCV / FFmpeg media pipeline;
- PyTorch-compatible vision/temporal models;
- 2D + optional multi-view 3D pose abstraction;
- FastAPI-compatible service boundary;
- PostgreSQL for structured records/provenance;
- object storage for original/proxy/evidence clips;
- WebSocket/event stream for live operation;
- browser judging/review UI;
- containerised CPU/GPU deployment.

Technology choices remain replaceable behind interfaces until benchmarks justify them.

## Governance

A score is publishable only if its rule-pack, model versions, calibration state, evidence completeness and review state satisfy the policy for the selected operating mode. Competition/live workflows require stricter gates than training analysis.

## Project phases

- **M0 — Specification & rule provenance**
- **M1 — Video ingest, annotation and evidence system**
- **M2 — Pose / phase / element recognition research baseline**
- **M3 — Apparatus-specific D-score engine**
- **M4 — Execution / artistry / neutral deduction assistance**
- **M5 — Offline end-to-end WAG analysis**
- **M6 — Shadow judging & panel comparison**
- **M7 — Low-latency live judge assist**
- **M8 — KIGA integration**
- **M9 — Competition-grade validation / governance**

See `docs/ROADMAP.md` and GitHub issues for implementation detail.

## Legal / sporting disclaimer

Ai.WAGVID is an independent project and is not affiliated with or endorsed by FIG / World Gymnastics. FIG rules, element tables and publications remain subject to their respective rights and official publication terms. Store citations, structured interpretations and implementation logic rather than redistributing copyrighted rule documents unless redistribution is explicitly permitted.
