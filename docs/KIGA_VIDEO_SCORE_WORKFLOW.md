# KIGA competition video and official-score workflow

## Product outcome

KIGA is the competition and athlete context system. Ai.WAGVID is the evidence, reconstruction,
and review system. A user should be able to open one KIGA competition/routine, see its authorised
videos and official result, request an Ai.WAGVID analysis, and return to the same record to inspect
the evidence-linked comparison.

The exchange contract is `schemas/competition-video-v1.schema.json`. Names are display data;
stable external IDs are the integration keys.

## Required competition context

Store competition ID/name, start/end date, timezone, venue, geography, organiser/federation,
level, category and applicable rule profile. Each routine also stores athlete/team external IDs,
apparatus, round, rotation/start order and exact performance time. This makes videos searchable by
competition and prevents a file name from becoming the only source of context.

## Media acquisition

KIGA provides one or more short-lived, authorised download URIs. Ai.WAGVID downloads the original
bytes, verifies SHA-256, records capture metadata and creates its own immutable analysis-media
record. URI access, analysis, retention and model-training rights are separate flags. Footage of
minors is never assumed to be training-authorised merely because it can be viewed.

Future ingestion may be event-driven, but the v1 contract is also usable for explicit batch pulls.
Re-importing identical bytes is idempotent by media hash; changed bytes create a new media version.

## Independent analysis before comparison

To avoid official-score leakage, the preferred evaluation flow is:

1. import competition/routine metadata and video;
2. hide official scores from model features and freeze the AI interpretation;
3. record `ai_frozen_at` and model/rule-pack provenance;
4. reveal/import the versioned official score;
5. calculate D/E/neutral/final differences;
6. list element, connection, deduction and evidence-level explanations;
7. route material or low-confidence differences to qualified review.

The official result is a valuable initial **silver label**, not unquestioned ground truth. Training
directly on every official final score would reproduce judging noise and would not teach the model
which underlying element or deduction caused the number.

## Human adjudication

The reviewer sees synchronized evidence, the frozen AI ledger and official score components. Each
material difference receives reason codes, notes and one outcome:

- `official_confirmed`: official interpretation is supported;
- `ai_supported`: evidence supports the AI interpretation;
- `both_partly_wrong`: corrected interpretation differs from both;
- `unresolved`: evidence or rule interpretation is insufficient.

Only expert-adjudicated cases become gold-quality learning labels. Unreviewed official results may
be used as lower-weight silver labels only when rights allow and evaluation splits prevent leakage.
The model should learn element/observation/deduction targets as well as score totals.

## Review and future appeal support

Initial scope is post-routine/post-event review. The system produces a judge-readable discrepancy
package containing exact frames/clips, accepted facts, rule references, arithmetic, confidence and
review history. A future competition workflow may attach an `appeal_reference`, but submission,
deadlines and authority remain federation/event responsibilities and require a separately approved
live operational design.

## Learning controls

- Split datasets by athlete, competition and source video, not random frames.
- Never expose official scores to inference before the AI freeze used for evaluation.
- Track label tier: unreviewed official, expert adjudicated or excluded.
- Exclude withdrawn/corrected results until the selected result version is explicit.
- Re-analysis creates a new immutable analysis version.
- Do not use athlete identity, club, nationality, reputation or ranking as scoring features.
- Preserve disagreement cases; they are high-value review data, not examples to force-fit.

