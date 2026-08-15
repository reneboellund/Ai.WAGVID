# Canonical Data Model

## Design rules

- source media is immutable;
- analysis revisions are additive;
- observations and decisions are distinct entities;
- all material records carry provenance;
- IDs are stable and integration-safe;
- historical analyses remain pinned to their rule/model versions.

## Core entities

### Event
Competition/training event metadata and governing profile.

### Athlete
Minimal event identity required to associate a routine. Identity must not be used as a judging feature.

### Routine
One athlete + apparatus + event occurrence.

Suggested fields:
```json
{
  "routine_id": "uuid",
  "event_id": "uuid",
  "athlete_id": "external-or-local-id",
  "apparatus": "VT|UB|BB|FX",
  "category": "event-defined",
  "start_order": 12,
  "rulepack_id": "FIG-WAG-2025-2028@2026-05-25",
  "state": "DRAFT_AI"
}
```

### MediaSource
Original camera/video source, checksum, codecs, clocks, dimensions, FPS diagnostics and retention metadata.

### Calibration
Camera intrinsics/extrinsics or simpler 2D apparatus geometry, with validity interval and quality.

### ModelRun
Exact model/config/container/code identity and runtime statistics.

### Observation
Machine or human observation independent of scoring consequence.

Fields include:
- observation type;
- source model/user;
- time/frame range;
- geometry/measurement;
- confidence;
- quality;
- source cameras.

### Segment
Canonical temporal unit representing a phase, skill candidate, connection interval or choreography region.

### ElementCandidate
Ranked element hypotheses for a segment.

### AcceptedElement
Human/policy-confirmed element interpretation referencing the candidate/evidence used.

### DeductionCandidate
Evidence-linked possible execution/artistry/neutral deduction.

### JudgingDecision
Human or policy decision on a candidate. Never overwrite candidate history.

### RuleApplication
Deterministic evaluation result from rulepack + accepted facts.

### ScoreLedger
Transparent score construction rather than only totals.

### EvidenceArtifact
References frame(s), clips, overlays and measurements used for review.

### AuditEvent
Append-only state/config/decision change record.

## Score ledger concept

```json
{
  "routine_id": "...",
  "rulepack_id": "...",
  "d": {
    "counted_elements": [],
    "composition": [],
    "connections": [],
    "total": null
  },
  "e": {
    "accepted_deductions": [],
    "total_deduction": null,
    "score": null
  },
  "neutral": [],
  "final": null,
  "unresolved": [],
  "state": "NEEDS_REVIEW"
}
```

`null` is preferable to a guessed zero.

## Evidence references

Evidence must be reproducible by:
- source media hash;
- media source ID;
- canonical start/end time;
- source frame identifiers where meaningful;
- transform/overlay version;
- calibration ID;
- generating model run.

## Model/version provenance

A production decision should be traceable to:
- git commit/release;
- container/image digest;
- model artifact digest;
- model configuration digest;
- rulepack digest;
- calibration digest;
- runtime hardware class if determinism can vary.

## Privacy

Separate personally identifying event data from machine feature records where feasible. Dataset exports should support pseudonymous athlete IDs and exclude unnecessary names/birth details.

## Dataset split protection

Maintain stable athlete/event/routine grouping keys to prevent near-duplicate or same-routine leakage between training and evaluation sets.
