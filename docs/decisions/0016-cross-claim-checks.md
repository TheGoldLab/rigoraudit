# 0016 — Cross-claim checks: values that disagree between claims

**Status:** accepted (2026-11-02)

## Problem

Compare takes one claim at a time and sets what that claim says beside
the code, data, and Methods behind it. It never sets one claim's value
beside another's. So when two places in the paper give different values
for the same thing, no step notices. This matters in two cases:

- Neither value can be checked against code or data. One sentence says
  "48 of 60 sessions", a figure legend says "48 of 61 sessions", and no
  shared file counts the sessions. Each claim is *Not verifiable*, and
  nothing says the two printed values differ.
- Both values differ from the code, in different ways. Each claim gets its
  own *Differs*, and the report does not say that the paper also gives two
  values for one quantity.

Two ways of handling this were rejected:

- **Leaving it out.** The report would then be silent on an error a reader
  can see by setting two pages side by side.
- **Linking claims while each is processed.** The result would depend on
  the order of the claims, every task would need the other claims in its
  context, and the stages would come to depend on each other.

Comparing every pair of claims is also out: the work grows with the square
of the number of claims.

## Decision

1. **A new stage, `cross-check`, after compare and before verify.** It
   reads the compare findings, and writes to `work/crosscheck/`. It changes
   no compare finding.

2. **It groups observations, then compares within each group.** Two
   observations from different claims are put in one group if any rule
   below says they are about the same thing:
   - **R1, restates:** one claim `restates` the other (already in the
     schema).
   - **R2, same place:** code observations whose lines overlap in the same
     file; data observations with the same file, field, and selection;
     Methods observations quoting the same paragraph.
   - **R3, same label:** the value's name, subject, and unit match after
     small clean-ups (lower case, spacing).
   - **R4, same meaning (assistant):** given a short list of rows (claim
     ID, facet, value name, subject, unit, a few words of the statement),
     an assistant returns groups, each with a one-line reason naming the
     shared population and condition. The tool checks that every ID exists
     and that each group spans at least two claims. This is the only step
     that uses a model, and its groups pass the same checks as any other
     (0009).

3. **Comparison within a group is done by the tool**, by the rules
   compare already uses (0006):
   - numbers at the coarser of the two printed precisions;
   - bounds checked as stated (p < 0.05 and p = 0.03 agree);
   - strings exactly.

   Pairs within one claim are skipped; compare already covers them.

4. **A cross-claim finding is its own record**, kept in a separate list,
   not a `Finding`. A `Finding` belongs to one claim, and the existing
   checks stay as they are. A cross-claim finding holds:
   - two or more claim IDs;
   - status *Consistent* or *Differs* only;
   - the values as quoted, each with its manuscript anchor;
   - the grouping rule that joined them;
   - a neutral one-line summary (0004).

5. **Report.** Each cross-claim finding is shown on the card of every claim
   it involves, and listed briefly in the summary.

6. **Phasing.** R1–R3 are built first and run on the example audit. R4 is
   added only if the overlaps it would catch turn out to matter.

7. **Wrong cross-references** (design.md, open questions) are left out for
   now. They may later become a cross-claim check.

## Example (synthetic)

| Claims | Rule | Values | Basis | Status |
|---|---|---|---|---|
| R3.1.b, F4.2.a | R3 same label | "48 of 60 sessions"; legend "48 of 61 sessions" | exact | Differs |
| R2.4.c, R5.1.a | R1 restates | "slope 0.42"; "slope of 0.4" | reported precision | Consistent |
| R2.2.a, S1.3.d | R2 same place | both on `trials.csv`, field `rt`: "p < 0.01"; "p = 0.003" | inequality | Consistent |
| M2.1.a, M6.3.b | R3 same label | "lapse rate 2%"; "lapse rate 5%" | reported precision | Differs |

The first row would read: "R3.1.b and F4.2.a give the number of sessions
as 60 and 61."

## Why

Grouping keeps the work close to the number of observations, not its
square. Rules R1–R3 need no model, so the same record always gives the same
groups. Each status follows from the printed values and the rule that
joined them, so a reader can check it by hand (0007).

A separate stage keeps compare unchanged and independent of order. A
separate record keeps the one-claim `Finding` simple, and every check built
on it stays valid.

## Open questions

1. **How strict R3 should be.** Small clean-ups may miss labels that mean
   the same thing ("sessions" and "number of sessions"), and looser
   matching may join values about different populations. To be settled on
   the example audit.

## Notes

- 2026-11-02: R1–R3 are built (`rigoraudit.crosscheck`). Choices made in
  building them:
  - **R3 needs a subject.** R3 joins two values only if both name a
    subject; a value with no subject is joined only by R1 or R2. Without
    this, every bare *p* in a paper would be one group. This settles open
    question 1 for now; the example audits may still show it too strict.
  - **R2 needs the same label too.** Values on the same code lines are
    compared only if their name, subject, and unit match, because one
    function often serves several conditions. R1 allows one of the two
    values to have no subject.
  - **Two bounds** agree if some value meets both (p < 0.05 and p < 0.001
    agree; p > 0.1 and p < 0.05 differ).
  - **Where the findings are.** `rigoraudit check` (and `rigoraudit
    crosscheck`) write them to `work/crosscheck/findings.json`. The report
    works them out from the record it shows, so it is never out of date;
    no stage is added to the guided audit, which runs them as part of the
    check.
- 2026-11-02: R1–R3 tried on a real audit. Most groups they made, and every
  group whose values differed, joined values about different things: one
  code loop serves several tasks or populations, one name and subject
  leave out the condition, list numbers ("1)", "2)") were taken as values,
  and two cases of one formula share a label. The one known disagreement
  was missed, because its two claims name the count differently and share
  no code. So, changing item 6, **R4 is built, and every group passes
  through it**: R1–R3 only propose candidate groups, and an assistant
  confirms, splits, or sets aside each one (with a reason) and adds groups
  the rules miss. The tool compares every pair within a confirmed group
  from different claims and different printed text. This adds a step to
  the guided audit, `crosscheck`, after compare, and removes the command
  `rigoraudit crosscheck`; the check writes the findings. The answer keeps
  the values it was given, and is used only while the record gives the
  same ones.
- 2026-11-03: Two changes after reviewing a real audit. **A value printed
  as approximate** ("∼50") agrees with another within 10% of it, the
  default for hedged wording in [0006](0006-comparison-rules.md); before,
  it was compared as exact, so "∼50 per group" and 52 differed. **The
  reviewer can Confirm or Override a cross-claim finding**, as a finding
  ([0010](0010-provenance-and-review.md)); the entry names the finding's
  ID and a fingerprint of its status and values, and is stale if they
  change.
