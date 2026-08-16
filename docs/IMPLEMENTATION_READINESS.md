# Implementation readiness review

Date: 2026-08-17

See `docs/CURRENT_STATUS.md` for the compact source-of-truth implementation summary. This document focuses on release gates.

## Ready in the current `main` baseline

- runnable Django 5.2-compatible application shell with organization-scoped authentication and roles;
- Concept 3 operational UI across dashboard, gymnasts/levels, devices, capture, analyses, exchange, competitions, system status and evidence review;
- organization-scoped gymnast create/edit/archive/restore and level create/edit/deactivate with append-only audit events;
- organization-scoped device, media, analysis, competition and exchange records;
- resumable Android upload API with strict offsets, SHA-256 verification and idempotent finalize;
- durable analysis-worker leases, expired-lease recovery, append-only progress and bounded retries;
- health/database readiness endpoints and operational status cards;
- atomic gymnast CSV preview/import, row-error report and UTF-8 CSV export;
- short-lived signed immutable-media access with authenticated source-video review and HTTP byte-range seeking;
- evidence review with millisecond evidence jumps, deduction decisions, overall official-versus-AI score adjudication and append-only history;
- controlled human-reviewed learning-label export;
- leakage-safe dataset manifests and deterministic grouped athlete/event/source splits;
- model-component catalogue, model-neutral analysis contracts and offline validation CLI;
- KIGA competition/routine/video/official-result no-write preview + atomic import and schema-compatible export;
- rights-gated external media catalogue with immutable official-result versions;
- native Android Kotlin/Compose/CameraX/Room/WorkManager project foundation plus backend pairing, heartbeat and command contracts;
- Wasabi layout/cost/reconciliation/provider foundation behind the storage abstraction;
- Python 3.11/3.13 repository validation covering Ruff, pytest, source registry and rule-pack manifest.

## Must still be completed before an internal alpha

- production-safe secrets/configuration workflow and durable credential administration;
- continuously running external worker/queue deployment and real operational probes;
- production object-storage connection/admin workflow and persisted storage-routing/retention metadata;
- Android production UI wiring for pairing, gymnast/capture context, archive/queue/device health and command reconciliation;
- Android SDK/Gradle plus emulator/physical-device validation, including network-loss recovery;
- audited gymnast duplicate merge and richer import field mapping/profiles;
- user invitations, role administration and multi-organization selector;
- persisted canonical frame timeline/index and exact frame stepping in review;
- full annotation authoring/revision comparison UX;
- structured error pages, deployment security checks and rate limiting;
- Docker/on-prem deployment plus backup/restore rehearsal.

## Must still be completed before research evaluation

Already ready as foundation:

- dataset manifest/governance structures;
- gymnast/event/source leakage-safe split enforcement;
- immutable source checksums and media inspection/timeline utilities;
- model-neutral perception/export/benchmark interfaces;
- benchmark manifest/report scaffolding and reviewed-label correction loop.

Still required empirically/operationally:

- durable FFmpeg normalization/proxy execution and persisted canonical frame indexing;
- rights-cleared RTMPose/RTMW benchmark producing real measured results;
- promotion or rejection of an executable pose/tracker baseline based on those measurements;
- temporal segmentation/element-recognition benchmark and OOD/confusion evaluation;
- annotation/evidence export integrated with the authoring workstation;
- apparatus-specific validation data and deterministic scoring/deduction coverage;
- calibrated AQA challenger results kept separate from deterministic scoring;
- MAG rule-source/content expansion where production scope requires it.

No RTMPose/RTMW checkpoint, GPU benchmark or large production inference run has been completed merely because adapters and manifests exist.

## Must be completed before any external or competition use

- privacy/consent review, retention enforcement and data-subject workflow;
- threat model, security review, audit export and incident procedure;
- production object-store/worker redundancy, backup/restore and capacity/load testing;
- qualified judge validation and formal released rule-pack process;
- validated model cards and benchmark evidence for any promoted inference models;
- explicit authorization for any changed commercial/external scope.

## Deferred intentionally

GPU model training, large dataset/model downloads, bulk video transcodes, Android release builds and load tests are not run as routine development checks. They require an explicit milestone-specific reason. Development should continue to prefer cheap contract/unit/integration work and one consolidated repository validation at meaningful integration boundaries.
