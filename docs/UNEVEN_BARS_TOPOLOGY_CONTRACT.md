# Uneven-bars topology contract

## Purpose

`src/ai_wagvid/uneven_bars.py` defines the UB-specific pre-scoring contact/topology layer for issue
#8. It records evidence-backed contact state, release/regrasp/bar-change events, accepted temporal
element references and continuity candidates. It does not award connection value or calculate D/E.

## Bar identity

Bar identity is one of `low-bar`, `high-bar` or `unknown`. Known bar identity requires a calibrated
bar-geometry digest. Without geometry the contract remains `unknown`; it must not guess which bar is
involved from mutable labels or sequence assumptions.

A `bar-change` event requires known, different from/to bars and calibrated geometry.

## Contact topology

Contact intervals can represent hang, support, released, flight, regrasp, fall/interruption or
unknown state. Topology events include contact boundaries, release, regrasp, bar change,
handstand-region, turn-progress and fall/interruption.

Each interval/event keeps exact time, confidence, immutable evidence references, optional geometry
and limitations.

## Element references

The topology layer references temporal candidates by immutable digest. An exact element identity can
only appear when that reference is explicitly marked accepted. Unreviewed temporal alternatives
cannot be relabelled as accepted exact UB elements in this contract.

## Continuity

A continuity candidate links two distinct element segments and requires one or more topology event
IDs as evidence. It may be `continuous`, `interrupted` or `unresolved`.

Temporal proximity by itself is not enough to create a continuity conclusion. This module does not
award FIG connection value; accepted continuity facts later feed the deterministic rule engine in #6.

## Public export

`src/ai_wagvid/uneven_bars_exports.py` emits `ai.wagvid.uneven-bars-topology.v1`, validated by
`schemas/uneven-bars-topology-v1.schema.json`. The schema is locked to `apparatus: UB` and rejects
connection-value, D/E/final-score and official-result fields.

## Remaining issue #8 work

Issue #8 remains open for trained/pinned UB inference and real validation, including:

- contact/release/regrasp timing models and benchmarks;
- high/low bar geometry binding to persisted calibration/media;
- cast/handstand, pirouette, release, transition, circle and dismount recognition;
- complete routine contact/element graph generation;
- borderline interruption/connection review against qualified labels;
- bar-identity and release/regrasp timing error benchmarks;
- real full-routine camera/occlusion validation;
- #6 rulepack connection/composition/repetition integration after accepted facts;
- evidence overlays/failure gallery and #15 promotion evidence.

No model-quality or connection-scoring result is claimed by this contract batch.
