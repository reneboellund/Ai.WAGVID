# Implementation readiness review

Date: 2026-08-16

## Ready in the local release branch

- runnable Django 5.2-compatible application shell and initial migration;
- authentication and organization membership roles;
- organization-scoped gymnast, level, device, media, analysis and exchange records;
- immutable audit-event model;
- status dashboard, operator page, gymnast create/list, device, analysis, exchange and system views;
- bootstrap command for first organization, owner membership and starter levels;
- health and database-readiness endpoints;
- existing rule, AI-layer, capture, research, schema and UI tests retained.
- worker leasing, expired-lease recovery, monotonic append-only progress and bounded retries;
- overall official-versus-AI score review with append-only conclusions and audit history;
- controlled human-reviewed learning-label export;
- leakage-safe dataset manifests and deterministic grouped splits;
- validated model-component catalogue and offline validation CLI.

## Must be completed before an internal alpha

- PostgreSQL environment settings and production-safe secret configuration;
- object-storage client and signed media access;
- external queue transport and continuously running worker process;
- Android Kotlin project with CameraX/Room/WorkManager implementation;
- authenticated device pairing and command acknowledgements;
- browser upload and resumable backend upload endpoint;
- full gymnast edit/archive/merge and CSV import dry-run;
- real system probes for object storage, worker queue and backups;
- organization selector for users belonging to multiple organizations;
- reviewer inbox filtering, synchronized replay and frame/clip evidence delivery;
- structured error pages, CSRF/security deployment checks and rate limiting;
- Docker/on-prem deployment and restore rehearsal.

## Must be completed before research evaluation

- dataset acquisition manifests and controlled storage adapters;
- split/leakage enforcement by gymnast and competition;
- FFmpeg normalization and immutable source checksums;
- RTMPose baseline adapter producing the PerceptionBundle contract;
- benchmark runner and evaluation reports;
- annotation/evidence export beyond the implemented score-label correction loop;
- canonical pose adapter interface plus MediaPipe-class baseline and RTMPose/YOLO-class challenger;
- FineGym/Gym288/OSL label and temporal-dataset adapters with athlete/event split enforcement;
- annotated proxy renderer and versioned JSON/CSV/REST/CLI analysis exports;
- separately calibrated AQA challenger channel;
- MAG rule sources, element catalogues, fixtures and apparatus-specific metric packs.

## Must be completed before any external or competition use

- privacy/consent review, retention enforcement and data-subject workflow;
- threat model, security review, audit export and incident procedure;
- redundancy, offline/failover rehearsal and capacity/load testing;
- qualified judge validation and formal rulepack release process;
- explicit authorization for any changed commercial/external scope.

## Deferred intentionally

GPU model training, large dataset downloads, full video transcodes and load tests are excluded from
this preparation run. Their interfaces and release gates must exist before those expensive jobs run.
