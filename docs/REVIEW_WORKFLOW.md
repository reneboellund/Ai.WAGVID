# Review inbox and evidence workspace semantics

Issue: #41. Coordinates with #3, #11, #18 and #16.

This branch defines review semantics before wiring the Django/HTMX UI. The UI may render these records, but it must not merge AI proposals, deterministic rule results, official results or human decisions into one mutable object.

## Review item

A `ReviewItem` is bound to one immutable analysis revision and contains typed references for:

- evidence;
- optional AI proposal;
- optional deterministic rule result;
- optional official result;
- rule sources;
- assignee;
- reason/materiality/confidence.

Reasons include:

- unknown element;
- low confidence;
- poor quality;
- rule mismatch;
- score discrepancy;
- deduction review;
- OOD/unavailable;
- human-requested review.

`score-discrepancy` requires both deterministic-result and official-result artifacts. `rule-mismatch` requires rule-source evidence.

Public schema: `schemas/review-item-v1.schema.json`.

## Artifact separation

Typed artifact kinds are:

- `ai-proposal`
- `deterministic-rule-result`
- `official-result`
- `evidence`
- `rule-source`
- `human-revision`

This is the review-workspace implementation of the evidence-first UI invariant: source/evidence and different interpretation layers remain inspectable rather than being flattened into one score cell.

## Human decisions

Actions:

- `accept`
- `reject`
- `revise`
- `escalate`

Every decision records reviewer, reason code, notes and immutable review-item digest. `revise` additionally requires a new `human-revision` artifact rather than mutating the AI/deterministic artifact.

Material resolution is qualification-gated in the core. The operational role mapping may permit an operator to create/escalate an item without granting that operator qualified accept/reject/revise authority; that distinction belongs in Django permission wiring.

Public schema: `schemas/review-decision-v1.schema.json`.

## Append-only revisions

`ReviewDecisionLedger` is append-only and non-forking:

- first decision has no supersedes pointer;
- a changed decision explicitly supersedes the current decision;
- timestamps increase;
- decision IDs are immutable;
- the decision remains bound to the exact original review-item digest.

A later qualified review therefore creates a new decision revision. It never overwrites the historical human choice.

## No material bulk approval

`validate_bulk_action()` rejects bulk accept/reject/revise whenever the set contains a material item. Generic bulk revise is rejected entirely because every revision requires an item-specific replacement artifact.

Bulk escalation/administrative operations may be handled separately, but material scoring/identity decisions always retain item-level evidence and attribution.

## Inbox filters

`ReviewFilter` supports deterministic filtering by:

- reason;
- apparatus;
- assignee or unassigned;
- maximum confidence;
- minimum age;
- material-only.

The operational UI can add search/text presentation, but these core dimensions map directly to #41 acceptance requirements.

## Evidence/adjudication export

`build_review_evidence_export()` creates a digest-only evidence package bound to:

- review-item digest;
- all human-decision digests;
- evidence digests;
- rule-source digests;
- immutable analysis revision digest.

Raw media is not embedded by this export. Authorized evidence deep links/grants remain a separate #16/#14 access decision.

## Integration with score verification

For #18 discrepancy cases:

- frozen AI/deterministic artifacts remain immutable;
- official result is a separate artifact/version;
- synchronized evidence refs are typed as evidence;
- rule source is typed separately;
- the qualified adjudication result becomes a human decision/revision rather than a mutation of either source.

The existing exact #18 adjudication outcome enum remains the domain truth for official-vs-AI discrepancy classification. This review module provides the generic append-only workspace shell around such decisions.

## Remaining work before #41 closes

- persist review items, assignments and decision revisions in the organization-scoped product shell;
- map qualified reviewer/judge roles and operator escalation permissions explicitly;
- build Django/HTMX inbox with reason/confidence/age/apparatus/assignee filters;
- build evidence player/timeline shell using #3 canonical evidence/timestamps;
- render AI proposal, deterministic result, official result and human decision in separate panels;
- connect #11 deduction decisions and #18 discrepancy adjudication to review-item factories;
- add analysis revision comparison UI;
- implement secure evidence/adjudication download using #16/#14 grant rules;
- keyboard/accessibility tests and empty/loading/error/permission states;
- validate workflow burden with qualified reviewers.

No PR, merge, GitHub Actions run or bulk material approval path is created by this branch.
