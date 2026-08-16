# KIGA competition exchange implementation

Ai.WAGVID now implements the `ai.wagvid.competition-video.v1` boundary as an idempotent dry-run and
commit workflow. KIGA remains the external competition-context system; Ai.WAGVID owns its UUIDs,
immutable analysis media and review history.

## Import behavior

The administrator uploads UTF-8 JSON and receives a no-write preview. Validation covers JSON
Schema, stable KIGA athlete mapping, active gymnast status, WAG/MAG apparatus compatibility and an
IANA timezone. Commit runs atomically and creates or updates:

- competition identity, dates, timezone, venue, geography, organizer, federation and rule profile;
- routine mapping, apparatus, round, rotation, start order, category and performance timestamp;
- external video references with SHA-256 and independent download/analysis/training/retention flags;
- an append-only official-result snapshot keyed by provider and result version.

Reimporting the same record is idempotent. Reusing an official result version with changed values is
rejected; a correction requires a new version. A withdrawn result remains in history but cannot
replace the routine's current official score. Media without both download and analysis permission
is catalogued as blocked and is not acquired.

The import does not download remote video. This avoids network cost and keeps source acquisition as
a separate worker operation with checksum, retention and authorization checks.

## Export behavior

The competition UI lists routines, official totals and external video readiness. Each ready routine
can be exported back through the same versioned schema. Export contains official result provenance,
rights, media hashes, reviewed AI link/difference where available, adjudication state and learning
eligibility. Unreviewed or training-disallowed material is explicitly exported as ineligible.

Every committed import and export is organization-scoped and creates an append-only audit event.
Names are display values; external athlete/event/routine/media IDs remain the integration keys.
