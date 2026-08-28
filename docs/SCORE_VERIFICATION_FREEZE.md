# Score verification freeze and discrepancy adjudication

Issue: #18

This branch implements the leakage-safe comparison and adjudication core for post-routine score verification.

## Freeze first, official score second

`FrozenAnalysis` binds:

- analysis ID + immutable revision ID;
- source-media/quality snapshot digest;
- reconstructed score components known at freeze time;
- D-ledger digest/reference;
- optional deduction-ledger digest/reference;
- pinned rulepack ID + SHA-256;
- software digest;
- `frozen_at`.

An official result cannot be compared if its `imported_at` is at or before `frozen_at`. The import/reveal time must be strictly later.

This makes official-score leakage a contract violation rather than a study convention.

## Ledger independence

The report layer never recomputes D or deductions. It references their immutable normalized ledger digests. This allows the #6 D-score branch and #11 deduction branch to be integrated later without duplicating arithmetic in report/UI code.

A resolved ledger cannot simultaneously claim unresolved references. A frozen analysis rejects a ledger from a different rulepack ID/digest.

## Official result versions

`OfficialScoreHistory` is append-only:

- first version is 1;
- corrected/withdrawn records append contiguous versions;
- result identity cannot change inside the history;
- import timestamps must increase;
- an old official result is never overwritten in place.

## Comparison

The existing Decimal-based `score_comparison.py` remains the arithmetic comparison primitive. `ScoreVerificationComparison` additionally binds:

- frozen-analysis digest;
- official-score-version digest;
- compare time;
- materiality threshold.

Non-finite score/threshold values are rejected.

The UI/report wording should remain neutral: `difference requiring review`, not `official score is wrong`.

## Discrepancy cases

Each material numeric difference can become a `DiscrepancyCase` containing:

- field/component;
- official and reconstructed Decimal values;
- exact delta/arithmetic impact;
- evidence IDs + immutable evidence digests;
- rule IDs + source locators;
- optional confidence milli-value;
- immutable comparison digest.

A case is `review_ready` only when both evidence and rule-source links exist.

## Qualified adjudication

The issue-defined decisions are represented exactly:

- `official_confirmed`
- `ai_supported`
- `both_partly_wrong`
- `unresolved`

A substantive decision requires a `review_ready` case. An incomplete case may only be marked `unresolved`.

Every adjudication records:

- reviewer ID;
- reviewer qualification reference;
- reason code(s);
- notes;
- time;
- case digest;
- explicit supersession.

Histories are append-only and cannot fork.

## Learning boundary

This branch does not automatically convert any official result or adjudication into training truth. Official results remain potential lower-weight silver labels; expert-adjudicated cases may become gold candidates only through the separate dataset-rights/governance workflow. Rights, athlete/event split rules and data-use permission must remain explicit.

## Remaining work before #18 closes

- integrate canonical D-score ledger (#6 branch) and deduction ledger (#11 branch) at a planned integration point;
- populate chronological element timeline and deduction-list report sections from those immutable ledgers;
- add exact canonical evidence deep links from #2/#3;
- render source quality, D reconstruction, accepted/unresolved deductions and discrepancy cases in the review workspace;
- build stable JSON report schema and HTML/PDF-ready view model after the integrated ledger fields are fixed;
- attach official result versions only after server-side freeze in the operational Django flow;
- add qualified reviewer permissions and audit persistence;
- add KIGA mapping/export fields without exposing unreviewed guesses as facts;
- validate representative competition/training reports with qualified WAG reviewers.

No PR, merge, Actions run or competition/live-judging workflow is created by this branch.
