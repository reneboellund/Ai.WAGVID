# Floor-exercise evidence contract

## Purpose

`src/ai_wagvid/floor_exercise.py` defines the FX-specific pre-scoring evidence layer for issue #10.
It records trusted routine timing, floor-geometry capability, tumbling/dance/turn/choreography
intervals, observable technical evidence and connection continuity candidates. It calculates no
D/E/final score.

## Timing and audio policy

Routine timing is an exact source interval with immutable timeline digest, confidence and evidence.
The allowed timing sources are media timeline, audio timeline or combined.

Audio is timing/synchronization evidence only. The contract contains no music style, performer,
language, popularity or other music-semantic fields. The public schema rejects undeclared timing
metadata.

## Floor geometry and boundary

Floor geometry is an explicit `available`/`unavailable` capability with a floor-polygon digest and
reason. A boundary candidate requires the calibrated polygon digest. If geometry is unavailable the
bundle rejects all boundary candidates instead of treating missing geometry as evidence that no
boundary violation occurred.

## Routine structure and element candidates

Intervals represent routine, tumbling pass, acro candidate, dance candidate, turn candidate,
corner/preparation, choreography and landing. Acro/dance/turn candidates require an immutable
temporal candidate digest. Exact identity can only be exposed when explicitly accepted.

All intervals and observations must remain inside the trusted routine timing interval.

## Observations and connection evidence

Observable facts include rotation, twist, body shape, landing displacement, step/fall, boundary,
connection timing and criterion-specific artistry evidence.

A connection candidate links two distinct intervals and requires timing-evidence observation IDs. It
may be `continuous`, `interrupted` or `unresolved`. The layer never awards connection value; accepted
facts later feed #6 under the active rulepack.

## Public export

`src/ai_wagvid/floor_exercise_exports.py` emits `ai.wagvid.floor-exercise-analysis.v1`, validated by
`schemas/floor-exercise-analysis-v1.schema.json`. The schema is locked to `apparatus: FX` and rejects
music-semantic metadata, connection-value, D/E/final-score and official-result fields.

## Remaining issue #10 work

Issue #10 remains open for real model/runtime and qualified validation:

- trusted full-routine start/end detection on real media/audio timelines;
- tumbling-pass, acro, dance and turn inference;
- calibrated rotation/twist/body-shape estimation;
- persisted floor-polygon calibration and boundary visibility validation;
- landing displacement/step/fall models;
- connection timing and borderline continuity review;
- fixed/broadcast/partial-floor camera benchmark slices;
- rulepack/#6 D/connection/composition integration after accepted facts;
- criterion-specific artistry/composition review validation;
- evidence overlays/failure gallery and #15 promotion evidence.

No music semantics, scoring result or model-quality benchmark is claimed by this contract batch.
