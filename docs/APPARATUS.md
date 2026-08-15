# Apparatus-Specific Analysis

This document defines what the perception and judging layers must be capable of representing for each WAG apparatus. Exact scoring consequences are delegated to the active versioned rule pack.

## Common primitives

Across all apparatus the system should estimate:
- gymnast track and body keypoints;
- body axis and segment angles;
- center-of-mass approximation;
- support/contact states;
- flight intervals;
- rotation and twist progression;
- flexion/extension and leg separation where visible;
- landing contact and post-landing displacement;
- falls / support on apparatus/floor candidates;
- timing between consecutive elements;
- camera visibility / occlusion quality.

No primitive is itself a deduction until the active rules and human/policy workflow map it to one.

# VT — Vault

## Required phase model

1. approach/run context where available;
2. hurdle;
3. springboard contact;
4. pre-flight;
5. table support/contact;
6. repulsion;
7. post-flight;
8. landing contact;
9. landing stabilization / steps / displacement;
10. end state.

## Recognition goals

- vault family candidate;
- entry shape/orientation;
- support timing and hand-contact evidence;
- salto/rotation estimate;
- longitudinal twist estimate;
- body shape classification over phases;
- table-to-flight geometry indicators;
- landing axis/direction;
- line/corridor observations if camera geometry supports it;
- fall/extra support candidate.

## Multi-camera recommendation

At least side/oblique and landing/frontal perspectives are desirable for serious validation. One camera may be insufficient for reliable twist/body-angle/landing-line distinctions.

# UB — Uneven Bars

## Required topology

The vision layer must know low bar/high bar geometry and maintain hand/body relationships to each bar.

## Phase primitives

- mount;
- support/hang;
- swing direction;
- hand contact/regrasp/release;
- flight phase;
- bar transition;
- pirouette/turn phase;
- cast/handstand region;
- dismount;
- landing.

## Recognition goals

- element segmentation despite continuous movement;
- release and regrasp events;
- bar changes;
- turn/twist amount;
- body position through circle/flight;
- handstand-angle measurement candidates where valid from camera geometry;
- connection timing and interruptions;
- falls, extra support or abnormal interruption candidates;
- dismount identity candidates.

## Main technical challenge

UB should use temporal models and apparatus-contact topology rather than frame-only classification. A single pose snapshot rarely identifies the skill safely.

# BB — Balance Beam

## Required geometry

Beam plane/axis/endpoints must be calibrated. Athlete feet/hands/body relationship to beam is central.

## Segment classes

- mount;
- acrobatic element;
- dance/leap/jump/hop;
- turn;
- connection/series;
- choreography/transition;
- hold/pause candidate;
- dismount;
- landing;
- fall/remount interval.

## Recognition goals

- acro/dance element candidates;
- series continuity and timing;
- body/leg angle observations relevant to element recognition or deductions;
- landing alignment and balance corrections;
- step/hop/grasp/support/fall candidates;
- pauses/hesitations measurable in time;
- beam contact/off-beam state;
- mount/dismount boundaries;
- artistry/composition evidence markers where objectively observable.

## Main technical challenge

Qualitative artistry must not be reduced to a single aesthetic model. The system should expose criterion-specific observable evidence and allow human judgement.

# FX — Floor Exercise

## Required geometry

Calibrate the competition floor polygon and, where possible, boundary lines in world/image coordinates.

## Segment classes

- acro pass / tumbling line;
- individual acro element;
- dance leap/jump/hop;
- turn;
- dance/choreography passage;
- landing/recovery;
- corner/preparation interval;
- routine start/end;
- out-of-bounds candidate.

## Recognition goals

- tumbling skill sequence;
- salto rotation/twist/body shape;
- connection timing;
- dance element candidate recognition;
- landing displacement/steps/falls;
- boundary crossing evidence with exact foot/hand frame where visible;
- routine timing if camera/audio timeline is trusted;
- choreography/artistry criterion evidence without identity bias.

## Audio

Audio can assist synchronization and routine timing. Music style, popularity, nationality or performer identity must not become scoring features.

# Apparatus-specific quality gates

Every apparatus session records:
- camera count and positions;
- effective fps/resolution;
- motion blur estimate;
- calibration state;
- occlusion score;
- apparatus visibility;
- athlete tracking continuity;
- inference latency (live mode);
- capabilities enabled/disabled.

Example: if the FX boundary cannot be calibrated, `boundary_detection` must be marked unavailable instead of pretending no boundary deduction occurred.

# Recognition hierarchy

Use hierarchical labels to reduce catastrophic forced classification:

```text
apparatus
  → skill family
    → phase structure
      → candidate element identities
        → distinguishing attributes
```

An analysis may safely know "backward salto family" without being certain of the exact named/numbered element. The UI must preserve that distinction.
