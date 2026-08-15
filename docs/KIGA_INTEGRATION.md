# KIGA Integration

## Principle

Ai.WAGVID remains an independent project/runtime. KIGA may consume validated outputs later, but neither project should become tightly coupled to the other's internal database or ML implementation.

## Integration boundary

Preferred mechanisms:
- REST API for on-demand lookup;
- event/webhook-compatible export for completed analyses;
- JSON/Parquet export for historical/batch analysis;
- signed evidence links/tokens where video access is permitted.

## KIGA should consume

- athlete/event/routine mapping identifiers;
- apparatus;
- rulepack version;
- analysis status;
- accepted element sequence;
- D-score construction components;
- execution/artistry observation summary;
- neutral deduction summary;
- confidence/review state;
- evidence references;
- official-vs-AI comparison when available;
- model/version provenance.

## KIGA should not consume as fact

- unreviewed low-confidence element guesses;
- a final AI score without its review/evidence status;
- private raw pose/model tensors;
- internal model-specific class indexes;
- temporary pipeline state.

## Proposed KIGA use cases

### Competition analysis
Attach Ai.WAGVID routine evidence to an imported competition result and explain likely sources of D/E changes.

### Athlete development
Aggregate confirmed element recognition, landing/execution patterns and apparatus trends over time. KIGA remains responsible for longitudinal analysis; Ai.WAGVID remains responsible for per-video evidence extraction.

### Coach review
Open the exact video segment behind a KIGA observation.

### Data-quality reconciliation
Compare official result metadata with video-derived routine structure and flag mismatches for human review.

## Example export envelope

```json
{
  "schema": "ai.wagvid.analysis.v1",
  "analysis_id": "uuid",
  "routine": {
    "external_event_id": "...",
    "external_athlete_id": "...",
    "apparatus": "BB"
  },
  "rulepack": "FIG-WAG-2025-2028@2026-05-25",
  "state": "HUMAN_CONFIRMED",
  "judging": {
    "d_score": null,
    "d_ledger": [],
    "execution": [],
    "neutral": []
  },
  "evidence": [],
  "provenance": {
    "software_version": "...",
    "model_bundle": "..."
  }
}
```

## Identifier strategy

Ai.WAGVID uses its own UUIDs and stores optional external identifiers. For KIGA integration use stable mappings, never athlete names as keys.

## Compatibility

Every export declares schema version. Breaking integration changes require a new major schema version. Old KIGA imports must remain interpretable.

## Security/privacy

KIGA should receive only the minimum data required. Raw video access should be separately authorised and may remain entirely inside Ai.WAGVID/on-prem storage.
