# Camera calibration, synchronization and canonical evidence

This branch implements the provider/model-neutral contracts behind issues #2 and #3 without requiring OpenCV, camera hardware or a database migration.

## Compatibility boundary

Existing `ai_wagvid.calibration.ApparatusCalibration` and `ai_wagvid.evidence.EvidenceReference` remain available and retain their existing v1 digest behavior.

New work is additive:

- `camera_calibration.py` — immutable camera identity plus intrinsic/extrinsic calibration histories.
- `multicamera_sync.py` — affine clock offset/drift models fitted from timestamp anchors, with residual, drift and extrapolation gates.
- `apparatus_geometry.py` — normalized single-camera 2D geometry for VT/UB/BB/FX with explicit capabilities and append-only supersession.
- `evidence.py` — `CanonicalEvidenceReference` v2 using exact source ticks/rational timebase, multi-camera intervals and explicit calibration/synchronization bindings.
- `annotations.py` — `CanonicalAnnotationRevision` v2 with evidence-preserving revision chains and leakage-safe training-label export.

This is intentionally a migration path rather than a second mutable source of truth. Existing persisted v1 references can remain readable while new analysis paths adopt the v2 contracts.

## Safety invariants

1. Camera IDs and hardware fingerprints are stable identities. A camera ID cannot silently be rebound to different hardware.
2. Calibration records are immutable. A newer record explicitly supersedes one older record and histories cannot fork.
3. Extrinsic rotations must be proper 3D rotations; reflections and malformed matrices are rejected.
4. Synchronization does not assume equal/fixed FPS. Clock mapping uses timestamp anchors and frame selection uses actual presentation timestamps.
5. Clock drift, residual error and extrapolation are bounded by policy. Outside those bounds synchronization is unavailable rather than guessed.
6. Apparatus geometry reports only calibrated capabilities. Missing FX boundary geometry, for example, cannot be interpreted as evidence that an athlete remained in bounds.
7. Canonical evidence binds source SHA-256, timeline digest, stream, exact frame indices, source ticks and rational timebase.
8. Multi-camera evidence may bind intrinsic, extrinsic, apparatus-geometry and synchronization digests independently per camera interval.
9. Pose/geometry/track overlays and interpolated views are derived visualizations. They always reference the source-evidence digest and are never marked as original evidence.
10. Material annotation/review changes are append-only. Revisions cannot silently replace evidence, and element/deduction decisions cannot be bulk accepted.
11. Accepted training-label exports contain stable pseudonymous grouping keys and canonical source references; names are not part of the public label contract.

## What remains for integration validation

The contracts are deliberately pure and can be exercised in ordinary unit tests. Completion of #2/#3 still requires integration work at the appropriate merge point:

- persist camera/calibration/geometry records in the operational Django model where needed;
- hook the media worker/FFprobe timeline pipeline into ingest automatically;
- wire CameraX/other camera registration to stable camera identities;
- implement calibration tooling/UI and real camera fixtures;
- feed canonical evidence into the frame-accurate annotation UI;
- validate real multi-camera audio/flash/timecode/PTP anchors and camera drift;
- add OpenCV or equivalent calibration estimators as replaceable adapters, not core dependencies;
- run representative fixed-camera and broadcast-video acceptance fixtures.

No PR, merge, cloud resource, camera device or GitHub Actions run is created by this branch work.
