# Deterministic D-score engine

Issue: #6

This branch introduces the apparatus-independent D-score construction core without embedding any FIG/WAG scoring values in Python.

## Boundary

The engine starts **after** perception, element interpretation and human/review policy have produced accepted gymnastics facts. It never:

- reads video or model tensors;
- calls an ML model;
- reads athlete identity, club, nationality, ranking or historical performance;
- reads an official score before or during D reconstruction;
- invents an element when identity remains unresolved;
- downloads or parses copyrighted rule documents at runtime.

A pinned rule-pack supplies a declarative D-score policy. The policy contains only reviewed data: element values and repetition keys, counting constraints, composition requirements, connection rules and explicit adjustment rules.

## Files

- `src/ai_wagvid/dscore.py` — pure deterministic evaluator and normalized ledger.
- `src/ai_wagvid/dscore_policy.py` — strict JSON/YAML mapping loader; unknown fields and type coercion are rejected.
- `schemas/dscore-policy-v1.schema.json` — public declarative policy schema.
- `schemas/dscore-ledger-v1.schema.json` — stable normalized output schema.
- `tests/test_dscore.py` — synthetic rule/value fixtures exercising engine semantics.
- `tests/test_dscore_policy.py` and `tests/test_dscore_policy_strictness.py` — policy/schema safety.
- `tests/test_dscore_ledger_schema.py` — resolved, ambiguous and fail-closed ledger schema validation.

The test values are intentionally synthetic and are **not** FIG scoring content.

## Exact arithmetic

Rule-pack scoring values are integer `value_units` and the policy declares `units_per_point`. The engine performs all arithmetic in integers. A presentation string is generated only after the total is known.

This avoids binary floating-point differences in audit ledgers and makes normalized JSON byte-stable for the same facts + policy.

## Counting

The v1 core supports:

- a maximum number of counted elements;
- a configurable repetition limit per repetition key;
- group minimum/maximum counting quotas;
- deterministic maximum-value selection under those constraints;
- explicit reason codes for every non-counted element;
- a warning when a configured minimum quota cannot be met by the accepted facts.

Repetition eligibility is chronological in v1: the first accepted occurrences up to `repetition_limit_per_key` remain eligible. A future rule-pack that requires a fundamentally different repetition algorithm must add a reviewed policy/plugin capability rather than silently changing this semantic.

## Composition requirements

Composition is a separate ledger channel. A requirement declares:

- stable requirement ID;
- matching element group;
- minimum count;
- whether the condition uses all performed facts or only counted elements;
- award units;
- source-rule locator/reference.

Satisfied and unsatisfied requirements are both serialized.

## Connections / series

Connection points are never inferred merely because two elements are adjacent. Input includes an accepted `AcceptedConnectionFact` with continuity evidence. The rule-pack then maps the accepted pair to a connection rule.

- interrupted connection → zero award with explicit status;
- adjacency-required rule with non-adjacent facts → zero award;
- no matching rule → zero award;
- overlapping equal-priority rules → evaluation error so the rule-pack must be corrected instead of making an arbitrary choice.

## Ambiguity

An accepted element fact may intentionally retain multiple candidate element IDs.

The v1 engine evaluates the bounded Cartesian set of rule outcomes. It can therefore distinguish:

1. **identity ambiguous, score resolved** — different element identities lead to the same D total;
2. **score ambiguous** — candidate identities lead to different totals;
3. **ambiguity too large** — configured outcome bound is exceeded, returning a fail-closed ledger with an explicit blocker and no guessed total.

The ledger exposes per-alternative possible totals.

## Provenance and determinism

Every ledger records:

- rulepack ID;
- rulepack digest;
- deterministic D-score policy digest;
- apparatus;
- exact integer arithmetic;
- every resolved candidate outcome;
- counted/non-counted reason;
- composition and connection ledgers;
- accepted adjustment facts;
- ambiguity impacts;
- warnings/blockers.

`normalized_json()` sorts keys and normalizes ordering. Same accepted facts + same pinned policy produce byte-equivalent output and the same SHA-256 ledger digest, regardless of caller input ordering.

## Production rule-pack gate

The core permits synthetic/draft policies without source locators so unit tests and research fixtures remain possible. A production-approved WAG rule-pack must be governed by #1 and should require:

- approved/current official source registry entries;
- immutable artifact SHA-256 values;
- source locator on every scoring rule represented in the policy;
- expert review/sign-off;
- apparatus-specific known-routine vectors;
- regression vectors for every confirmed scoring bug.

The engine does not declare a rule-pack authoritative by itself.

## Remaining work before #6 can close

The generic deterministic core is implemented, but #6 should remain open until:

- reviewed 2025–2028 WAG apparatus D policies are encoded from the authoritative #1 registry;
- apparatus-specific semantics that exceed the v1 declarative primitives are identified and implemented behind a reviewed extension boundary;
- known-routine positive/negative/boundary/repetition/connection fixtures are reviewed by a qualified WAG rules expert;
- the accepted-element review flow feeds these facts into the engine;
- #18 report/UI renders the ledger and ambiguity without changing the arithmetic;
- re-analysis under a new rulepack is proven to create a new immutable ledger rather than mutating historical results.

No PR, merge, GitHub Actions run or competition-grade claim is created by this branch.
