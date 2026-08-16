# Layered AI architecture and technology evaluation

## Implemented adapter milestone

The repository contains framework-neutral conversion adapters in
`ai_wagvid.model_adapters` for MediaPipe Pose Landmarker, COCO-keypoint outputs
from RTMPose/MMPose or YOLO-Pose, MMAction2-style class probabilities, and a
separately calibrated AQA score. Heavy frameworks are lazy optional dependencies;
the Django/API process does not import GPU frameworks merely to start.

Worker execution is fail-closed: resolve `config/model-bundles.yaml`, verify local
artifacts from `research/artifacts.yaml`, run the isolated framework worker, convert
raw output to WAGVID contracts, and persist model/config provenance. Ambiguous or
unmapped source labels increase explicit unknown probability; they are never
silently treated as FIG elements.

Use `wagvid validate-label-map research/label-maps/<file>.yaml` to validate source
labels and `wagvid verify-artifacts --root <controlled-store>` for a streaming
SHA-256 audit. Neither command downloads nor loads a model.

The starter FineGym, Gym288 and OSL maps deliberately contain no guessed FIG
mappings. They prove the ingestion contract until a pinned authoritative annotation
revision is acquired and reviewed. No trained WAGVID checkpoint is claimed yet.
Profiles remain `contract-only` until their runtime, source revision, checksum,
leakage-safe benchmark and acceptance gates are recorded.

## Decision

Ai.WAGVID uses three strict boundaries:

1. **Motion perception** detects people, apparatus, pose, geometry, contacts, flight, rotation,
   angles, landings and visibility limitations.
2. **Gymnastics interpretation** converts temporal observations into ranked element candidates,
   alternatives, unknown probability and distinguishing evidence.
3. **Deterministic FIG rule engine** consumes accepted facts under one pinned rule pack and creates
   a transparent score ledger.

No perception or interpretation adapter may output D, E or final score fields. The rule engine may
not call an ML model. Human review connects uncertain interpretation to accepted facts.

## Why

A video-to-score black box is difficult to validate, diagnose and update when rules or models
change. Layer boundaries make it possible to measure pose quality separately from element
recognition, and element recognition separately from rule correctness. A result such as
"element X 87%, alternative Y 11%, unknown 2%" remains useful and reviewable.

## Technology candidates

These are adapter candidates, not mandatory dependencies.

| Capability | Initial candidates | Evaluation focus |
|---|---|---|
| Video I/O/calibration | OpenCV, FFmpeg | timestamps, VFR, distortion, reproducibility |
| Fast pose baseline | MediaPipe, YOLO Pose | latency, setup cost, common-camera robustness |
| Research pose | MMPose/RTMPose, ViTPose | WAG keypoint accuracy, occlusion, license/deployment |
| Segmentation/tracking | SAM/SAM2, ByteTrack, BoT-SORT | identity continuity, apparatus/people occlusion |
| Temporal recognition | VideoMAE, TimeSformer, MMAction2, PyTorchVideo, SlowFast-style models | full-routine segmentation, top-k identity, OOD |
| Gymnastics dataset adapters | FineGym, Gym288-Skeleton, OSL Gymnastics Localization | label mapping, split leakage, temporal localization, source provenance |
| Temporal fusion | temporal transformers | multi-phase context without score leakage |
| 3D pose | VideoPose3D, MotionBERT | view sensitivity, metric stability, compute |
| Multi-view geometry | OpenCV triangulation/calibration | sync/calibration error and uncertainty |
| Annotation | CVAT, Label Studio | frame accuracy, revisions, adjudication, export |
| Dataset QA | FiftyOne, Roboflow | leakage checks, slices, failure exploration |
| Experiment tracking | MLflow, Weights & Biases, TensorBoard | reproducibility, artifact lineage, deployability |
| Action quality assessment | CaFlow-style and other AQA challengers | global quality correlation, calibration by discipline/apparatus, bias and explainability |

GymPose-style angle and deduction implementations are reference candidates for measurable motion
features, not authoritative rule engines. Any port must identify its source revision, license,
apparatus coverage and differences from the active WAG/MAG rule pack.

An AQA output is stored as a separate advisory quality channel. It must never be silently converted
into D, E, neutral or final score. Promotion requires calibration against held-out WAG/MAG routines
and evidence that it adds value beyond the transparent deduction ledger.

## Selection policy

Do not install every framework in the core package. The core contains contracts and serialization.
Model integrations live behind adapters with optional dependency groups or isolated services.

A candidate is promoted only after the same versioned benchmark suite reports:

- accuracy by apparatus, camera condition, visibility and skill family;
- top-1/top-k element recognition and unknown/OOD behavior;
- contact/flight/landing event timing error;
- calibration and multi-view sensitivity;
- confidence calibration;
- CPU/GPU latency, memory and operational complexity;
- license, offline deployment and data-governance compatibility.

## Initial implementation sequence

1. OpenCV/FFmpeg media and calibration foundation.
2. One fast 2D pose/tracking baseline and one research-quality challenger.
3. Motion primitives and evidence overlays.
4. Temporal segmenter with family-first, top-k interpretation.
5. Optional SAM2 and 3D/multi-view experiments only where benchmarks show value.
6. Deterministic rule engine integration after human acceptance of interpreted facts.

## Runtime profiles

- **coaching-low-compute:** MediaPipe-class baseline, angles and training feedback;
- **competition-research:** YOLO-Pose/RTMPose-class pose plus temporal recognition and evidence;
- **high-precision/multi-view:** MMPose/3D challengers, calibrated cameras and fusion;
- **benchmark:** multiple adapters run on the same frozen inputs without selecting by athlete identity.

Profiles select compatible adapters; the production pipeline does not load every framework at once.

## Learning boundary

Official scores are not perception inputs. Evaluation analysis is frozen before official results are
revealed. Official scores may seed silver-label comparisons; expert-adjudicated elements,
observations and deductions are the preferred training targets. Athlete identity, club, nationality,
reputation and ranking are prohibited scoring and technical-quality features.
