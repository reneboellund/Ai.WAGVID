# Current implementation status

Date: 2026-08-17

This file is the compact implementation-status source of truth for the active development baseline. Detailed product intent remains in the roadmap and issue tracker; this file records what is actually present in `main` versus what still requires implementation or empirical validation.

## Current baseline

The consolidated baseline includes the work merged through PRs #46, #49, #50, #51 and #52.

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
- short-lived organization-scoped signed media grants;
- authenticated source-video playback in evidence review;
- single HTTP byte-range delivery for efficient browser seeking;
- exact millisecond jumps from deduction candidates plus ±100 ms source-time nudging;
- append-only evidence, annotation-revision and adjudication contracts.

Still required:

- durable FFmpeg normalization/proxy execution and persistence;
- persisted canonical frame index/timeline linked to each MediaAsset revision;
- exact frame stepping and frame-number display derived from that persisted timeline;
- camera registry, persisted calibration lifecycle and multi-camera synchronization/drift handling;
- full annotation-authoring workstation and dataset-export UX.

Important boundary: the current evidence player is source-time accurate. It must not be described as frame-accurate until canonical frame indexing is persisted and wired into review.

### Android capture

Implemented foundation:

- native Kotlin/Compose project;
- CameraX capture controller;
- Room-backed local archive records;
- WorkManager upload queue;
- SHA-256 upload verification;
- encrypted credential storage and HTTPS policy;
- mDNS/manual discovery components;
- backend pairing, heartbeat, capture context, command queue and acknowledgements;
- idempotent ARM/DISARM/START/STOP server controls;
- server-side Concept 3 pairing/device/operate UI.

Still required before treating Android as a usable release client:

- production UI wiring for pairing/session/context rather than prototype `unassigned` capture state;
- device health/archive/upload queue screens;
- command polling/reconciliation integrated into app lifecycle;
- motion-triggered/pre-roll/post-roll end-to-end behavior;
- physical-device, network-loss, Android SDK/Gradle and emulator/device validation.

No Android APK/device validation result should be inferred from the repository scaffolding alone.

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
- source-video evidence playback for stored originals.

Still required:

- complete element timeline and deterministic D-score ledger UI;
- grouped deduction explorer and accepted E/neutral arithmetic report;
- complete score-verification report and export;
- strength/weakness/pattern aggregation;
- longitudinal athlete trends and coach confirmation/prioritization workflow.

## Validation policy

GitHub remains the source of truth. Development currently follows a cost-conscious integration policy:

- batch related changes into meaningful commits/PRs;
- use the existing PR validation once at the integration boundary rather than repeatedly during intermediate edits;
- inspect a failed run before rerunning anything;
- after a concrete fix, let one new automatic run validate the fix;
- do not run model downloads, dataset downloads, FFmpeg transcodes, Android SDK builds/emulators, GPU benchmarks or load tests without a milestone-specific reason.

The most recent code integrations through PR #52 passed the repository validation matrix on Python 3.11 and 3.13, including Ruff, full pytest, source-registry validation and draft rule-pack-manifest validation.
