# Backup, recovery and upgrade safety model

Ai.WAGVID treats application code as replaceable and production data as durable state. The portable recovery baseline is deliberately independent of NetApp, Wasabi, AWS S3 or any other storage vendor.

## Recovery artifacts

A verified system backup consists of a versioned `ai.wagvid.system-backup.v1` manifest plus referenced artifacts. The manifest records the exact application Git SHA, migration heads, PostgreSQL version, configuration bundle, recoverable object inventory, rule/model artifact digests and secret references. Plaintext operational secrets do not belong in the ordinary backup set.

Large canonical video objects normally remain on their configured object/file providers. `ai.wagvid.system-object-inventory.v1` records their provider, bucket/filesystem location, version identifier, size, SHA-256 and retention/protection state so a restored control plane can prove that its database still points to the expected evidence.

## PostgreSQL baseline

Logical `pg_dump` plus `pg_restore` is the provider-neutral portability floor. Command planning keeps passwords out of process arguments; credentials must be injected through the deployment secret mechanism (for example a protected pgpass/service configuration or environment supplied only to the subprocess).

A backup does **not** become `verified` merely because `pg_dump` returned successfully. Verification requires the database archive and portable artifacts to match their SHA-256 values, `pg_restore --list` to prove that the archive is readable and non-empty, manifest/application provenance to be present and the object inventory to be schema-valid. Deployments can additionally sample canonical objects through their configured providers before promotion to `verified`.

Detailed verification evidence belongs in the append-only backup catalog event. The published backup manifest remains schema-valid and, after its final `verified` transition, is immutable.

Provider-native snapshots, PostgreSQL PITR and NetApp SnapCenter may accelerate protection or recovery, but cannot be the only recovery method.

## Backup state and retention

Backups use explicit state transitions: `created -> verifying -> verified`, with `failed` available before verification completes and `verified -> expired` only through retention policy. State events are stored in a hash-chained append-only journal so silent editing of historical backup state is detectable.

Retention selection is deterministic and may preserve daily, weekly and monthly generations independently of the destination provider. Expiration means the portable backup generation is eligible for policy cleanup; it does not shorten an external provider's retention, Object Lock, legal hold or appliance policy.

## Restore safety

Restore defaults to a new/staging target. Paths referenced by a backup manifest are resolved below the selected backup root and path traversal is rejected. Artifacts are SHA-256 verified before use. A database restore does not overwrite media storage. Before recovered services accept writes, storage providers and the object inventory must be reconciled and missing secrets rebound.

Production promotion is a separate gate after restore. It requires approved restore preflight, completed database restore, secret rebinding, object-inventory verification, exact migration state and successful system checks. A staging recovery remains write-isolated by default. Production promotion additionally requires the explicit confirmation phrase `PROMOTE RECOVERED SYSTEM TO PRODUCTION`.

## Upgrade safety

Every release must eventually publish `ai.wagvid.release-manifest.v1`. It declares supported PostgreSQL versions, target Django migration heads, direct/intermediate upgrade paths, configuration/storage/rule/model schema versions, rollback semantics and compatible Android protocol range.

An upgrade is blocked when there is no declared path, PostgreSQL is incompatible, migration state is unknown, required providers are unavailable or a verified pre-upgrade backup is missing. Environment preflight also checks database reachability, a clean migration graph, storage-routing consistency, disk headroom, required secret references and worker/device compatibility before maintenance begins.

Maintenance is a transaction, not an ad-hoc restart. New mutation work is stopped, uploads/analysis leases/recording devices are drained, the verified pre-upgrade backup is bound to the transaction, the target is applied, post-upgrade checks run and write traffic is explicitly reopened only after verification passes. Read-only access may remain available when the deployment adapter supports it.

Upgrade events use a hash-chained append-only journal with a fixed source version, target version, backup ID and initiator. Valid phases are deliberately constrained (`planned`, `maintenance`, `draining`, `backup-verified`, `applying`, `verifying`, `ready-to-reopen`, `completed`) with failures leading only to a staged rollback path.

Application upgrades never reset the database, replace customer configuration with packaged defaults or move/delete canonical media as an implicit deployment side effect. Configuration migration adds new defaults recursively while preserving installation-specific and unknown/future keys.

Destructive schema changes should use an expand/backfill/switch/contract lifecycle over releases. Upgrade plans that drop/recreate the production database, truncate data, remove canonical media, reset audit history or remove a schema representation before its deprecation window are rejected by policy. Media movement requires a separate migration plan.

## Rollback

Code-only rollback is allowed only when the target release declares compatible rollback and the database has not changed incompatibly. Database-affecting rollback defaults to restoring the verified pre-upgrade database into a staging/new target and validating it against the previous application release instead of trusting reverse migrations blindly.

Canonical media remains in place during rollback. The recovered control plane rebinds the unchanged providers and verifies object inventory/provenance before any cutback. A rollback plan never uses media deletion or implicit relocation as part of an application rollback.

## Post-upgrade verification

Before reopening writes, the transaction verifies exact migration heads, Django/system checks, database integrity, storage-provider health, worker compatibility, rule/model registry loading, authentication and readability of the backup catalog. A sampled media-reference check is recommended and becomes a blocker when it is run and fails.

## Provider relationship

NetApp, Wasabi, AWS S3, VAST, Ootbi and future providers remain peers. Provider-specific snapshot/replication/backup capabilities appear as protection references and optional recovery accelerators. The system-backup format itself remains portable.
