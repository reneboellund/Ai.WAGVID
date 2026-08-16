# Research data policy

## Scope

Ai.WAGVID is currently an internal, non-commercial research and test tool. It is not an external
service, competition decision system or commercial product. A future change of scope requires a
new legal, privacy and dataset-license review before existing data or trained artifacts are reused.

## Discovery and inclusion rule

Every relevant research dataset that is discoverable online is included in Ai.WAGVID's research
catalog, even when its license or source-video terms cannot yet be validated. Inclusion means that
the source, claimed contents, research relevance and access path are recorded; it does not claim
ownership or permission.

A catalogued source with unresolved terms is placed in a controlled acquisition quarantine. Its
metadata, documentation, structure and integrity information may be inspected. Raw media must not
be redistributed or committed to Git, and it must not enter routine model training until a named
responsible researcher records the lawful basis and approves that exact use. This preserves every
research lead without silently treating public availability as a license.

Before acquisition, record:

- dataset and version, source URL, access date and responsible researcher;
- license/terms snapshot, or an explicit `unresolved` marker and review ticket;
- source-video and annotation provenance where separately governed;
- athlete/competition identifiers needed for leakage-safe splits;
- integrity hashes, retention period and deletion/withdrawal procedure;
- whether minors or other sensitive personal data are present;
- quarantine location and the decision that releases or rejects the dataset.

## Storage and publication boundary

Raw datasets, third-party video, credentials and signed access material are stored outside Git in
controlled research storage. They must not be committed, attached to issues, redistributed, or
exposed through a public endpoint. The repository may contain schemas, adapters, provenance
manifests, aggregate metrics and synthetic or explicitly redistributable fixtures.

Derived checkpoints and embeddings inherit applicable source restrictions until a documented review
shows otherwise. Publication of examples, frames, overlays or model artifacts requires a separate
rights and privacy check.

## Competition and KIGA data

User- or club-supplied competition video requires a documented upload basis, competition metadata
and retention controls. Official scores are immutable source records used as supervised targets and
comparison evidence, not unquestioned truth. Large official-versus-AI discrepancies enter human
adjudication; adjudication labels must preserve both the original official result and reviewer
decision.

## Leakage and evaluation

Split by athlete and competition before training. Freeze official scores and adjudications used for
final evaluation. Report dataset/version, split policy, exclusions and known bias. Research data may
improve perception and interpretation models, but the versioned deterministic rule engine remains
the scoring authority over accepted facts.

## Exit conditions

If Ai.WAGVID becomes commercial, externally accessible, operational during competitions or shared
outside the approved research group, stop new processing and re-review every dataset, checkpoint,
video consent, privacy basis and retention rule before continuing.
