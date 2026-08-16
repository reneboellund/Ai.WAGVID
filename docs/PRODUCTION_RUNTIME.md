# Production runtime foundation

## Database

Set `WAGVID_DATABASE_URL` to a PostgreSQL URL. SQLite remains a developer/test fallback only.
Production mode (`WAGVID_DEBUG=0`) refuses the development secret and enables secure session/CSRF
cookies, HTTPS redirect and HSTS.

## Object storage boundary

`LocalObjectStore` is the development adapter and establishes required semantics for an S3/MinIO
adapter: safe keys, temporary writes, size and SHA-256 verification, then atomic publication. Video
bytes never enter PostgreSQL. Original retention remains separate from upload completion.

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
