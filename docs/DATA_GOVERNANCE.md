# Data governance, provenance and post-event audit

Issue: #16. Product scope follows #17 and validation governance #15.

This branch defines cross-cutting policy/provenance contracts. It does **not** replace Django authentication, the existing append-only application audit model, KIGA evidence-grant transport, object-storage retention APIs or #72/#73 recovery/upgrade controls.

Adapters execute decisions. The core records why an action is allowed/blocked and the immutable provenance required around it.

## 1. Explicit rights and permissions

`DatasetRightsRecord` binds:

- source reference + SHA-256;
- rights/consent/licence reference + SHA-256;
- explicit permissions;
- retention class;
- validity/revocation times.

Permissions are independent:

- `view`
- `download`
- `analyze`
- `retain`
- `train`
- `export`
- `share-evidence`

Most importantly, `train` is never inferred from `view`, `download`, `analyze` or `retain`.

Public audit schema: `schemas/dataset-rights-v1.schema.json`.

Operational integration:

- KIGA `rights.training_allowed` maps to the generic training permission;
- dataset/research registries retain the rights record digest;
- #15 benchmark datasets must refer to cleared/synthetic rights evidence and split manifests;
- a revoked/expired permission fails at evaluation time even if the original record once permitted it.

## 2. Pseudonymous grouping IDs

`pseudonymous_group_id()` uses HMAC-SHA256 with a deployment secret of at least 32 bytes and an explicit namespace.

The same stable source ID produces deterministic grouping within one namespace/key, while:

- another namespace produces another pseudonym;
- another deployment/rotation key produces another pseudonym;
- the source ID is not encoded in the output.

The pseudonym key itself belongs in secret storage. It is not exported with datasets.

This supports athlete/event grouping and leakage protection without making display identity a model feature.

## 3. Retention and deletion are separate from storage DELETE

`RetentionRecord` tracks:

- canonical media SHA-256;
- acquisition time;
- retention class/window;
- legal holds;
- provider immutability/Object-Lock-like time.

`DeletionRequest` requires requester, approver, reason and correlation ID before policy evaluation.

`evaluate_deletion()` also checks active:

- evidence references;
- dataset references;
- export references;
- provider delete permission.

Possible results:

- `blocked`
- `quarantine-only`
- `physical-delete-allowed`

A pure time-window blocker can permit quarantine/soft-delete while physical deletion waits until the longest retention/provider-immutability date. Legal hold, active provenance references or provider deletion denial remain hard blockers.

The storage adapter may call DELETE only after `physical-delete-allowed`. A provider retention denial is a governance state, not a generic transient-success path.

## 4. Frozen configuration and secret handling

`freeze_configuration()` canonicalizes the public/non-secret configuration and records only secret **references**.

The factory rejects obvious plaintext secret-like fields such as password/token/access/secret/private-key fields unless the field is explicitly a `_ref` / `_reference`.

A `FrozenConfigSnapshot` contains:

- organization ID;
- config schema version;
- canonical public JSON;
- SHA-256 config digest;
- secret references;
- creation time.

The same JSON content yields the same digest regardless of input mapping order.

`ConfigChangeLedger` is append-only and anchored to an initial frozen digest. Every change requires:

- from/to digests;
- actor;
- approver;
- reason;
- correlation ID;
- increasing time;
- prior-change digest after the first change.

Historical analyses therefore remain pinned to the exact configuration digest even when current settings later change.

## 5. Original evidence versus derived visualization

`EvidenceProvenanceRef` distinguishes:

- `source-interval`
- `proxy`
- `overlay`
- `interpolated`
- `generated-visualization`

Every representation still carries the canonical source-media SHA-256.

Only `source-interval` may set `represented_as_original=true`. A proxy, pose overlay, interpolated frame or generated visualization cannot be serialized as original evidence.

This rule exists both in Python and `schemas/production-decision-provenance-v1.schema.json`.

## 6. Production decision provenance

`ProductionDecisionProvenance` binds a material conclusion to:

- organization/object reference;
- semantic layer;
- state (`provisional`, `confirmed`, `rejected`, `unresolved`);
- decision authority/reviewer reference;
- evidence provenance;
- rulepack digest;
- model bundle digest;
- software digest;
- frozen config digest;
- calibration digest or an explicit calibration-unavailable limitation;
- creation time;
- superseded decision ID where applicable.

Semantic layers remain explicit:

- observed fact;
- judging interpretation;
- score effect;
- pattern;
- coaching hypothesis;
- suggested training focus.

A confirmed material decision must include canonical source-interval evidence. Generated/overlay evidence may support review, but cannot be the only basis of a confirmed material conclusion.

`ProductionDecisionLedger` keeps revisions append-only and non-forking.

Public audit schema: `schemas/production-decision-provenance-v1.schema.json`.

## 7. Evidence sharing

This branch intentionally does not create a second token issuer. The generic policy is executed through existing/scoped evidence-grant adapters, including the KIGA integration work under #14.

A share must remain bound to:

- organization;
- subject/recipient;
- exact evidence digest/reference;
- explicit permission;
- expiry/revocation;
- auditable grant ID.

Public bucket exposure is not an evidence-sharing mechanism.

## 8. Application audit integration

Canonical serializers in `src/ai_wagvid/governance_exports.py` provide stable audit payloads for:

- dataset rights;
- deletion decisions;
- frozen configuration;
- production-decision provenance.

The operational Django layer should record their digests/payloads through the existing organization-scoped append-only AuditEvent mechanism rather than introducing another audit database.

## 9. Threat/deployment checklist

The #15 `governance` validation layer should require deployment evidence for at least:

- organization/role isolation;
- TLS and trusted CA/certificate handling;
- secret-store references/no plaintext secret export;
- rights/training-permission registry;
- retention/hold/deletion gates;
- evidence grant scope/expiry/revocation;
- original-vs-derived evidence provenance;
- rule/model/software/config/calibration digests;
- append-only application + production-decision audit;
- backup/restore and upgrade rollback readiness (#72/#73);
- incident contact/runbook and secret-compromise rotation path.

A deployment-specific threat model can add controls, but cannot remove the cross-cutting provenance/rights gates without failing the #15 governance validation slice.

## 10. Incident/recovery coordination

Governance recovery uses the existing cross-cutting recovery framework:

- lost/compromised secret -> revoke/rebind/rotate; never restore plaintext secret from normal backup;
- damaged config -> recover a frozen config revision through audited change flow;
- lost DB/app host -> #72 restore while media identity/provenance remains hash-bound;
- failed upgrade -> #73 maintenance/rollback flow;
- compromised evidence grant -> revoke grant and audit replacement;
- incorrect human/AI conclusion -> append a superseding decision, never rewrite the old decision.

## Remaining work before #16 closes

- map existing Django roles/permissions and qualified reviewer roles to the governed operations;
- persist dataset-rights records and pseudonymous grouping keys safely;
- integrate retention/deletion evaluation with the common storage/provider layer and quarantine workflow;
- persist frozen configuration + authorized change ledger;
- emit canonical governance records through the existing AuditEvent model;
- connect production-decision provenance to #18 review/adjudication and #19 coach-review persistence;
- connect #14 evidence-grant records to generic evidence-sharing audit;
- define deployment-specific threat model/checklist and #15 governance promotion metrics;
- exercise rights revocation, legal hold, secret compromise, evidence-grant revocation and restore/rollback incident fixtures.

No shadow/live/official judging mode, PR, merge, GitHub Actions run or destructive storage action is created by this branch.
