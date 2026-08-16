# Verified research baselines

## Reference-data integration

`research/baselines.yaml` is the discovery catalogue, `research/artifacts.yaml` is
the acquisition/checksum manifest, and `research/label-maps/` is the only permitted
bridge from source indices to WAGVID candidates. Media, annotations, weights and
identity-bearing derivatives remain outside Git in controlled research storage.
An artifact without a matching recorded SHA-256 is always unverified, even when a
file exists at the expected path.

Verified on 2026-08-16 against primary paper/project sources. The machine-readable decision
record is `research/baselines.yaml`. Ai.WAGVID is currently an internal, non-commercial research
and test tool; `docs/RESEARCH_DATA_POLICY.md` defines the data boundary.

## Decision summary

- **Start one MMPose/RTMPose spike.** It is the strongest practical first pose baseline and the
  framework is Apache-2.0. Each checkpoint and source dataset still needs its own provenance audit.
- **Use AthletePose3D for controlled internal research.** Its non-commercial scientific-research
  restriction matches the current project scope. It may be used for domain-gap benchmarking and
  research training, subject to its terms, corrected artifacts, controlled storage and no
  redistribution.
- **Keep FineGrade/FineGym-AQA on research hold until their actual terms are recorded.** Internal
  use is not a substitute for a license or source-video permission.
- **Use FineGym taxonomy and MMAction2 preparation after the same rights review.**
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

It should become a comparison baseline once its use terms are verified. Ai.WAGVID remains a
provenance-first system whose deterministic rule engine operates on accepted facts.

## First executable spike

Produce a reproducible offline benchmark adapter for RTMPose-L/RTMW on a controlled WAG validation
set. The set may combine permissioned project footage and research datasets whose terms explicitly
allow the current internal, non-commercial use. The spike must output the existing
`PerceptionBundle` contract and report:

- 2D keypoint accuracy or expert-reviewed proxy labels;
- inverted/extreme-pose, blur and occlusion slices;
- event-timing impact for contact, flight and landing;
- confidence calibration and missing-keypoint behavior;
- runtime, VRAM/RAM and resolution;
- checkpoint/config/license/data provenance.

No model is promoted merely because a demo overlay looks plausible.
