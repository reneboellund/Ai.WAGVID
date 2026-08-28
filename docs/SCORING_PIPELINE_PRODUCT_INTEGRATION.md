# Scoring pipeline: product integration

The analysis core and the operational product are connected through immutable,
schema-bound artifacts. A worker may calculate results, but it cannot silently
turn a model proposal into an official or human-approved score.

## Artifact chain

1. Temporal recognition records element alternatives, probabilities and evidence.
2. The deterministic D-score engine evaluates accepted facts against a pinned rulepack.
3. The deduction ledger records accepted, rejected, unresolved and escalated candidates.
4. The apparatus module records evidence specific to VT, UB, BB or FX.
5. Release validation records dataset rights state, validation slices, promotion gates,
   limitations and waivers.
6. Human review and score verification remain separate, auditable decisions.

Every published artifact is validated against its public JSON Schema, linked to an
analysis job and source-media SHA-256, and stored with rule/model provenance and
upstream digests. Repeating an identical publish is idempotent. Reusing identical
payload bytes with different upstream provenance is rejected.

## Supported schemas

- `ai.wagvid.temporal-recognition.v1`
- `ai.wagvid.dscore-ledger.v1`
- `ai.wagvid.deduction-ledger.v1`
- `ai.wagvid.vault-analysis.v1`
- `ai.wagvid.uneven-bars-topology.v1`
- `ai.wagvid.balance-beam-analysis.v1`
- `ai.wagvid.floor-exercise-analysis.v1`
- `ai.wagvid.release-validation.v1`

Artifacts can be published from the analysis review page and downloaded with a
digest-bound ETag from the reports area. Organization scoping applies to both UI
and JSON downloads.

## Safety boundary

The modules are production-shaped deterministic control and evidence layers, not
a claim of empirically validated judging accuracy. Competition use remains blocked
until representative data, apparatus-specific benchmarks, model cards, rulepack
review, calibration and documented promotion gates have passed. Official scores
may be used as a blinded comparison target after inference; they are not leaked
into the worker input or treated as infallible labels.
