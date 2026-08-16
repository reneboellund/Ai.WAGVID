# Research data policy

## Scope

Ai.WAGVID is currently an internal, non-commercial research and test tool. It is not an external
service, competition decision system or commercial product. A future change of scope requires a
new legal, privacy and dataset-license review before existing data or trained artifacts are reused.

## Admission rule

A research dataset may be used only when its recorded terms explicitly permit the intended internal
non-commercial research use. Public availability, a paper citation or a downloadable archive is not
permission by itself. Sources with unresolved terms remain on research hold.

Before ingestion, record:

- dataset and version, source URL, access date and responsible researcher;
- license/terms snapshot and the exact permitted purpose;
- source-video and annotation provenance where separately governed;
- athlete/competition identifiers needed for leakage-safe splits;
- integrity hashes, retention period and deletion/withdrawal procedure;
- whether minors or other sensitive personal data are present.

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
