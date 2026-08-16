# Android upload and worker contract

This milestone supplies the backend contract for a thin Android capture client. The phone retains its original file and uploads it in resumable chunks; the backend verifies byte count and SHA-256 before exposing a stored `MediaAsset`.

## Authentication

Each request supplies `X-WAGVID-Device: <device_key>` and `Authorization: Bearer <token>`. Only active devices with a matching hashed token are accepted. Plaintext device tokens are never stored.

## Upload sequence

1. `POST /api/device/uploads/open/` with capture UUID, gymnast UUID, recording kind, capture timestamp, filename, byte count, SHA-256 and an idempotency key.
2. `PUT /api/device/uploads/{id}/chunk/` with raw bytes and `X-Upload-Offset`. The server only accepts the exact next offset.
3. Repeat step 2 after interruptions. Reopening with the same idempotency key returns the existing offset.
4. `POST /api/device/uploads/{id}/finalize/`. The server verifies size and checksum, atomically promotes the partial file and creates one media record.

Default limits are 8 MiB per chunk and 20 GiB per capture. Configure `WAGVID_MAX_CHUNK_BYTES`, `WAGVID_MAX_UPLOAD_BYTES` and `WAGVID_OBJECT_ROOT` for the deployment.

## Analysis workers

Workers lease the oldest eligible queued or retryable analysis job. A lease records owner, expiry and attempt count. Only the owning worker may extend it. This prevents two perception pipelines from processing the same recording concurrently while allowing expired work to be recovered.

## Master data

The web UI supports UTF-8 gymnast CSV files (maximum 2 MiB) using the columns `name`, `license_number`, `level` and optional `kiga_id`. Preview validates every row before an atomic commit. Completed imports create an exchange-history record and append-only audit event. A UTF-8 CSV export is available to every authenticated organisation member.
