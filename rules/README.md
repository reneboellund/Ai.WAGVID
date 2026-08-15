# Rules Directory

This directory will contain **machine-readable interpretations** of official WAG rules, not redistributed copies of FIG/World Gymnastics publications unless redistribution rights are explicitly confirmed.

## Initial target

`FIG-WAG-2025-2028@2026-05-25`

Official source registry must include the current WAG Code of Points, Appendix, WAG Specific Judges' Rules, WAG Help Desk and relevant Technical/competition regulations.

## Proposed structure

```text
rules/
  registry.yaml
  FIG-WAG-2025-2028/
    2026-05-25/
      manifest.yaml
      apparatus/
        vt.yaml
        ub.yaml
        bb.yaml
        fx.yaml
      elements/
        vt.yaml
        ub.yaml
        bb.yaml
        fx.yaml
      deductions/
        execution.yaml
        artistry.yaml
        neutral.yaml
      tests/
        fixtures.yaml
```

## Manifest requirements

- rulepack ID;
- discipline/cycle;
- release and effective date;
- source URLs/document names;
- content hashes/metadata where lawfully retained;
- interpretation revision;
- reviewers;
- status (`draft`, `reviewed`, `competition-approved-internal`);
- compatibility notes.

## Rule authoring policy

1. Each rule has a stable internal ID.
2. Each rule cites a source locator.
3. Machine interpretation is separated from source text.
4. Changes create a new version; they never rewrite historical truth.
5. Every deterministic scoring rule receives tests.
6. Apparatus-specific exceptions are explicit.
7. Unknown/ambiguous cases produce explicit states.
8. No athlete identity/history can be referenced by scoring rules.

## Copyright discipline

Prefer short identifiers, paraphrased machine interpretations, citations and test cases. Do not commit entire copyrighted FIG PDFs or extensive copied rule text without permission.
