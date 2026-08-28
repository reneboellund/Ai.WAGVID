# Post-event validation and release governance

Issue: #15. Scope follows master epic #17.

This module defines what Ai.WAGVID is allowed to claim about a release. It does not validate by reputation, one headline MAE, or a future live-judging roadmap. The current promotion model ends at **validated production post-event analysis**.

## Current promotion gates

The only gates represented in code are:

1. `research-fixture`
2. `offline-component`
3. `integrated-post-routine`
4. `qualified-user-pilot`
5. `production-post-event`

There are deliberately no `shadow`, `live-assist`, `competition-grade` or `official-scoring` enum values. A future change in product scope must therefore change the governed contract rather than reusing an old dormant gate.

## Slice-first validation

A `ValidationRun` belongs to one validation layer and one exact benchmark slice. A slice may specify:

- apparatus;
- camera condition;
- skill family;
- challenge tags such as OOD/rare/difficult;
- rights-cleared or synthetic dataset digest;
- train/test split manifest digest;
- sample count.

A `ValidationRequirement` selects the exact slice shape and metric IDs required for one release claim.

An aggregate run with excellent results cannot satisfy a requirement for a missing apparatus/camera/challenge slice. The release manifest lists only the scopes selected by satisfied requirements.

## Validation layers

The core supports independent evidence for:

- media integrity;
- perception;
- segmentation;
- D-score;
- deduction evidence;
- score verification;
- performance analysis;
- review workflow;
- runtime;
- governance.

A promotion policy decides which layers/slices/metrics are required for a particular gate.

## Dataset rights and split provenance

Each benchmark slice references `DatasetEvidence` with:

- dataset ID + SHA-256;
- rights status;
- rights reference/digest for cleared data;
- immutable split-manifest SHA-256.

`uncleared` dataset evidence creates a hard blocker. Synthetic fixtures may be represented explicitly as synthetic rather than pretending they have a third-party licence.

## Exact metrics

`MetricResult` uses finite `Decimal` values and a deterministic threshold comparison (`at-least` / `at-most`). A requirement names the metric IDs it needs.

This allows policies to require separate metrics such as:

- top-k error/accuracy;
- unknown/OOD performance;
- unresolved/abstention rate;
- timing error;
- category/severity agreement;
- review intervention rate;
- reliability/runtime metrics.

If a required unresolved/abstention metric is missing, a good accuracy metric cannot substitute for it.

## Non-waivable blockers

The following are derived directly from a validation run and have no waiver target in the model:

- uncleared dataset rights;
- detected official-score leakage;
- invalid rulepack provenance;
- invalid audit/provenance traceability;
- invalid source-media integrity.

A named approver cannot override these using a regression waiver. The evidence must be rerun correctly.

## Regression waivers

A `RegressionWaiver` can target only one failed metric on one exact validation run.

It records:

- waiver ID;
- run + metric;
- named approver;
- reason;
- approval time;
- expiry time.

The metric itself must be marked waivable. Expired waivers stop satisfying the requirement automatically. Non-waivable metrics, such as a policy-defined unresolved-rate gate, remain blockers even if a waiver record exists.

## Deterministic promotion decision

`evaluate_promotion()`:

1. filters evidence to the exact release digest;
2. evaluates every policy requirement independently;
3. matches exact layer/slice constraints;
4. enforces minimum sample count;
5. rejects derived hard blockers;
6. requires every named metric or an active legal metric waiver;
7. chooses the newest passing matching run deterministically, using digest as tie-breaker;
8. returns only the exact validated scopes.

A partially satisfied promotion remains `blocked`, but its already validated scopes stay visible. This is useful for showing precise progress without broadening the release claim.

## Release validation manifest

`ReleaseValidationManifest` binds:

- release/model/rule/software digests;
- immutable promotion-decision digest;
- policy ID/digest;
- current post-event gate + status;
- exact validated scopes and benchmark dataset digests;
- active waiver digests;
- blockers;
- known limitations;
- creation time.

Public schema: `schemas/release-validation-v1.schema.json`.

The manifest is intended to become part of the release metadata consumed by #73 upgrade/preflight and the administration UI.

## Validation philosophy

A release may claim only the slice it has actually validated. Examples:

- passing BB broadcast does not imply BB fixed-camera support;
- common skills do not imply rare/OOD skills;
- aggregate final-score MAE does not imply correct element identity, deduction severity or D-ledger reasoning;
- low review burden does not compensate for official-score leakage;
- newer model output does not rewrite old validation evidence because runs are digest-bound.

Qualified expert/judge consensus and expert-adjudicated cases remain preferred gold evidence. Official results are useful comparison/silver evidence but never the sole truth source.

## Remaining work before #15 closes

- define reviewed promotion policies and metric thresholds for each component/gate;
- connect rights-cleared benchmark dataset registry and split manifests;
- add apparatus/camera/rare/OOD challenge fixtures;
- import benchmark results from actual perception/segmentation/scoring/runtime validation workers;
- define judge/category/severity agreement metrics with qualified reviewers;
- measure review burden, abstention and unresolved rates in pilot workflows;
- persist signed/append-only release validation manifests;
- integrate manifest with release/upgrade preflight (#73) and admin release UI;
- define release waiver authority and incident/expiry workflow operationally;
- validate production-post-event policy with qualified WAG reviewers and documented acceptance thresholds.

No live/shadow/official-scoring claim, PR, merge, GitHub Actions run or external benchmark resource is created by this branch.
