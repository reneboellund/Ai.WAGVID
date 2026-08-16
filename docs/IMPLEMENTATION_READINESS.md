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

## Must be completed before an internal alpha

- PostgreSQL environment settings and production-safe secret configuration;
- object-storage client and signed media access;
- durable job backend with idempotency and progress events;
- Android Kotlin project with CameraX/Room/WorkManager implementation;
- authenticated device pairing and command acknowledgements;
- browser upload and resumable backend upload endpoint;
- full gymnast edit/archive/merge and CSV import dry-run;
- real system probes for object storage, worker queue and backups;
- organization selector for users belonging to multiple organizations;
- review inbox and evidence workspace skeleton;
- structured error pages, CSRF/security deployment checks and rate limiting;
- Docker/on-prem deployment and restore rehearsal.

## Must be completed before research evaluation

- dataset acquisition manifests and controlled storage adapters;
- split/leakage enforcement by gymnast and competition;
- FFmpeg normalization and immutable source checksums;
- RTMPose baseline adapter producing the PerceptionBundle contract;
- benchmark runner, model-run provenance and evaluation reports;
- annotation/review export and human correction loop.

## Must be completed before any external or competition use

- privacy/consent review, retention enforcement and data-subject workflow;
- threat model, security review, audit export and incident procedure;
- redundancy, offline/failover rehearsal and capacity/load testing;
- qualified judge validation and formal rulepack release process;
- explicit authorization for any changed commercial/external scope.

## Deferred intentionally

GPU model training, large dataset downloads, full video transcodes and load tests are excluded from
this preparation run. Their interfaces and release gates must exist before those expensive jobs run.
