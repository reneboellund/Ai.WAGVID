# Leakage-safe research splits

Gymnastics datasets contain correlated clips: multiple skills from one routine, repeated routines
from one event, the same gymnast across competitions and duplicate source video under different
filenames. Random clip-level splitting would produce misleading evaluation results.

`ai_wagvid.dataset_splits` builds connected components across four grouping dimensions:

- pseudonymous gymnast identity;
- competition/event identity;
- routine identity;
- immutable source-video SHA-256.

If any two samples share a dimension, they—and all transitively connected samples—receive the same
train, validation or test split. Components are assigned deterministically from a versioned salt;
changing the policy requires a new salt and a recorded dataset version. Empty athlete/event IDs are
allowed for legitimately de-identified sources, but routine ID and source checksum are mandatory.

The leakage audit also checks externally supplied/manual assignments and fails when any grouping
key spans multiple splits. This contract is implemented before dataset downloads or training so all
future FineGym, Gym288, OSL and project-video adapters must obey the same boundary.

## Versioned manifests

Every imported research source must use `schemas/dataset-manifest-v1.schema.json`. The manifest
records its exact version and origin, retrieval time, approval basis, approving party, permitted
uses, personal-data class and immutable media hashes. An unverified source may be catalogued for
later review, but it must not enter training until these required governance fields are populated.

Official competition scores are retained as reference labels, not unquestionable ground truth.
Model disagreement is therefore review evidence: a qualified reviewer can confirm the official
result, confirm a model-supported judging concern, or mark the case unresolved. Training data
derived from a reviewed disagreement must retain that decision and its provenance.
