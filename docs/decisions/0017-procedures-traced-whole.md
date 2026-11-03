# 0017 — Procedure claims are traced and compared whole

**Status:** accepted (2026-11-02)

## Problem

The design said a procedure ("Trials lasted 500 ms", "Each network was
trained for 100 epochs") is checked against the code, like a Methods
statement ([0002](0002-claims.md)). The guided steps never did this: only
new-result claims were split into facets, traced, and compared. Every
procedure stayed *Not traced yet*. In a paper with long Methods and figure
legends, that is most of the claims.

Splitting procedures into facets, as new results are, was rejected. A
procedure states one step: what was done, often with a number or two. Its
facets would mostly be empty, and each claim would add several findings
to a report that is already long.

## Decision

1. Procedures skip decompose. Trace takes each one whole, in tasks of
   their own (up to 15 claims each). The answer copies the numbers the
   claim states, as printed, and cites the Methods passages and the code
   lines that carry the step out. Each code passage gives the values it
   sets that the claim states, as the code prints them.
2. When the code works in another unit than the claim (s for ms, a
   fraction for %), the answer names the code's unit. The tool works out
   the claim's value in that unit itself, from a short table of units of
   the same kind (time, frequency, proportion), and lists it as a value
   *computed* from the text. Compare gives it as the value the claim
   predicts for the code.
3. Compare takes procedures in tasks of their own (up to 15 claims each)
   and gives findings for the claim as a whole, with no facet: usually
   one. Values are compared exactly; a step stated in words only gets a
   status with what had to match. A step the code does not carry out is
   *not described* in the code. A step no code could show, such as how
   participants were recruited, is *not verifiable*, with the reason.
4. A claim card whose findings are all for the whole claim has no table
   of facets; the findings say the same thing.

Procedures are not re-derived: what was done is read in the code, not
recomputed from the data.

## Consequences

- Every procedure gets a status, as the design promised. A paper with
  many procedures needs more trace and compare tasks.
- Findings for whole claims have IDs ending in `/whole`.
- The values a procedure states join the cross-claim checks
  ([0016](0016-cross-claim-checks.md)), as other stated values do.
