# Multi-provider S3 setup and validation

Ai.WAGVID treats object storage as a capability-driven provider boundary. Media-domain code resolves a logical role (`originals`, `derivatives`, `metadata`, `results`, `audit`, `backup`, `temp`) through `StorageProviderRegistry`; it does not select Wasabi, AWS, ONTAP, VAST or Ootbi directly.

## Shared safety rules

- Production endpoints use HTTPS. Enterprise/private endpoints use a validated custom CA rather than permanent certificate bypass.
- Access keys and secrets are resolved from secret storage, workload identity or environment injection at process start. They are never stored in object metadata, manifests, database plaintext or log output.
- Ai.WAGVID SHA-256 is authoritative. S3 ETag is not treated as a content hash.
- Versioning is not immutability. Immutable-original policy requires an actively verified Object Lock capability.
- Object Lock does not automatically imply legal-hold support.
- Logical roles may use different providers concurrently. This is the recommended layout when retained evidence and disposable cache/derivatives have different retention characteristics.

## Amazon S3

AWS S3 is the reference implementation of the common S3 contract. Configure an explicit region and prefer IAM role/instance/workload identity. Static credentials, when unavoidable, are secret references only.

Preflight checks mapped buckets, active versioning/Object Lock/lifecycle/public-access/encryption state, regional placement where the API is available, ACL/policy public status and safe account identity. Protected buckets are rejected when explicit public exposure is observed. Provisioning is modeled as a dry-run plan before any mutation.

Recommended production controls: private buckets, public-access block, role-separated layout, versioning where required, Object Lock only when retention policy calls for it, and lifecycle rules that cannot shorten evidence/legal retention.

## NetApp ONTAP S3

Data I/O uses native S3; cluster-admin credentials are not part of the object data path. Optional ONTAP REST management is a separate control-plane scope.

Setup checklist:

1. Verify a supported native ONTAP S3 service on the target SVM and record ONTAP release/platform.
2. Install/assign a valid HTTPS certificate for the S3 service LIF and distribute the enterprise CA chain to Ai.WAGVID workers.
3. Create or select role-separated buckets (`originals`, `derivatives`, `metadata`, `results`, optional `audit`/`backup`).
4. Create a least-privilege S3 user/group/key for Ai.WAGVID; keep cluster-admin credentials separate.
5. Configure endpoint, region hint/addressing mode and secret references.
6. Confirm network access from every local/cloud worker that may read the provider.
7. Run the explicit lab contract probe before relying on optional presign or provider-specific behaviors.
8. Confirm active versioning/Object Lock/lifecycle against both bucket state and the ONTAP release matrix. S3 NAS/multiprotocol mode is not treated as equivalent to native S3 governance.

Ai.WAGVID will not offer in-place conversion of an unlocked bucket into an Object Lock bucket. External protection such as SnapMirror S3 remains authoritative unless an explicit, approved management workflow is used.

## VAST Data S3

VAST is treated as an S3 subset, not as implicit AWS parity. Every mapped bucket must have an Ai.WAGVID contract-validation record before the provider is usable. Only capabilities proven by that validation and read-only preflight are advertised.

When a VAST namespace is multiprotocol, provider+bucket+key remains the canonical S3 identity. Do not infer a POSIX/NFS path or write the same Ai.WAGVID object concurrently through S3 and another protocol. Optional VMS diagnostics use separate read-only credentials and are not required for data I/O.

## Object First Ootbi

Ootbi support is deliberately conditional and existing-bucket-only in v1. Ai.WAGVID does not automate appliance creation, firmware, destructive administration, Zero Access bypass or undocumented management APIs.

Every mapped Ootbi bucket starts as `unvalidated`. It becomes usable only after the explicit contract probe proves HEAD bucket, PUT/HEAD/GET, metadata round-trip, Range GET, multipart complete and multipart abort. Optional failures produce `limited`; missing core operations produce `incompatible`.

Ootbi retention is authoritative. A retention-rejected delete is surfaced as a policy state rather than a transient retry error. Long-retained `originals`/evidence and `audit`/backup exports are natural candidates; `derivatives` and `temp` should normally route to another provider when appliance retention makes them unsuitable.

## Opt-in lab contract probe

The probe is never run by startup, health checks or CI. Use a dedicated test bucket/prefix and explicitly confirm the action. Credentials are read from environment variables; no secret is accepted as a command-line value.

Example:

```text
python manage.py validate_s3_provider \
  --provider-id lab-ontap \
  --provider-type ontap-s3 \
  --endpoint https://s3-lif.example.internal \
  --region eu-central-1 \
  --bucket wagvid-lab \
  --prefix ai-wagvid-capability-probe \
  --ca-bundle-path /etc/ssl/certs/company-ca.pem \
  --confirm "RUN SAFE S3 PROBE"
```

Set `WAGVID_S3_ACCESS_KEY_ID` and `WAGVID_S3_SECRET_ACCESS_KEY` only in the process environment/secret injector when explicit keys are required. For AWS, omit them to allow the SDK workload-identity/role chain. Add `--test-presign` only when presigned access is intended for that provider. Use `--no-delete` where appliance retention intentionally forbids cleanup; the remaining core results must then be interpreted with that retention policy.

Real-provider throughput/concurrency benchmarks and destructive cleanup are milestone-specific operations and are intentionally excluded from routine CI.
