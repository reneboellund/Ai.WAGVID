# KIGA export runtime boundary

Issue: #14. Coordinates with #12, #18 and the existing `docs/KIGA_INTEGRATION.md` / `docs/KIGA_VIDEO_SCORE_WORKFLOW.md`.

This branch implements the runtime integration boundary around the already-defined public analysis and competition schemas. It does not recalculate scores or replace `analysis-v1`.

## Schema negotiation

`PublicSchemaVersion(family, major)` and `negotiate_schema()` choose the highest exact major shared by producer and consumer for a requested family.

A breaking public contract therefore requires a new major (`analysis-v2`); it is never silently coerced into v1.

## Analysis payload ownership

The existing `analysis-v1` serializer/schema remains the semantic source of truth for accepted elements, score ledgers, deductions, evidence references and provenance.

The KIGA wrapper stores that public payload as canonical JSON + SHA-256 and adds:

- stable KIGA competition/routine/athlete/team mapping IDs;
- immutable analysis revision ID + digest;
- negotiated analysis schema;
- review/disclosure state;
- rulepack/model/software digests;
- explicit training eligibility;
- immutable export revision/supersession metadata.

It does not inspect tensors or internal model classes to produce scores.

## Review disclosure

Review state and disclosure are separate but constrained:

- `draft` -> `provisional`
- `needs-review` -> `provisional`
- `reviewed` -> `confirmed`

Both Python contracts and public JSON schemas enforce this. A low-confidence or unreviewed result may be shared as provisional analysis context, but cannot be labelled as a confirmed fact.

## Public payload safety

The integration boundary recursively rejects known raw/internal model fields such as:

- tensors;
- logits;
- embeddings/feature vectors;
- internal class indexes;
- raw model output.

The authoritative factory in `src/ai_wagvid/kiga_export.py` additionally rejects `NaN`/`Infinity` and other non-JSON values before canonical serialization.

Operational exporters should validate the nested analysis object against the negotiated existing `analysis-vN` schema before calling the KIGA factory.

## Immutable export revisions

`KigaAnalysisExportRevision` is content-addressed from stable mapping identity + immutable analysis revision digest + public payload/schema/review disclosure.

A re-analysis under a new model/rulepack creates a new analysis revision and therefore a new export ID. The history is append-only and the new revision must explicitly supersede the current one.

### Retry rule

If an `export_id` already exists, retry must return/reuse that persisted immutable export revision. It must not reconstruct the same content ID with a new creation timestamp and try to append it as a new revision.

This is the same idempotency principle used by other Ai.WAGVID immutable artifacts.

## Names are not keys

The export envelope uses stable external IDs as mappings. Human-readable names may be display metadata inside a versioned public analysis/report contract when appropriate, but they are never the primary key used to join KIGA and Ai.WAGVID records.

## Training rights

`TrainingEligibility` is explicit:

- `unknown`
- `denied`
- `allowed`

`allowed` requires a rights reference and immutable rights digest. It can never be inferred from the ability to view, download or analyse a video.

## Secure evidence deep links

`issue_evidence_grant()` creates a random token shown to the caller once. Persistence contains only SHA-256 of the token plus:

- evidence ID + evidence digest;
- organization ID;
- subject reference;
- explicit `view` / `download` permissions;
- issue/expiry time;
- optional revocation time.

Authorization checks token digest, expiry/revocation, organization, subject and permission. Raw video remains separately authorized from analysis access.

## Notifications

`KigaNotification` is a small event-compatible envelope containing export ID/digest, negotiated analysis schema and review/disclosure state. Notification identity/idempotency is derived from event type + destination + immutable export.

No raw video URL, official result internals or model tensors are placed in the notification.

## Batch JSON / Parquet

`canonical_batch_rows()` defines one shared row representation. Nested `analysis` stays canonical JSON inside `analysis_json`, so JSON and Parquet cannot develop different field semantics.

- `serialize_batch_json()` emits deterministic JSON bytes + batch manifest.
- `parquet_rows_and_manifest()` returns the identical canonical rows and a Parquet manifest without making PyArrow a mandatory core/web dependency.

A deployment/export worker can write those rows using a pinned Parquet library later; semantic equality is checked by the same member export digests.

## Public schemas added

- `schemas/kiga-analysis-export-v1.schema.json`
- `schemas/kiga-notification-v1.schema.json`

The existing schemas remain in force:

- `schemas/analysis-v1.schema.json`
- `schemas/competition-video-v1.schema.json`

## Remaining work before #14 closes

- wire the existing production `analysis-v1` exporter into `build_public_analysis_artifact()` with schema validation;
- add Django REST read/export endpoints and authenticated revision lookup;
- persist export histories, rights assertions and evidence grants in organization-scoped storage;
- implement actual short-lived evidence deep-link HTTP route;
- implement notification delivery/retry adapter to the chosen KIGA/event transport;
- add a pinned Parquet writer in the background export worker and verify byte/content interoperability;
- connect the #12 competition-batch freeze/reveal flow and #18 score-verification revision;
- return KIGA analysis/evidence links to originating routine records;
- define retention/revocation/audit for exported evidence grants;
- validate end-to-end with a real KIGA integration fixture.

No PR, merge, Actions run or public raw-media access is created by this branch.
