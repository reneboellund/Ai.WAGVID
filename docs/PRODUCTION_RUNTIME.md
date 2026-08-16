# Production runtime foundation

## Immutable object access

The local object backend enforces the same immutable-original semantics required
from an S3-compatible backend. Repeating a write with identical size and SHA-256 is
idempotent; attempting to reuse an object key for different bytes fails. Inspection
and download hash the stored object as a stream.

Authenticated organization members request short-lived media grants. Grants bind
organization ID, object key, stored SHA-256, expiry and content disposition under an
HMAC-SHA256 signature. Delivery verifies both grant and object checksum before
streaming, uses `private, no-store`, `nosniff` and a checksum ETag, and records grant
creation in the audit log. Production must provide a distinct
`WAGVID_OBJECT_SIGNING_SECRET`; the development fallback is Django's secret key.

`MediaAsset` persists original filename, detected content type and byte length from
upload finalization. Migration `0011_mediaasset_source_metadata` is additive.

## Database

Set `WAGVID_DATABASE_URL` to a PostgreSQL URL. SQLite remains a developer/test fallback only.
Production mode (`WAGVID_DEBUG=0`) refuses the development secret and enables secure session/CSRF
cookies, HTTPS redirect and HSTS.

## Object storage boundary

`LocalObjectStore` is the development adapter and establishes required semantics for an S3/MinIO
adapter: safe keys, temporary writes, size and SHA-256 verification, then atomic publication. Video
bytes never enter PostgreSQL. Original retention remains separate from upload completion.

### Wasabi native integration

Issue #47 defines first-class Wasabi provisioning. `wagvid_app.wasabi` implements
the deterministic desired state and cost policy; `wagvid_app.wasabi_provider`
implements read-only S3 capability preflight and explicit approval-gated apply.
Boto3 is a lazy `wasabi` optional dependency and is never imported by the normal
web process unless a provider client is requested.

The default bounded layout uses sharded `originals` and `derivatives` pools plus
single `metadata`, `results` and optional `audit` buckets. It avoids per-athlete or
per-event bucket proliferation. Organization/content keys are assigned with
rendezvous hashing; routing maps must be versioned when pool membership changes.
Generated names are DNS-safe, contain a non-secret account fingerprint, and stay
within 63 characters. The configured Wasabi region selects its official endpoint;
unknown regions require an explicit endpoint override.

Preflight lists and inspects only desired buckets, redacts the access key to its
last four characters, and plans changes without mutation. Public buckets, region
conflicts, missing inspection permissions or changed plan digests block apply.
Apply accepts only the reviewed plan digest plus the phrase
`CREATE PRIVATE WASABI BUCKETS` in an unexpired admin approval. Runtime credentials
and provisioning credentials must be separate in production and secrets must live
outside the application database/logs.

Pay-Go configuration fixes the normal minimum storage duration at 90 days; RCS is
represented explicitly as 30 days. Each object must record `billable_until`.
Deletion previews calculate remaining GB-days and physical deletion must respect
evidence retention, consent, legal hold and object lock. Transient frames/cache do
not belong in this storage tier. Setup defaults to dry-run; unit tests use a fake S3
control client and never create cloud resources.

## Upload sessions

`UploadSession` persists capture ID, organization-scoped idempotency key, expected size/checksum,
received byte checkpoint, object key and state. Reusing an idempotency key with different content is
rejected. Checkpoints may only advance and never exceed the declared size.

The HTTP chunk/finish API is deliberately the next slice: it must authenticate the Android device,
lock the upload row, validate offsets, stream to object storage and create `MediaAsset` only after
final checksum verification.

## Analysis jobs and workers

Analysis state transitions are explicit and locked in a database transaction. A draft cannot jump
directly to completed; retryable failure can return to queued; completed jobs reach 100 percent.
`WorkerNode` records capability, heartbeat, state and active-job count. The first durable queue
adapter must lease jobs with expiry rather than relying on an in-process task.

## Readiness

`/health/` reports that the web process runs. `/ready/` separately probes database, object-storage
capacity and worker availability. A missing worker degrades readiness only when analysis jobs are
queued. The system-status page renders the same probes so machine and human status agree.

The next production increment must add S3/MinIO, worker queue and backup probes without changing the
probe/result contract.
