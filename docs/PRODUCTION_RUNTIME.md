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

The administration page at `/system/storage/` now persists an organization-scoped
connection profile and its versioned desired bucket routes. It stores credential
references, never credential values. The built-in resolver deliberately supports
only explicit `env:NAME` references; vault/secret-manager schemes require a separate
adapter. A read-only preflight resolves credentials only for the provider call and
persists a sanitized result, plan digest and audit event. Disconnect marks the
connection inactive but never deletes remote buckets or local object records.

`StoredObjectRecord` is the durable control-plane ledger for bucket, key, version,
checksum, byte size, upload time, `billable_until`, retention and legal hold. Deletion
is a two-stage operation: an administrator first quarantines an eligible record, then
a future worker may physically delete it no earlier than the retention, billable and
quarantine deadlines. This milestone does not yet expose cloud apply or physical
deletion through the WebUI, so a saved plan or successful preflight cannot mutate
Wasabi resources.

The S3 data-plane adapter stages and hashes incoming bytes before any provider
mutation. Small immutable objects use a verified single request; objects at or above
100 MiB use checksummed multipart upload with 16 MiB parts and automatic abort on a
failed part. Every write carries SHA-256 metadata and server-side AES-256 encryption,
returns the provider version ID, and is registered in the ledger with its selected
bucket. Reusing a key is allowed only when size and SHA-256 are identical. Downloads
can be streamed by exact version or exposed through a provider-signed URL of at most
one hour.

Cloud apply is available only to storage administrators and requires the exact typed
phrase `CREATE PRIVATE WASABI BUCKETS`. Apply always runs a fresh read-only preflight,
binds the short-lived approval to that plan digest, and marks routes ready only after
all provider actions complete. A partial provider failure is recorded as a sanitized
audit event and leaves the connection degraded for reconciliation.

Physical removal is also version-specific. A worker first claims only quarantined,
due, non-held objects. Provider failure returns the item to quarantine for retry;
success marks the ledger record deleted and appends an audit event. Neither path
stores provider exception text or credentials. Provider calls still require the
optional Boto3 dependency and runtime secret references; tests use contract fakes.

### Multi-provider S3 framework

Issues #60-#64 generalize the same data plane to Wasabi, Amazon S3, NetApp ONTAP
S3, VAST Data and conditionally validated Object First Ootbi. The connection model
persists provider, TLS/custom-CA, addressing, authentication, governance, explicit
bucket mappings and a verified capability snapshot. `StorageRoleAssignment` selects
the provider independently for each logical data role. `StorageTransfer` supplies an
idempotent, audited, checksum-verified cross-provider copy workflow without implicit
source deletion. Setup and validation guidance lives in `docs/S3_PROVIDERS.md`.

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
