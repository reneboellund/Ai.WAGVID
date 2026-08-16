# Ai.WAGVID UI/UX Design System

## Status
Canonical visual direction for Ai.WAGVID post-event WAG video analysis.

Canva source folder: `Ai.WAGVID` (Canva folder ID `FAHSaA85XIU`).

## Product purpose
Ai.WAGVID is a post-event/post-routine analysis platform for recorded WAG routines. The UI must support both:
1. score verification and FIG-rule evidence review;
2. coach/athlete performance analysis and development priorities.

It is explicitly **not** a live judging interface.

## Visual direction
- premium 2026 sports-tech / AI analytics aesthetic;
- dark graphite/navy foundations with light content surfaces where appropriate;
- luminous emerald/teal primary accent;
- restrained electric cyan/blue for analysis/evidence;
- amber/orange for warnings and review-needed states;
- red reserved for high-confidence deductions/errors;
- subtle gradients, thin technical grid lines and motion/timeline motifs;
- rounded but precise cards and controls;
- strong numerals and compact data typography;
- accessible contrast and no neon/cyberpunk overload.

## Core UX principle: Evidence first
Every score, deduction, strength, weakness, pattern or recommendation must link to the exact supporting video evidence where available.

The UI must visually separate:
- Observed Fact
- Judging Interpretation
- Score Effect
- Pattern
- Coaching Hypothesis
- Suggested Training Focus

Confidence/ambiguity must never be hidden. `NEEDS REVIEW` is a first-class state.

## Canonical screens
1. Visual identity / design tokens
2. Main dashboard
3. Routine analysis workspace
4. Frame evidence detail
5. D-score reconstruction
6. Deduction list
7. Score verification
8. Coach performance analysis
9. Technical pattern explorer
10. Athlete longitudinal view
11. Apparatus hub (VT/UB/BB/FX)
12. Mobile responsive concept
13. Component library
14. Iconography / asset board
15. Background / motion asset board
16. Developer handoff

## Component families
### Navigation
- app shell / left navigation
- breadcrumbs
- tabs
- apparatus switcher
- athlete/event selectors

### Analysis
- video player shell
- frame step controls
- timeline
- timeline markers
- evidence thumbnail
- pose/geometry overlay styles
- confidence badge
- review state badge

### Scoring
- D-score card
- E/deduction summary card
- neutral deduction card
- official-vs-reconstructed comparison card
- element ledger row
- deduction ledger row
- rule reference chip

### Coaching
- strength card
- weakness / point-loss card
- technical pattern cluster
- priority action card
- observation/pattern/hypothesis/training-focus labels
- longitudinal trend card

### System
- loading state
- analysis processing state
- empty state
- error state
- toast
- modal
- tooltip
- accordion
- filter/search controls

## Required icon family
Original non-FIG icons for:
- VT
- UB
- BB
- FX
- video
- play/pause
- previous/next frame
- evidence
- rulebook
- D-score
- execution/deduction
- compare
- strength
- weakness
- trend
- recurring pattern
- coach note
- review needed
- accepted
- rejected
- KIGA export

## Required asset/export matrix
Target repository location: `assets/ui/`.

### Backgrounds
- `ui-bg-dark.png`
- `ui-bg-light.png`
- `ui-bg-analysis-grid.png`
- `ui-bg-motion-arcs.png`
- `ui-bg-timeline-pulse.png`

### Apparatus icons
- `icon-vt.svg` + PNG fallback
- `icon-ub.svg` + PNG fallback
- `icon-bb.svg` + PNG fallback
- `icon-fx.svg` + PNG fallback

### Functional icons
- `icon-video.svg/png`
- `icon-frame-prev.svg/png`
- `icon-frame-next.svg/png`
- `icon-evidence.svg/png`
- `icon-rulebook.svg/png`
- `icon-d-score.svg/png`
- `icon-deduction.svg/png`
- `icon-compare.svg/png`
- `icon-strength.svg/png`
- `icon-weakness.svg/png`
- `icon-trend.svg/png`
- `icon-pattern.svg/png`
- `icon-coach-note.svg/png`
- `icon-review-needed.svg/png`
- `icon-accepted.svg/png`
- `icon-rejected.svg/png`
- `icon-kiga-export.svg/png`

### Badges / timeline markers
- `badge-confidence-high.svg/png`
- `badge-confidence-medium.svg/png`
- `badge-confidence-low.svg/png`
- `badge-needs-review.svg/png`
- `timeline-marker-element.svg/png`
- `timeline-marker-deduction.svg/png`
- `timeline-marker-landing.svg/png`
- `timeline-marker-connection.svg/png`
- `timeline-marker-review.svg/png`

### Motion assets
- `loader-analysis.gif`
- `pulse-evidence.gif`
- `timeline-processing.gif`

GIFs must be subtle, short-looping and non-distracting. SVG is preferred for scalable icons where the design tool/export path allows it; PNG fallback is mandatory.

## Developer handoff requirements
The final Canva design must document:
- color tokens;
- spacing scale;
- radius scale;
- shadows/elevation;
- typography hierarchy;
- status/severity/confidence states;
- component naming;
- responsive behavior;
- hover/focus/selected/disabled states;
- mobile condensation rules;
- asset filenames and intended use.

## Implementation workflow
Substantial UI implementation should be offloaded to Codex through a Codex-ready GitHub issue/PR workflow. Canva is the visual source of truth; GitHub stores the durable design specification and exported assets.
