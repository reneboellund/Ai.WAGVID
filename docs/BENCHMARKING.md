# Reproducible model benchmarking

Benchmark reports use only frozen validation or test splits from a governed dataset manifest.
Training-split reports are rejected to reduce accidental metric leakage. Every run records dataset
identity/version, exact model profile and bundle digest, software revision, optional rule pack and
start time.

The baseline report includes top-1/top-k element accuracy, unknown/OOD recall, false-unknown rate,
absolute temporal-event error and confidence error. The same metrics are repeated for apparatus and
declared slices such as camera type, visibility, venue or frame-rate class. Athlete identity,
nationality, club, reputation and prior ranking are prohibited feature inputs; sensitive audit
slices may be evaluated under controlled access without becoming model features.

Reports conform to `schemas/benchmark-report-v1.schema.json`. Benchmark output is evidence for
model selection, not a FIG score, and no challenger can be promoted solely from a global average.

Pose baselines use `ai_wagvid.pose_benchmark` separately from element metrics. The report includes
normalized keypoint error, PCK, expected-keypoint detection, confidence/visibility calibration,
inference latency, RAM and VRAM, repeated by apparatus, camera condition and challenge slice. The
planned two-configuration RTMPose/RTMW comparison is recorded in
`research/benchmarks/rtmpose-spike.yaml`; its blocked status is intentional until artifacts and a
rights-cleared, leakage-safe validation manifest have verified digests. Every promoted component
must also complete `docs/MODEL_CARD_TEMPLATE.md` and link its failure gallery.
