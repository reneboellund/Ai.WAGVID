# WAG/MAG engineering handoff addendum

This document incorporates the supplied v1.0 handoff into Ai.WAGVID's existing provenance-first
architecture. It is a planning and adapter catalogue, not evidence that a named model, checkpoint or
dataset is already installed, licensed, validated or suitable for FIG-style decisions.

## End-to-end contract

```text
immutable video + timing/calibration
  -> person/apparatus tracking and 2D/3D pose adapter
  -> normalized skeleton, angles, rotation/contact/flight/landing observations
  -> temporal segments and ranked skill candidates
  -> human/policy accepted facts
  -> pinned deterministic WAG/MAG rule pack
  -> transparent score and deduction ledger
  -> review, annotated proxy video, JSON, CSV, REST and CLI exports
```

The annotated video is a derived proxy. Original frames, transcoded frames, interpolated content and
AI overlays must be visually distinguishable and traceable to the immutable source checksum.

## Adapter work packages

| Package | Candidates | Required output/gate |
|---|---|---|
| Pose baseline | MediaPipe | canonical keypoints, confidence, missing joints, runtime report |
| Dynamic pose | YOLO-Pose/GymPose-derived candidate | same contract plus rotation/occlusion benchmark |
| Precision/3D | MMPose/RTMPose, later multi-view | calibration provenance and uncertainty |
| Post-processing | skeleton normalization, joint angles, rotation compensation | unit conventions, coordinate frames and reproducible transforms |
| Temporal/action | MMAction2 adapters for FineGym, Gym288 and OSL | canonical segment/top-k candidates, unknown probability, leakage-safe splits |
| Deductions | GymPose-inspired measurable features plus apparatus packs | evidence interval, measurement, active rule reference and allowed severity |
| AQA | CaFlow-style challenger | separate advisory score, calibration and correlation report; never direct FIG total |
| Rendering/export | overlay, timeline, JSON, CSV, REST, CLI | schema version, provenance, source/derived distinction |

Canonical Python contracts now live in `ai_wagvid.perception` (`PoseFrame`, `PerceptionBundle`),
`ai_wagvid.actions` (`ActionSegment`) and `ai_wagvid.quality` (`QualityAssessment`). The action
contract preserves ranked alternatives and unknown probability instead of forcing one skill label.

Heavy frameworks remain optional services or dependency groups. Runtime profiles choose adapters;
"all integrated" means they implement common contracts and can be benchmarked, not that every model
runs for every video.

The supplied proposal to aggregate `aqa_score` directly into `RoutineScore.final_score` is rejected.
AQA may be displayed, correlated and used for research prioritisation, but D/E/neutral/final values
remain outputs of accepted facts plus a pinned deterministic rule pack.

## Supporting pretraining candidates

PoseTrack, COCO-Keypoints, PennAction, Sports-1M and AIST++ are catalogue candidates for general
pose/action representation and robustness experiments. They are not gymnastics truth datasets.
Every artifact requires an individual manifest entry, terms/provenance record and a held-out WAG/MAG
domain-gap report before use. No download is implied by listing a candidate.

## API and CLI target surface

- asynchronous `POST /api/analyses/` rather than a long-running synchronous request;
- `GET /api/analyses/{id}/` for job state and versioned result links;
- versioned pose, segment, score-ledger, AQA and provenance exports;
- CLI target `wagvid-analyze <input> --discipline WAG|MAG --apparatus <code> --output <dir>`.

The existing durable `AnalysisJob` is the orchestration boundary. Large video/model operations run in
workers and expose progress; web requests must not hold GPU inference open.

## Apparatus metric backlog

- **BB:** wobble, centre-of-mass deviation, turn precision, landing stability.
- **UB:** handstand alignment, swing amplitude, cast angle, release/regrasp and dismount rotation.
- **FX:** pass segmentation, jump height, landing stability, salto/body line.
- **VT:** board contact, block angle, flight height/distance and landing control.
- **MAG PH:** support/hand sequence, circle form, travel and interruption candidates.
- **MAG SR:** hold duration/stability, strength-position geometry, swing-to-strength and landing.
- **MAG PB:** support/brachial phases, handstand alignment, flight/regrasp and dismount.
- **MAG HB:** giant/release/regrasp timing, turn geometry, flight and dismount.

Each metric first produces an observation with camera suitability and uncertainty. A versioned rule
pack—not the metric/model—determines whether it can support a deduction.

## Definition of done per model adapter

1. Source, code, checkpoint, dataset and terms recorded in the research manifest.
2. Input/output mapped to canonical contracts with deterministic fixtures.
3. Frozen athlete/event-separated benchmark completed by apparatus and failure slice.
4. Confidence/OOD, runtime, compute and operational failure behaviour reported.
5. Human-visible evidence generated and provenance retained.
6. Promotion decision recorded; failed challengers remain reproducible but disabled.

## Delivery sequence

1. Complete immutable ingest, FFmpeg timing and one canonical pose bundle.
2. Implement MediaPipe-class baseline and RTMPose/YOLO-class challenger behind the same interface.
3. Add angles, apparatus geometry, contact/flight/landing primitives and overlay renderer.
4. Add OSL-style segmentation, then FineGym/Gym288 label adapters and top-k recognition.
5. Deliver one vertical apparatus slice through deterministic rules, review and exports.
6. Expand WAG apparatus coverage, then validate MAG apparatus packs independently.
7. Benchmark 3D/multi-view and AQA challengers only after the transparent baseline is stable.
