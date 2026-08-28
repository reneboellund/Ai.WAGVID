# Deduction evidence and adjudication engine

Issue: #11

This branch implements the deterministic rule/evidence boundary for execution, artistry and neutral deduction assistance. It does **not** implement an opaque E-score model.

## Core invariant

A model/observer may create a `DeductionCandidate`. The pinned rule-pack may validate its criterion and allowed severities. Neither action changes the deduction ledger.

Only an explicit attributable `DeductionDecision` can create an accepted deduction entry.

High confidence therefore means `ready-for-confirmation`, never `automatically deducted`.

## Files

- `src/ai_wagvid/deductions.py` — candidate evaluation, rule applicability, append-only decisions and accepted deduction ledger.
- `src/ai_wagvid/deduction_policy.py` — strict declarative ontology loader.
- `schemas/deduction-policy-v1.schema.json` — rule/criterion/severity/camera requirement contract.
- `schemas/deduction-ledger-v1.schema.json` — stable human-adjudicated ledger output.
- `tests/test_deductions.py` — synthetic evidence/review regressions.
- `tests/test_deduction_policy_schema.py` — ontology and output schema gates.

Synthetic values are test data, not FIG deductions.

## Candidate evaluation

A rule may declare:

- execution, artistry or neutral channel;
- element/phase/routine/procedural scope;
- criterion ID;
- legal severity IDs and deduction units;
- required camera capabilities;
- minimum evidence-quality threshold;
- minimum model-confidence threshold;
- whether qualitative human judgement is mandatory;
- source-rule locator/reference.

Candidate confidence and evidence quality are represented as integer milli-units `[0, 1000]` to keep rule comparisons deterministic.

## Fail-closed camera/evidence behavior

A candidate becomes `unavailable` when required evidence or required camera capability is unavailable. Examples include a boundary rule without visible/calibrated floor boundary or a body-shape rule without a suitable view.

`unavailable` does not mean `no deduction`. It means the system cannot make that determination from the supplied evidence.

An unavailable proposal cannot be accepted until revised evidence produces a new usable proposal.

## Low-confidence behavior

- low model confidence -> `needs-review` / ambiguous applicability;
- insufficient-but-present evidence quality -> `needs-review` / conditional applicability;
- unresolved severity -> `needs-review`;
- no evidence/evidence quality -> `unavailable`.

The model-suggested severity remains visible for audit/review but is never counted by itself.

## Artistry

The architecture forbids a rule-pack from setting an artistry criterion to `human_judgement_required: false`.

This is enforced in both Python validation and the JSON schema. AI can surface criterion-specific observations/evidence, but it cannot collapse BB/FX artistry into one autonomous aesthetic score or final deduction decision.

## Human decisions

Decision actions are:

- `accept` — reviewer explicitly selects a legal severity;
- `change` — reviewer selects a different legal severity;
- `reject` — candidate is not accepted;
- `escalate` — remains unresolved for higher review.

Every decision records author, time, reason, immutable proposal digest and optional supersession. Decision histories are append-only and cannot fork.

## Accepted ledger

The normalized deduction ledger contains only human-accepted entries plus explicit lists of rejected, unresolved and escalated candidates. It exposes `accepted_deduction_units`, not a fabricated E-score.

A ledger with unresolved candidates can validly contain zero accepted units while still reporting `fully_resolved: false`. Report/UI code must not interpret that zero as “no deductions”.

## Evidence integration

The current branch references immutable evidence identifiers supplied by the evidence layer. At integration with the canonical #2/#3 branch, proposal persistence should bind the canonical evidence digest (source SHA, exact frame/ticks, calibration/sync provenance) as well as the human-friendly evidence ID. Derived/interpolated overlays remain non-original evidence.

## Remaining work before #11 closes

- encode reviewed 2025–2028 WAG deduction ontology from #1 with source locators;
- add apparatus-specific measurable observation adapters from #7–#10;
- integrate canonical evidence digests from #2/#3;
- connect the operational review inbox/#41 to proposal and decision history;
- add whole-routine criterion fixtures and qualified judge adjudication datasets;
- validate category/severity agreement against qualified reviewers;
- have #18 render the accepted/unresolved ledger without changing its arithmetic/status;
- define final E-score arithmetic only where the active competition/rule profile makes that deterministic.

No PR, merge, Actions run or claim of autonomous judging is created by this work.
