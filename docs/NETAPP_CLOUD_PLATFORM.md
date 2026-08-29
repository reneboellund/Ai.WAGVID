# NetApp cloud storage and protection architecture

Ai.WAGVID integrates NetApp cloud services through three independent boundaries: object storage, shared-file storage, and protection/control APIs. A provider may implement more than one boundary, but identities are never silently interchangeable.

## Shared-file contract

FSx for ONTAP, Azure NetApp Files, Google Cloud NetApp Volumes and Cloud Volumes ONTAP may expose NFS/SMB storage to workers. `SharedFileResource` records provider/resource identity, protocol, mount reference, private network scope, region, capacity, health and locality token. Worker mount planning checks region/network reachability, read/write capability and SMB identity requirements before scheduling a mount.

A file identity is `file://<provider>/<resource>/<relative-path>`. It is not an S3 bucket/key identity, even where the same underlying data also has an object access path.

## FSx for ONTAP

FSx volumes remain file storage first. The backing ONTAP/FSx resource may use snapshots, SnapMirror or managed backup when those capabilities are explicitly discovered. An FSx ONTAP S3 Access Point is represented as an explicit adapter identity and is not treated as AWS S3 or native ONTAP S3.

The v1 access-point boundary enforces the 50 GiB object limit and does not advertise presigned URLs, S3 versioning, Object Lock, legal hold, lifecycle, bucket policy or public-access-block semantics. Multipart is only advertised when explicitly validated for the attached profile. S3 access-point creation is approval-gated and refuses unsupported governance requirements.

The current persisted provider enum has not yet been migrated with a dedicated FSx-access-point value, so this adapter temporarily uses `generic-s3` while retaining the explicit `fsx-ontap-s3-access-point:<provider-id>` runtime identity. This is deliberate and fail-closed rather than pretending to be AWS S3.

## Azure NetApp Files

ANF is integrated as shared file storage. Discovery normalizes volume identity, Azure region/subscription, delegated network scope, service level, capacity and mount information. Snapshot, backup, file restore, volume revert and cross-region replication are protection/control-plane capabilities. Revert and replication direction-changing actions are destructive and require the destructive confirmation gate.

## Google Cloud NetApp Volumes

GCNV is integrated as shared file storage, not S3. Discovery normalizes project/location/network, service level, capacity and NFS/SMB mount identity. Snapshot and cross-region replication are modeled as protection capabilities. Reverse/resync style relationship changes require explicit destructive approval and never rewrite Ai.WAGVID canonical media identity on their own.

## Cloud Volumes ONTAP

NetApp Console owns working-environment discovery and lifecycle. Once a CVO environment is online, Ai.WAGVID may create a separate ONTAP handoff containing only endpoint/config references and secret references; normal ONTAP REST/S3 modules then manage the ONTAP layer. Core code rejects ad-hoc low-level cloud disk/aggregate mutations that bypass Console-supported lifecycle operations.

## NetApp Backup & Recovery

Backup & Recovery is protection-only. It never becomes the live #60 storage provider. Logical retained roles may be mapped to backup policies and their protection/job/recovery-point health displayed independently of live routing.

Restore defaults to an alternate/staging target. Before any production cutover, Ai.WAGVID verifies the restored object/file inventory, canonical SHA-256 where available, provider health and that canonical routing has remained unchanged during validation. Cutover requires the explicit phrase `CUT OVER VERIFIED NETAPP RESTORE`.

## Mutation policy

Cloud provisioning and protection actions are first expressed as deterministic plans containing no secret material. Plan digests become idempotency/approval boundaries. Non-destructive mutations require `APPLY NETAPP CLOUD CHANGES`; destructive protection actions such as revert, replication break/resync/reverse or destructive access-point changes require `APPLY DESTRUCTIVE NETAPP PROTECTION CHANGE`.

Provider SDK/REST adapters are intentionally thin. Ordinary CI uses fake adapters only and never creates volumes, snapshots, access points, mirrors, backups, restores or cloud workers. Real-provider validation remains a milestone-specific lab/acceptance activity.
