# S3-compatible provider framework

Ai.WAGVID uses one object-storage contract for Wasabi, Amazon S3, NetApp ONTAP
S3, VAST Data S3 and conditionally validated Object First Ootbi. Provider support
is capability-based: an S3-shaped endpoint is not assumed to implement AWS parity.

## Common safety contract

- TLS verification is mandatory outside explicit `dev`, `lab` and `test` profiles.
- Enterprise endpoints may use a custom-CA secret reference; `verify=False` is not
  a production shortcut.
- Access keys remain secret references. AWS may instead use workload identity and
  an optional STS role.
- Every stored object records provider connection, bucket, key, version, size and
  Ai.WAGVID SHA-256. ETag is never treated as the evidence checksum.
- Writes are immutable/idempotent by key + size + SHA-256. Large media uses resumable
  multipart sessions with list/complete/abort operations.
- Video delivery supports byte-range reads and bounded presigned GET when validated;
  a future proxy remains the fallback where presigning is unavailable.
- Provisioning and policy mutation are optional, dry-run first and bound to an exact
  plan digest. Existing-bucket mode blocks mutation.
- Logical roles (`originals`, `derivatives`, `metadata`, `results`, `audit`) may be
  assigned to different active providers.
- Cross-provider transfer is planned and idempotent, verifies SHA-256 at the target,
  records both locations and never deletes the source automatically.

The normal preflight is read-only. A real endpoint contract probe creates temporary
objects and therefore requires the explicit CLI flag:

```text
python manage.py validate_storage_provider CONNECTION_UUID \
  --bucket DEDICATED_TEST_BUCKET --prefix wagvid-contract-tests \
  --approve-test-objects
```

The probe validates PUT/HEAD/GET/Range, metadata, presign where available, multipart
create/upload/list/complete and cleanup. Run it only against a dedicated test prefix.
Immutable retention may prevent cleanup; that is reported as policy state, never
worked around.

## Wasabi

Use the official region endpoint, virtual-host addressing and secret-referenced
keys. The existing bounded multi-bucket plan and 90-day Pay-Go / 30-day RCS billing
policies remain active. See `config/wasabi-layout.yaml` and issue #47.

## Amazon S3

Preferred authentication is IAM role/workload identity; secret-referenced keys are
supported where necessary, and an optional role ARN invokes STS. Use the regional
endpoint and virtual-host addressing. Versioning, Object Lock and public-access
controls remain governance decisions and must match the selected profile. AWS
documents multipart restart/list/abort behavior and recommends multipart around
100 MB; Ai.WAGVID keeps its own SHA-256 because multipart ETags are not content hashes.

Official references:

- https://docs.aws.amazon.com/AmazonS3/latest/userguide/mpuoverview.html
- https://docs.aws.amazon.com/AmazonS3/latest/userguide/using-presigned-url.html
- https://docs.aws.amazon.com/AmazonS3/latest/userguide/object-lock.html

## NetApp ONTAP S3

Configure the S3 service/LIF, native S3 bucket, least-privilege S3 user, HTTPS
certificate/CA, endpoint reachability and explicit bucket mapping. Path-style is the
safe default. Capability probing is authoritative because ONTAP release and native
S3 versus S3 NAS affect the API surface. Current official documentation states that
versioning and Object Lock arrived in different ONTAP releases and that Object Lock
must be enabled when a native S3 bucket is created; the adapter therefore never
infers those capabilities from the provider name.

Official references:

- https://docs.netapp.com/us-en/ontap/s3-config/ontap-s3-supported-actions-reference.html
- https://docs.netapp.com/us-en/ontap/s3-config/ontap-s3-interoperability-concept.html
- https://docs.netapp.com/us-en/ontap/s3-config/create-bucket-task.html

## VAST Data S3

Configure a VAST S3 VIP endpoint, S3 key references, region hint, path/virtual style
as validated, and the enterprise CA. VAST documents Boto3 compatibility against a
subset of S3 operations and supports Range headers; exact versioning, Object Lock,
lifecycle, checksum and presign behavior remains probe-controlled. Provider/bucket/key
is canonical. Ai.WAGVID never infers a writable POSIX/NFS path or permits concurrent
cross-protocol mutation of the same managed object.

Official references:

- https://kb.vastdata.com/documentation/docs/overview-of-vast-cluster-s3-implementation-3
- https://kb.vastdata.com/documentation/docs/en/using-boto3-with-vast-cluster-s3-5
- https://kb.vastdata.com/documentation/docs/s3-object-storage-protocol

## Object First Ootbi (conditional)

Ootbi is existing-bucket-only. Configure its service-point HTTPS endpoint, the
documented `us-east-1` hint unless the appliance says otherwise, key references,
CA and explicit bucket mappings. Originals/evidence and audit/backup are candidates;
derivatives/cache are intentionally omitted by default. No appliance administration,
firmware action, lifecycle mutation, bucket provisioning or undocumented management
API is used.

Public Object First material is Veeam/backup-focused. Consequently the provider
remains `limited` until the safe contract probe succeeds on the exact appliance and
firmware. Marketing language is never accepted as an operation-level capability.

Official references:

- https://objectfirst.com/installation/ootbi-64-128-192-tb/
- https://objectfirst.com/ootbi/

## Remaining real-system validation

Ordinary CI uses fakes and never contacts a provider. Production certification still
requires opt-in contract runs for AWS and representative ONTAP/VAST/Ootbi systems,
throughput/Range measurements with large video, permission-negative tests, credential
rotation, orphan multipart inspection and restore rehearsal. Unsupported capabilities
must remain visible rather than being emulated as security guarantees.
