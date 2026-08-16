# Verified research baselines

Verified on 2026-08-16 against primary paper/project sources. The machine-readable decision
record is `research/baselines.yaml`.

## Decision summary

- **Start one MMPose/RTMPose spike.** It is the strongest practical first pose baseline and the
  framework is Apache-2.0. Each checkpoint and source dataset still needs its own provenance audit.
- **Use FineGrade/FineGym-AQA as a benchmark design reference.** The CVPR Findings 2026 paper and
  score-augmented annotations are verified. At verification time the public repository exposed
  annotations and result books, but no explicit repository license and no clearly visible training
  implementation. Do not ingest or redistribute data until rights and artifacts are confirmed.
- **Use FineGym taxonomy and MMAction2 preparation as research inputs only after rights review.**
- **Use AthletePose3D to quantify domain shift, not as product training data.** Its repository
  restricts use to non-commercial scientific research and notes corrected 3D artifacts.
- **Benchmark MotionBERT and KASportsFormer as 3D challengers**, not default dependencies.
- **Treat Hierarchical NeuroSymbolic AQA as architecture evidence.** Its diving symbols/rules do not
  transfer directly to WAG, but its neural-observation -> symbols -> rules boundary supports ours.

## FineGrade compatibility assessment

FineGrade is close to Ai.WAGVID in temporal parsing and rule-consistent totalization, but its
routine-level D/E/ND/total supervision does not replace:

- current versioned FIG/WAG rule interpretation;
- element- and deduction-level evidence;
- official-score freeze and leakage controls;
- human adjudication of official-vs-AI disagreements;
- data rights and competition/athlete split governance.

It should become a comparison baseline. Ai.WAGVID remains a provenance-first system whose
deterministic rule engine operates on accepted facts.

## First executable spike

Produce a reproducible offline benchmark adapter for RTMPose-L/RTMW on a small, rights-cleared WAG
validation set. The spike must output the existing `PerceptionBundle` contract and report:

- 2D keypoint accuracy or expert-reviewed proxy labels;
- inverted/extreme-pose, blur and occlusion slices;
- event-timing impact for contact, flight and landing;
- confidence calibration and missing-keypoint behavior;
- runtime, VRAM/RAM and resolution;
- checkpoint/config/license provenance.

No model is promoted merely because a demo overlay looks plausible.
