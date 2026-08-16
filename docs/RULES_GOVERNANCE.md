# Rule-source governance

## Purpose

Ai.WAGVID must reproduce historical analyses and explain every scoring interpretation. A rule
update therefore creates a new immutable rule-pack version; it never edits the meaning of a pack
already referenced by an analysis.

## Source states

- `discovered`: listed by World Gymnastics, but direct artifact and metadata are not fully verified.
- `current`: artifact, edition, dates, and URL have been verified by a reviewer.
- `superseded`: retained for historical analyses and linked to its replacement.
- `withdrawn`: publisher withdrew the source; it remains addressable for audit history.

Interpretation review is tracked separately as `unreviewed`, `draft`, `reviewed`, or `approved`.
Only approved interpretations may enter a production scoring rule pack.

## Stable citation format

Rule interpretations cite a registry source ID plus a locator. Prefer the document's semantic
structure over page number alone:

`wag-cop-2025-2028-2026-03#section:8.3/page:44/table:CR`

Locators are stored as opaque strings in downstream contracts so a future resolver can support
articles, sections, apparatus, tables, figures, and pages without changing the score engine.

## Update procedure

1. Check the official World Gymnastics rules index and record the check date.
2. Register a new publication as `discovered`; never reuse an existing source ID.
3. Verify title, discipline, language, publication/effective dates, and direct URL.
4. If retention is lawful, store the copy outside the public repository and record SHA-256.
5. Link both directions using `supersedes` and `superseded_by`.
6. Diff and interpret changes as reviewable machine-rule changes.
7. Obtain named review and record the decision reference.
8. Publish a new rule-pack version and regression-test known routines.
9. Re-analysis creates a new analysis version; old output remains pinned and unchanged.

## Copyright and retention

This public repository stores metadata, original structured interpretations, short citations, and
source links. It does not store full copyrighted rule publications unless redistribution permission
is documented. Licensed/private copies belong in controlled object storage; their hashes may be
recorded here to make the reviewed artifact unambiguous.

## Required automation

CI must run `wagvid-rules validate rules/registry.yaml` and `pytest`. A later scheduled checker may
flag changed URLs or bytes, but it must never automatically promote a source or interpretation.

