# Batch competition analysis

Issue: #12. Coordinates with #14 and #18.

This branch implements the pure control-plane contracts for processing many recorded competition routines while preserving the independent-analysis requirement.

## Existing exchange contract remains authoritative

The external record remains `schemas/competition-video-v1.schema.json`. KIGA or another approved source may send:

- competition and routine mapping;
- authorised video assets;
- official result;
- rights/retention/training flags;
- return links.

The batch layer does not invent a second competition format.

## Trust-domain split

Receiving an official result together with a video does **not** make it available to the analysis worker.

`plan_competition_batch()` splits each exchange record into:

1. **control-plane mapping** — competition/routine/athlete/team IDs, performed-at metadata, source-record digest and rights;
2. **identity-minimized worker task** — opaque task/idempotency handle, apparatus, rule profile, media references and analysis-profile digest;
3. **withheld official-result envelope** — canonical official-result JSON + SHA-256, retained outside the worker payload.

The worker schema is `schemas/competition-analysis-task-v1.schema.json` with `additionalProperties: false`. Athlete/team/competition/routine external IDs, official results, source-record digest, training flags and request time are therefore not legal fields in the worker contract.

This keeps identity/reputation/event context out of model features as well as official-score values.

## Idempotency and re-analysis

The task idempotency key is derived from:

- competition + routine mapping in the control plane;
- apparatus;
- rule profile;
- sorted media SHA-256 values;
- analysis-profile digest.

It deliberately excludes:

- official result and later corrections;
- adjudication/learning metadata;
- request timestamp.

Consequences:

- correcting an official score does not rerun independent AI analysis;
- retrying the same request tomorrow produces the same worker bytes/digest;
- a deliberate re-analysis is represented by a new analysis-profile/model/rulepack revision rather than a wall-clock timestamp.

## Rights gate

A routine is excluded before queueing when:

- the exchange schema version is unsupported;
- `analysis_allowed` is false;
- `download_allowed` is false for the remote media workflow;
- media is unavailable.

`training_allowed` is independent. Training may remain false while post-event analysis is allowed. Training eligibility is never inferred from download/analysis access.

## Freeze and official reveal

A `FreezeReceipt` binds:

- task ID + worker-task digest;
- analysis ID + immutable revision ID/digest;
- rulepack digest;
- model-bundle digest;
- `frozen_at`.

The official envelope may have been received before analysis started. `reveal_official_result()` still requires:

- the freeze receipt belongs to the exact task/digest;
- the withheld official envelope belongs to the same source record/routine;
- `revealed_at` is strictly later than `frozen_at`.

The returned revealed object carries both official-payload digest and freeze-receipt digest. At integration with #18, the reveal time becomes the leakage-safe official import/reveal time for score comparison while the original source `captured_at` remains source metadata.

## Batch state journal

`RoutineBatchJournal` is an append-only hash chain with legal transitions:

`queued -> running -> ai-frozen -> official-revealed -> comparison-ready -> needs-review/complete`

Failure/cancel transitions are explicit. Illegal skips, timestamp regression and hash-chain tampering fail closed.

## Disagreement aggregation

After #18 produces immutable comparison digests, `DisagreementRecord` can be aggregated descriptively by:

- apparatus;
- discrepancy category;
- element family;
- deduction category;
- camera condition.

The aggregate reports routine count, material count, total absolute difference and maximum absolute difference in integer milli-points. It does not declare either the official result or AI to be ground truth.

## Remaining #12 work

- persist batch plans/journals and durable job leases in the operational product shell;
- connect the common worker queue/compute runtime;
- construct #18 `FrozenAnalysis` from completed analyses and use revealed official result only afterward;
- generate event-level review dashboard and filters;
- build batch export/report jobs;
- combine event processing with the longitudinal foundation on `agent/performance-analysis-core`;
- implement explicit analysis-revision selector for re-analysis comparisons;
- validate full recorded-competition fixtures at routine/athlete/apparatus/event levels;
- wire KIGA notification/deep-link return flow under #14.

No live competition dependency, PR, merge or GitHub Actions run is created by this branch.
