# Versioned FIG Rule Engine

## Goal

Rules change. Ai.WAGVID must therefore treat a rule set as data + tested logic with provenance, not as hard-coded assumptions scattered through model code.

## Rule-pack identity

Suggested identifier:

`FIG-WAG-2025-2028@2026-05-25`

A pack contains:
- discipline: WAG;
- cycle;
- release/effective dates;
- official source references;
- supersedes/superseded-by metadata;
- machine-readable element catalogue;
- apparatus configuration;
- composition rules;
- connection/series rules;
- repetition/counting rules;
- deduction definitions;
- neutral/procedural rules;
- test vectors;
- interpretation notes with provenance.

## Source provenance

Each machine rule must identify the official source document and human-verifiable reference location. Do not copy an entire copyrighted publication into the repository merely for convenience.

Example conceptual record:

```yaml
rule_id: wag.fx.example-rule
rulepack: FIG-WAG-2025-2028@2026-05-25
source:
  document: WAG Code of Points 2025-2028
  edition_date: 2026-03-13
  section: "machine-verifiable locator"
effective_from: 2026-03-13
status: active
interpretation:
  type: deterministic
```

## Rule categories

### Element catalogue
- canonical internal element ID;
- official name/reference locator;
- apparatus;
- difficulty value/category;
- family/group;
- recognition features useful to the vision layer;
- predecessor/successor aliases when rules change;
- validity/effective interval.

### Routine counting
Rules selecting which accepted elements contribute to D-score.

### Composition requirements
Declarative conditions evaluated against accepted routine facts.

### Connections / series
A graph/rule expression over temporally adjacent accepted elements and intervening events.

### Execution deduction definitions
The rule engine does not visually invent deductions. It validates whether an accepted observation maps to an available rule option and supplies the legal consequence.

### Neutral / procedural rules
Contextual penalties that may be supported by timing, boundary sensors/video or operator input.

## Rule expression system

Prefer a restricted declarative DSL over arbitrary Python for most rules. Requirements:
- deterministic;
- side-effect free;
- human reviewable;
- JSON/YAML serializable;
- versioned;
- unit-testable;
- supports temporal relationships;
- supports apparatus-specific predicates;
- cannot access athlete identity, nationality or historical performance.

Complex exceptional logic may use reviewed plug-ins behind a stable interface.

## Rule resolution

Every analysis session pins one rule-pack version at creation. A later rule-pack update does not silently change historical results.

Re-analysis is explicit:

`analysis A / rulepack X` remains immutable.

`analysis B / rulepack Y` can be generated and compared.

## Ambiguity

If observations do not uniquely determine a rule outcome, the engine returns alternatives and required evidence rather than making an arbitrary choice.

Example:

```json
{
  "status": "AMBIGUOUS",
  "outcomes": [
    {"candidate": "A", "d_delta": 0.0},
    {"candidate": "B", "d_delta": 0.1}
  ],
  "missing_evidence": ["required visual distinction"]
}
```

## Test strategy

Each rule requires, where applicable:
- positive test;
- negative test;
- boundary test;
- repeated-element test;
- ordering test;
- historical regression fixture when a bug is found.

Ruleset release gates:
1. schema validation;
2. provenance completeness;
3. deterministic unit tests;
4. known-routine fixture tests;
5. independent review by a qualified WAG rules expert before competition use.

## Update workflow

1. detect official publication/update;
2. archive metadata/hash/link internally;
3. perform human diff review;
4. create new rule-pack version;
5. update machine rules;
6. add/update test vectors;
7. rerun benchmark routines;
8. quantify changed outputs;
9. review and sign release;
10. make new pack selectable — never silently replace historical pack.

## FIG Scoring Assistance boundary

World Gymnastics' current 2025–2028 Appendix includes a Scoring Assistance System framework. Ai.WAGVID should therefore distinguish **judging assistance** from claiming autonomous replacement of official judging. Any future competition deployment must follow the rules and approvals applicable to that event and federation.
