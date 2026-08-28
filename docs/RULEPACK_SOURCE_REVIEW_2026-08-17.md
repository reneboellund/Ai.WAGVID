# WAG rule source review — 2026-08-17

This note records the source-refresh investigation for release-target rulepack issue #76. It is not a qualified rules interpretation or an approval record.

## Verified official landing-page state

The current World Gymnastics Rules → Women's Artistic section was checked on 2026-08-17.

Observed current entries include:

- `1.1 - WAG COP 2025-2028` — listed 13 Mar 2026.
- `1.2 - Appendix to the Code of Points 2025-2028` — current live page metadata differs from older cached/search representations and therefore requires direct-document/version verification before registry mutation.
- `1.3 - WAG Specific Judges' Rules 2025-2028` — listed 27 Mar 2026.
- `WAG Help Desk 2nd Edition, 16th cycle` — the current live page exposes an August 2026 entry dated 10 Aug 2026; the repository currently records the April 2026 edition.

## Direct document verification completed so far

### WAG Code of Points
The existing direct official URL in the registry still resolves through the official World Gymnastics rules service. The file is large and still requires controlled download/hash verification before release freezing.

### Appendix
Direct official path resolved as:

`https://www.gymnastics.sport/publicdir/rules/files/en_1.2%20-%20Appendix%20to%20the%20Code%20of%20Points%202025-2028.pdf`

The source has shown inconsistent version/date metadata across current/cached representations during this review. Do not change registry publication/version metadata until the exact current bytes are downloaded, hashed and document-internal edition/date are confirmed from the same retained copy.

### WAG Specific Judges' Rules
Direct official path resolved as:

`https://www.gymnastics.sport/publicdir/rules/files/en_1.3%20-%20WAG%20Specific%20Judges%27%20Rules%202025-2028.pdf`

The official Women's Artistic rules page lists this entry at 27 Mar 2026. Controlled download/hash and qualified content review are still required.

### WAG Help Desk
The live Women's Artistic rules page currently lists a newer August 2026 Help Desk entry. The direct document fetch was not reliably resolved during this pass. Do not replace the April registry record by guessing a URL. Resolve the direct official document first, then add the newer source as a distinct record and supersede the historical April source as appropriate.

## Repository state that remains non-release-ready

`rules/rulepack-manifest.example.yaml` remains a draft example with no review and no manifest hash.

The current WAG source records in `rules/registry.yaml` are still `interpretation_status: unreviewed` and therefore cannot satisfy the release gate.

`src/ai_wagvid/rulepack_promotion.py` on `agent/apparatus-promotion-gates` now makes this state explicit: an approved rulepack requires approved/current referenced sources, source review metadata, frozen artifact hashes, rulepack review metadata and a manifest SHA-256.

## Required next source-review actions

1. Download the exact current WAG CoP, Appendix, Specific Judges' Rules and Help Desk from official World Gymnastics direct URLs into controlled review storage.
2. Compute SHA-256 for each retained review copy according to repository copyright/retention policy.
3. Confirm document-internal version/date/effective information against landing-page metadata.
4. Add the August 2026 Help Desk as a new source record rather than silently rewriting the April historical source.
5. Resolve Appendix live/cached metadata disagreement from the retained current bytes.
6. Perform qualified WAG rules review and record source review metadata.
7. Create frozen VT/UB/BB/FX deterministic rule artifacts/policies with source locators.
8. Create and hash the approved release-target rulepack manifest.

Until these steps are complete, rulepack readiness must remain blocked even if model benchmarks pass.
