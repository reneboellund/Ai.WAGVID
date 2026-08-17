# Backup, recovery and upgrade safety model

Ai.WAGVID treats application code as replaceable and production data as durable state. The portable recovery baseline is deliberately independent of NetApp, Wasabi, AWS S3 or any other storage vendor.

## Recovery artifacts

A verified system backup consists of a versioned `ai.wagvid.system-backup.v1` manifest plus referenced artifacts. The manifest records the exact application Git SHA, migration heads, PostgreSQL version, configuration bundle, recoverable object inventory, rule/model artifact digests and secret references. Plaintext operational secrets do not belong in the ordinary backup set.

Large canonical video objects normally remain on their configured object/file providers. `ai.wagvid.system-object-inventory.v1` records their provider, bucket/filesystem location, version identifier, size, SHA-256 and retention/protection state so a restored control plane can prove that its database still points to the expected evidence.

## PostgreSQL baseline

Logical `pg_dump` plus `pg_restore` is the provider-neutral portability floor. Command planning keeps passwords out of process arguments; credentials must be injected through the deployment secret mechanism (for example a protected pgpass/service configuration or environment supplied only to the subprocess).

Provider-native snapshots, PostgreSQL PITR and NetApp SnapCenter may accelerate protection or recovery, but cannot be the only recovery method.

## Restore safety

Restore defaults to a new/staging target. Paths referenced by a backup manifest are resolved below the selected backup root and path traversal is rejected. Artifacts are SHA-256 verified before use. A database restore does not overwrite media storage. Before recovered services accept writes, storage providers and the object inventory must be reconciled and missing secrets rebound.

## Upgrade safety

Every release must eventually publish `ai.wagvid.release-manifest.v1`. It declares supported PostgreSQL versions, target Django migration heads, direct/intermediate upgrade paths, configuration/storage/rule/model schema versions, rollback semantics and compatible Android protocol range.

An upgrade is blocked when there is no declared path, PostgreSQL is incompatible, migration state is unknown, required providers are unavailable or a verified pre-upgrade backup is missing. Application upgrades never reset the database, replace customer configuration with packaged defaults or move/delete canonical media as an implicit deployment side effect.

Destructive schema changes should use an expand/backfill/switch/contract lifecycle over releases. Database-affecting rollback defaults to restoring the verified pre-upgrade database into a staging/new target and validating it against the previous application release instead of trusting reverse migrations blindly.

## Provider relationship

NetApp, Wasabi, AWS S3, VAST, Ootbi and future providers remain peers. Provider-specific snapshot/replication/backup capabilities appear as protection references and optional recovery accelerators. The system-backup format itself remains portable.
