# Operational product and UI blueprint

## Product definition

A usable Ai.WAGVID product is the complete operational loop, not merely a callable model:

`configure -> create/import identities -> capture/upload -> validate -> analyse -> review ->
approve -> export -> learn -> monitor -> recover`

Every screen must answer: current state, blocking reason, next valid action, responsible role,
history and recovery path.

## Roles

- **System administrator:** installation, organizations, storage, integrations, users, policies.
- **Organization administrator:** club scope, users, gymnasts, levels, retention and devices.
- **Operator:** capture sessions, device health, uploads and analysis jobs.
- **Coach:** gymnast library, training review, notes, comparisons and reports.
- **Reviewer/judge expert:** evidence review, rule interpretation and discrepancy adjudication.
- **Researcher/annotator:** datasets, labels, splits, model runs and benchmark exports.
- **Viewer:** read-only access explicitly granted to reports/video.
- **Service/device:** narrow machine identity; never inherits human admin rights.

Use deny-by-default organization scope. Sensitive actions require a reason and audit event.

## Global application shell

Persistent navigation:

- Overview
- Operate
- Gymnasts
- Videos
- Analyses
- Review inbox
- Competitions
- Training
- Devices
- Imports & exports
- Research
- System
- Administration

Global header includes organization/site, environment label, active rulepack, search, job activity,
alerts, help and signed-in identity. Dangerous environments and degraded operation must be visually
obvious.

## Complete flows

### First-run setup

1. Create system owner and organization.
2. Configure timezone, locale, storage and retention.
3. Test object storage and worker connectivity.
4. Install/activate a rulepack.
5. Create roles/users.
6. Add or import gymnasts and levels.
7. Pair Android device.
8. Run camera/upload/analysis smoke test.
9. Mark installation ready. Until then, dashboard shows a resumable checklist.

### Gymnast administration

Create, import, edit, merge duplicate and archive. Required identity: stable internal ID, display
name, level/trin and license number. Optional club/team, category, aliases and external KIGA ID.
Archiving never destroys linked videos. Merge requires preview and audit record.

### Training operation

Select gymnast -> activity/apparatus/target -> device -> Manual or Auto -> readiness check -> arm or
start -> record -> local finalization -> upload queue -> ingest validation -> analysis -> coach
review -> publish internal report. The UI must allow rapid “same gymnast/new attempt” and
“next gymnast” actions.

### Competition operation

Create/import competition -> map gymnasts -> verify start list -> attach/upload videos -> import
official scores -> analyse without leaking frozen official targets -> compare -> human adjudicate ->
approve -> export/KIGA. Competition and training records remain distinct.

### Upload/file ingest

Support Android queue, browser file upload, watched import folder and manifest import. Show checksum,
duplicate detection, codec/probe result, ownership, missing metadata and quarantine. Operators can
retry, relink metadata, supersede a bad upload or mark unusable; originals stay immutable.

### Analysis jobs

Create job with video, scope, apparatus, rulepack and model profile. States:
`draft, queued, blocked, running, needs-review, failed-retryable, failed-terminal, completed,
cancelled`. Show stage progress, worker/GPU, elapsed time, warnings, retry/cancel and logs safe for
operators. Re-analysis creates a new revision and never overwrites the previous result.

### Review inbox

Unified queue filtered by organization, gymnast, apparatus, reason, confidence, age and assignee.
Reasons include unknown element, low confidence, score discrepancy, poor video, rule mismatch and
failed quality gate. Review workspace preserves AI proposal, official result and human decision
separately. Bulk approval is forbidden for material score decisions.

### Import and export

Imports use preview -> validation -> mapping -> dry run -> commit -> result report. Accept CSV/JSON
for gymnasts, levels, competitions, start lists and official scores; accept media manifests without
embedding video. Row errors are downloadable and a failed atomic import changes nothing.

Exports support analysis JSON, coach PDF, evidence package, audit log, research annotations and KIGA
contract. Each export records filters, schema/version, requester, timestamp, checksums and redaction
profile. Large exports are background jobs with expiring authenticated download links.

### Administration

Manage organizations, users/roles, gymnasts/levels, rulepacks, model profiles, apparatus defaults,
devices, integrations, API credentials, retention, storage, workers, notification policies,
feature flags and audit log. Secrets can be replaced but never displayed after creation.

### System operations

Status dashboard covers web/database/object storage/queue/workers/GPU/device connectivity, storage
capacity, upload backlog, analysis backlog, oldest job, failure rate and last successful backup.
Actions: retry safe failures, pause/resume queue, drain worker, test storage, rotate device pairing,
run diagnostics and enter maintenance mode. Destructive actions require explicit scoped
confirmation and never rely on color alone.

## Status dashboard

Top-level health is `healthy, attention, degraded, unavailable, maintenance`. Cards link directly to
the filtered records causing the state. Required alerts:

- storage below thresholds;
- Android archive or upload queue growing;
- device offline while assigned;
- stuck upload/analysis/export;
- no compatible worker/model;
- rulepack missing or expired;
- database/object storage/queue unavailable;
- backup overdue or failed;
- repeated authentication/pairing failures;
- media quality prevents requested analysis.

Acknowledging an alert does not resolve it. Resolution is derived from the underlying condition.

## Usability rules

- Show only valid next actions for the current state.
- Preserve filters, pagination and return location.
- Every mutation has success/failure feedback and an audit ID.
- Long actions become jobs; never leave a spinner with no progress.
- Empty states explain how to create/import the first record.
- Errors include recovery action and whether retry is safe.
- Forms support keyboard use, accessible labels and unsaved-change protection.
- Dates show local timezone plus exact timestamp on demand.
- Search by gymnast name/license, competition, capture ID, video hash and job ID.
- Mobile WebUI is suitable for monitoring and simple approval; frame-accurate review targets
  desktop/tablet landscape.
- No silent fallback of rulepack, model, organization or gymnast.

## Operational non-functional requirements

- On-prem operation without internet.
- Idempotency keys for capture commands, imports, jobs and exports.
- Append-only audit history for identity merges, reviews, config and permissions.
- Database backup plus object-store inventory; restore rehearsal is a release gate.
- Structured logs with correlation IDs; no raw video or secrets in logs.
- Health/readiness endpoints distinguish web availability from worker readiness.
- Graceful degradation: capture/archive works while backend is offline; review remains available
  when GPU workers are down.
- Pagination and background jobs from the first release; video libraries will grow quickly.

## Delivery slices

1. **Product shell:** Django project, PostgreSQL models, auth/roles, organization scope, navigation,
   dashboard skeleton and audit events.
2. **Master data:** gymnasts, levels, devices and CRUD/import preview.
3. **Operate:** device cards, session setup, capture commands, upload and ingest status.
4. **Analysis:** job orchestration, progress, failure recovery and revision history.
5. **Review:** inbox, evidence workspace and adjudication.
6. **Exchange:** imports, exports, KIGA mappings and reports.
7. **Operations:** health, alerts, backup/restore, retention and diagnostics.
