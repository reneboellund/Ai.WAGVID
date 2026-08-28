# Current implementation status

Governance control-plane milestone: organization switching, hashed invitations, audited role changes, immutable configuration revisions, explicit dataset permissions with pseudonymous grouping, revocable evidence shares and scoped audit export are implemented locally and covered by Django tests. External identity-provider/email delivery and formal deployment threat-model review remain future integration work.

Date: 2026-08-17

This file is the compact implementation-status source of truth for the active development baseline. Detailed product intent remains in the roadmap and issue tracker; this file records what is actually present in `main` versus what still requires implementation or empirical validation.

## Current baseline

The consolidated baseline includes the work merged through PRs #46, #49, #50, #51, #52, #53 and #54. Current `main` after PR #54 is `fa2a44a`.

### Operational web product

Implemented:

- Django 5.2-compatible modular monolith with organization-scoped authentication and roles;
- Concept 3 responsive operational interface across dashboard, gymnasts, levels, devices, capture operations, analyses, exchange, system status, competition browsing and review;
- gymnast create/edit/archive/restore and level create/edit/deactivate with append-only audit events;
- atomic gymnast CSV preview/import, error report and CSV export;
- health/database readiness and operational status views;
- organization-scoped, idempotent analysis-job API and durable worker lease/progress/retry contracts.

Still required for internal-alpha completeness:

- multi-organization selector plus user invitation/role administration;
- audited gymnast duplicate merge and richer import field mapping/profiles;
- hardened error/security/rate-limit administration;
- real backup/restore and continuously running external worker/queue deployment rehearsal.

### Media and evidence

Implemented:

- immutable retained source-media records and SHA-256 integrity semantics;
- resumable Android upload API with strict offsets, checksum verification and idempotent finalize;
- FFprobe inspection and canonical PTS/DTS/best-effort timeline utilities with VFR/gap diagnostics;
- immutable canonical frame-timeline sidecars bound to the exact source SHA-256;
- organization-scoped timeline API and management-command import path for already-produced FFprobe frame payloads;
- short-lived organization-scoped signed media grants;
- authenticated source-video playback in evidence review;
- single HTTP byte-range delivery for efficient browser seeking;
- exact millisecond jumps from deduction candidates plus ±100 ms source-time nudging;
- canonical previous/next frame stepping and frame-number display when a validated timeline sidecar exists, without assuming constant FPS;
- append-only evidence, annotation-revision and adjudication contracts.

Still required:

- automated worker-side FFprobe timeline generation during ingest/analysis;
- durable FFmpeg normalization/proxy execution and persistence;
- camera registry, persisted calibration lifecycle and multi-camera synchronization/drift handling;
- full annotation-authoring workstation and dataset-export UX.

Important boundary: review is frame-accurate only when the canonical sidecar for the exact source SHA-256 exists. Otherwise the player deliberately remains source-time accurate and does not invent frame numbers.

### Android capture

Implemented and repository-build validated:

- native Kotlin/Compose project with CameraX preview/video capture;
- Room-backed local archive records with retained local files;
- WorkManager resumable authenticated upload queue with SHA-256 verification;
- encrypted credential storage;
- in-app device pairing using the backend pairing session/code contract;
- authenticated capture-context loading after pairing and on later starts;
- real gymnast selection by stable UUID plus display name/license/level and server-advertised media-kind selection;
- manual capture is blocked until valid server context exists and no longer writes `unassigned` placeholder metadata;
- release networking is HTTPS-only while debug builds may use local HTTP/user-installed development certificates for on-prem testing;
- server-side pairing, heartbeat, capture context, idempotent ARM/DISARM/START/STOP commands and acknowledgements;
- Concept 3 pairing/device/operate WebUI;
- path-filtered Android CI using Java 17 + Gradle 8.10.2; `assembleDebug` and `testDebugUnitTest` passed on PR #54;
- Java/Kotlin/KSP are explicitly aligned on JDK 17 and the CameraX controller uses the correct `androidx.camera.view.video.AudioConfig` API.

Still required before treating Android as a release client:

- heartbeat scheduling and command polling integrated into the Android lifecycle;
- actual Android execution/reconciliation of remote ARM/DISARM/START/STOP commands;
- foreground/background capture-service hardening while preserving local Stop authority;
- motion-triggered/pre-roll/post-roll end-to-end behavior;
- device health, storage, upload queue and local archive screens;
- certificate fingerprint/pinning UX and reconnect/re-pair lifecycle;
- physical-device and emulator validation including network loss/recovery.

A green repository Android build must not be confused with physical-device acceptance testing.

### KIGA and competition exchange

Implemented:

- `competition-video-v1` no-write schema preview followed by atomic commit;
- stable gymnast/event/routine/media mappings without name-based primary identity;
- competition metadata, authorized external media catalogue and explicit rights fields;
- append-only official-result snapshots and withdrawal/version protection;
- AI-freeze/official comparison and human adjudication/learning eligibility fields;
- competition browser and schema-compatible KIGA routine round-trip export.

Still required for the broader KIGA integration milestone:

- stable public analysis read/export API surface;
- durable batch JSON/Parquet/report exports;
- schema-version negotiation and notification/event interface;
- secure evidence deep links intended for external KIGA clients;
- longitudinal combined competition/video-development workflow.

### AI / research layer

Implemented foundation:

- versioned model-neutral perception/action/interpretation/AQA boundaries;
- pose normalization, camera-rotation compensation, confidence-gated joint angles and temporal smoothing;
- calibration and motion-feature primitives;
- dataset manifests, rights/governance metadata and grouped leakage-safe splits;
- model-bundle/profile catalogue, benchmark/report schemas and offline validation CLI;
- reproducible RTMPose benchmark manifest/scaffolding;
- structured JSON/CSV analysis export contracts and reviewed-label gating.

Not yet empirically completed:

- no RTMPose/RTMW checkpoint has been promoted from a rights-cleared WAG/MAG benchmark;
- no GPU benchmark, large model download or production pose inference baseline has been authorized/executed in this baseline;
- no temporal element recognizer has been empirically promoted;
- no complete apparatus-specific deterministic score/deduction engine has reached product-complete status.

Do not confuse model/benchmark scaffolding with measured model quality.

### Score review and performance analysis

Implemented:

- official result and AI proposal channels remain separate;
- evidence-linked deduction candidates;
- reviewer accept/correct/reject/official-error/inconclusive decisions;
- append-only score-comparison adjudication and review history;
- controlled reviewed-label export;
- signed source-video evidence playback;
- VFR-safe canonical frame stepping when a source-bound timeline sidecar exists.

Still required:

- complete element timeline and deterministic D-score ledger UI;
- grouped deduction explorer and accepted E/neutral arithmetic report;
- complete score-verification report and export;
- strength/weakness/pattern aggregation;
- longitudinal athlete trends and coach confirmation/prioritization workflow.

## Validation policy

GitHub remains the source of truth. Development follows a cost-conscious integration policy:

- batch related changes into meaningful commits/PRs;
- use PR validation at integration boundaries rather than repeatedly during intermediate edits;
- inspect one representative failed run before changing code or rerunning anything;
- after a concrete fix, let one new automatic run validate the fix instead of rerunning stale jobs;
- keep Android validation path-filtered to Android changes;
- do not run model downloads, dataset downloads, FFmpeg transcodes, GPU benchmarks or load tests without a milestone-specific reason.

Recent validation baseline:

- PR #53: Python 3.11 and 3.13 passed Ruff, 174 tests, source-registry validation and draft rule-pack validation;
- PR #54: Android `assembleDebug` and `testDebugUnitTest` passed after the repository's pre-existing JVM-target and CameraX import problems were fixed.
