# 0006 — When sources "differ": comparison bases and tolerances

**Status:** accepted (2026-10-28)

## Problem

In the first mock-up two design statements were judged without a rule. In
synthetic form:

- Switch probability: stated 30%, realized 31% of 40,000 trials → labeled
  *Consistent*.
- Stimulus duration: stated "exponential … mean of 400 ms", 200–1500 ms;
  realized mean 380 ms → labeled *Differs*.

Both departures are statistically detectable at this sample size, and both
are small. The mean comparison also set a sample mean against a generating
parameter. Truncating that exponential to 200–1500 ms changes its mean, so
400 ms is not what the design predicts for the trials observed.

## Decision

1. **Compare like with like.** Before comparing, convert a stated value into
   what it predicts for the quantity observed.
2. **Every *Consistent* or *Differs* finding declares its comparison basis**
   (`Finding.basis`):
   - **exact**: counts, identities, codings, code settings, named tests, bin
     edges. Any mismatch is *Differs*.
   - **reported precision**: a reported statistic compared with the audit's
     recomputation from the same data. It is *Consistent* if the recomputation
     rounds to the reported value at the reported precision. Inequalities such
     as "p < 0.001" are checked as stated.
   - **design vs realization**: a design parameter (probability,
     distribution, timing, coherence) compared with the recorded trials,
     judged by size, not significance. The realized values are always shown.
   - **direction**: a qualitative statement (higher, shallower, increases)
     checked against the direction in the data. If a test is reported, its
     statistic is checked separately under *reported precision*.
3. **No status is set by a p-value.** With tens of thousands of trials,
   negligible departures are significant. With a few sessions, large ones are
   not.
4. **Tolerances** are printed in each finding (`Finding.tolerance`). Defaults:
   - design proportions: ±2 percentage points;
   - design durations, rates, and other continuous values: ±5% of the
     predicted value;
   - stated ranges: all realized values must fall inside the range;
   - hedged wording ("~", "approximately", "roughly"): ±10%, unless the
     wording implies a tighter bound.
5. **Level.** Design statements are checked for each subject (each animal or
   participant group the design applies to), because pooling can hide a
   subject that departs from the design. Statements about an analysis or a
   display are checked at the level shown, with per-subject values listed as
   evidence.
6. **A difference is not a cause.** When the materials cannot tell causes
   apart, such as trial selection versus generator settings, the finding says
   so and does not choose between them.

## Example (synthetic)

| Claim | Basis | Comparison | Status |
|---|---|---|---|
| R1.1.b duration range | design vs realization | all values within 200–1500 ms, each subject | Consistent |
| R1.1.b duration mean, A / C | design vs realization | −1.8% / −0.6% of the predicted mean | Consistent |
| R1.1.b duration mean, B | design vs realization | −6.4% | Differs |
| R1.2.a switch rate, A / C | design vs realization | 30.4% / 29.1% | Consistent |
| R1.2.a switch rate, B | design vs realization | 33.5% | Differs |
| R2.1.c SEM | reported precision | 4.12 reported vs 4.57 recomputed | Differs |
| R2.1.d | reported precision, hedged | "~80" vs 83.0 ms | Consistent |
| F3.B.a sessions, C | exact | 41 vs 40 | Differs |
| F3.C.a bin counts | design vs realization, hedged, display level | pooled counts within 6% of equal (B alone: 25%) | Consistent |

## Why

The rule makes every status reproducible from what the finding prints: the
basis, the tolerance, and the values. Readers who would draw the line
elsewhere can see where each value falls.

Per-subject checking was chosen after pooling hid the clearest case in the
first mock-up: one subject's switch rate and mean duration fell outside
tolerance while the pooled values did not, as for subject B above.

## Notes

- 2026-10-30: The examples above are synthetic. The originals, from an
  example audit, were moved to that audit's workspace so that this
  repository holds no audit content (see [release.md](../release.md)).
