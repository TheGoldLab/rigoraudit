# 0008 — Wording with a threshold, and wording with none

**Status:** accepted (2026-10-28)

## Problem

Restating the first example audit under schema v3 (0007) required a computed
status for every numeric finding. Some claims are qualitative but rest on a
threshold the text does not print. In synthetic form:

- significance wording: "driven mainly by subject A", "confined to the early
  epoch", "neither term reliably dominating", "uncorrelated", "no reliable
  difference";
- proportions: "the majority of the change".

One claim states no criterion at all: "the two groups changed by comparable
amounts" (R2.3.b).

Before v3 these were judged case by case. The record already read "no
reliable difference" as p ≥ 0.05 in one place, but no rule said so.

## Decision

1. **Significance wording is read at α = 0.05**, unless the paper states
   another level. "Significant", "reliable", and "differs" read as p < 0.05.
   "No reliable difference", "uncorrelated", and "neither predominating" read
   as p ≥ 0.05. Each finding prints its reading, e.g. *"uncorrelated" read as
   p ≥ 0.05*.
2. **Proportion words read at their plain threshold.** "Majority" reads as
   > 0.5.
3. Direction findings may therefore use inequality comparisons as well as
   sign comparisons (`schema._KINDS_FOR_BASIS`).
4. **Wording with no criterion is *Not verifiable*.** Examples are
   "comparable" and "similar" without a hedge. The reason is stated, and the
   values are shown so readers can judge for themselves. The hedged-wording
   default (±10%, 0006 rule 4) is not applied, because "comparable" is not a
   hedge on a stated value.

This does not change 0006 rule 3. Design statements are still never judged
by a p-value. Rule 1 applies only where the paper's own wording is a claim
about a test.

## Example (synthetic)

| Finding | Reading | Status |
|---|---|---|
| R3.1.a | "significant across subjects" p < 0.05 (all, A); "driven mainly by A" p ≥ 0.05 (B, C) | Consistent |
| R3.1.c | "no reliable difference" p ≥ 0.05 (B 0.032, A 0.27, pooled 0.009) | Differs |
| R3.2.b | differences at 100–300 ms p < 0.05; "confined to" p ≥ 0.05 elsewhere | Consistent |
| R4.1.a | "neither term reliably dominating" p ≥ 0.05 (0.29, 0.61) | Consistent |
| R4.1.b | "uncorrelated" p ≥ 0.05 (0.47, 0.73) | Consistent |
| R2.3.c | "majority" > 0.5 (group 1: 0.64, group 2: 0.71) | Consistent |
| R2.3.b | "comparable": no criterion | Not verifiable (was Consistent) |

## Why

The record already used these readings in its summaries. Writing them down
makes each status reproducible, and printing the reading lets a reader who
would draw the line elsewhere see where each value falls. Treating
"comparable" as *Not verifiable* avoids inventing a tolerance the paper never
implies.

## Notes

- 2026-10-30: The examples above are synthetic. The originals, from an
  example audit, were moved to that audit's workspace so that this
  repository holds no audit content (see [release.md](../release.md)).
