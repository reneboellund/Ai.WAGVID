# Live Competition & Judge-Assist Architecture

## Scope

Live operation is a separate reliability class from offline analysis. A system that works after a 20-minute batch job is not automatically suitable for a competition.

Ai.WAGVID therefore defines progressive live modes:

1. **Shadow** — AI observes, no panel influence.
2. **Assist** — AI suggestions available to designated officials.
3. **Review Assist** — evidence retrieval and replay for inquiries/reviews.
4. **Research Autonomous Proposal** — system constructs full proposed score, still isolated from official publication unless explicitly authorised.

## Competition station topology

Recommended per apparatus:
- 2+ fixed cameras where practical;
- local capture/encoding;
- synchronized competition clock;
- redundant network path;
- local inference node or edge GPU pool;
- judge/reviewer browser clients;
- event orchestrator;
- local database/object cache;
- central scoreboard/scoring-system adapter only through a controlled gateway.

## Routine lifecycle

```text
READY
→ ARMED
→ CAPTURING
→ ROUTINE_ACTIVE
→ ROUTINE_ENDED
→ ANALYSIS_FINALIZING
→ REVIEWABLE
→ HUMAN/PANEL_DECISION
→ FROZEN
→ EXPORTED
```

Transitions are logged with actor and timestamp.

## Latency budgets

The project shall measure separate budgets rather than one vague "real-time" number:
- capture-to-frame availability;
- pose latency;
- segment recognition latency;
- element candidate latency;
- rule recomputation latency;
- UI propagation latency;
- end-of-routine finalization latency.

The acceptable limit depends on workflow. Judge assistance may allow progressive suggestions during the routine and a short deterministic finalization after the routine ends.

## Failover rules

Competition mode must define behavior for:
- one camera lost;
- all cameras lost;
- GPU worker lost;
- database failover;
- judge terminal lost;
- network partition;
- scoring-system adapter unavailable;
- clock synchronization drift;
- operator accidentally assigns wrong athlete/routine.

No infrastructure failure may silently generate a zero deduction or zero score.

## Human interface

Live UI should prioritize speed and disagreement resolution:

### D panel view
- chronological detected elements;
- candidate alternatives;
- connection/series chain;
- composition requirements;
- running D construction;
- unresolved flags;
- one-click synchronized replay.

### E / execution view
- timeline of deduction candidates;
- severity choices permitted by active rule pack;
- replay around candidate;
- filter by body shape / landing / amplitude / apparatus-specific category;
- accepted deduction ledger.

### Superior/review view
- all panel inputs;
- AI evidence;
- disagreements;
- source cameras;
- decision chronology;
- locked final state.

## Score isolation

AI provisional values and official panel values are physically/logically separated. Shadow mode must not expose AI values to judges before panel freeze if the purpose is unbiased validation.

## Clocking and synchronization

- use monotonic source timestamps;
- maintain wall-clock mapping separately;
- camera sync quality is measured continuously;
- never assume nominal FPS equals actual frame timing;
- preserve source PTS/DTS where possible;
- evidence references canonical timestamps plus source frame IDs.

## Competition configuration freeze

Before session start, freeze/hash:
- rule-pack version;
- model versions;
- camera calibration;
- apparatus profile;
- inference thresholds;
- eligible AI-assisted categories;
- UI policy;
- scoring adapter configuration.

Changes after freeze require an authorised change event and are visible in the audit log.

## Review and inquiry support

The system can become valuable before autonomous judging by providing instant evidence retrieval:
- exact element segment;
- slow motion;
- synchronized multi-view;
- pose/angle overlay;
- candidate identity and rule reference;
- previous accepted decision.

This is a major intermediate deployment target.

## Output publication gate

A result adapter may export only if:
- correct athlete/routine identity confirmed;
- required capture health policy passed;
- rule pack valid;
- no unresolved blocking ambiguity;
- required human approvals present;
- score frozen;
- audit record persisted.

## Replay integrity

Review UI must clearly distinguish:
- original frames;
- transcoded proxy;
- interpolated visualization (if ever used);
- AI-generated overlays.

Interpolated/generative frames must never be presented as original evidence.
