# 0015 — Statistical tests: check each reported number against the others and the code

**Status:** accepted (2026-11-02)

## Problem

A reported test, such as "t(22) = 2.10, p = 0.047, d = 0.90, N = 24",
prints several numbers that must agree with each other, with the Methods,
and with the code that produced them. The tool checks none of this today.
Decompose copies a test as one value, usually its p. Trace can cite the
test function but nothing compares its settings with the text. Derive can
recompute a test from the data, but only where the data are shared and a
script is written for it.

Many errors need no data to find. A p that does not follow from its
statistic and degrees of freedom, degrees of freedom that imply a different
N from the one stated, a one-tailed test described as two-tailed, or a
correction named in the Methods and absent from the code: each can be seen
by setting two sources side by side.

There is also no way to record such a check. An observation the audit
computes must today come from the data (`Obtained.RECOMPUTED` is allowed
only for a data source), so a p worked out from the printed text has
nowhere to go.

## Decision

This decision covers **Phase 1: checking sources against each other.** It
uses the four statuses and the comparison bases of
[0006](0006-comparison-rules.md) and adds no stage. Whether a test was the
right one to use is Phase 2 (see below).

1. **Decompose copies each reported test as one structured test report:**
   the test as named, the statistic (t, F, χ², r, z, U, W), its degrees of
   freedom, p as printed (with its relation, `=` or `<`), N, the tails if
   stated, and the effect size as printed. It copies only and works nothing
   out. A part the text does not print is left empty.

2. **A new way of obtaining an observation: *computed*, worked out by the
   tool from values printed in the manuscript.** It is allowed for Methods
   and Results sources. The tool, not a model, computes p from the printed
   statistic and degrees of freedom, for t, F, χ², r, and z first, and
   compares it with the printed p on the *reported precision* basis
   (inequalities checked as stated). A test the tool cannot compute from
   the text is *Not verifiable*, with the reason.

3. **Degrees of freedom imply N.** For an independent-samples t test, N is
   df + 2; for a paired test, df + 1. The implied N is compared exactly
   with the N stated in the text and with the N behind the derivation's
   recomputed test, if there is one. When the design (paired or not) is
   not known, the comparison is *Not verifiable*.

4. **Effect sizes are computed from the statistic and N:** d from t, r from
   t and df, partial η² from F and its degrees of freedom, and compared
   with the printed effect size at its precision. When the formula depends
   on a design the text does not settle (which d, paired or not), the
   comparison is *Not verifiable*, with the reason.

5. **Trace cites the test function and its settings:** paired or not,
   tails, equal or unequal variances (Welch), and any correction. Each
   setting is compared exactly with the text. A setting that only the code
   shows is *Not described*.

6. **Unit of analysis.** For each test it recomputes, derive saves the N
   and what one observation is (a trial, a session, a cell, an animal).
   Both are compared exactly with the population the text states.

7. **Corrections for multiple tests.** A correction stated in the Methods
   is compared, claim by claim, with what the claim's code applies.
   Counting the tests in a section, to judge whether a correction was
   needed, is left for later.

8. **Bootstrap and permutation tests.** Their p cannot be worked out from
   the text. Trace compares the settings in the code with the text: the
   number of resamples, what is resampled (which ties to item 6), the
   method for the confidence interval, and whether a seed is set. A rerun
   from the data gives a slightly different p each time, so its comparison
   needs a tolerance from the resampling error (open question 1).

9. **Each test's card says what the test assumes.** The tool keeps a fixed
   table of the assumptions of each test it knows. For example, a t test
   assumes independent observations, roughly normal group means, and,
   unless Welch's version is used, equal variances. A rank test assumes
   independent observations and, to compare medians, groups of the same
   shape. The card prints the line as context, with no status. Items 5 and
   6 already compare two of these assumptions with the text: equal
   variances (Welch or not) and independence (the unit of analysis).

10. **Whether the authors addressed each assumption.** Trace looks in the
    Methods and the code for a check of the assumption (a test of
    normality or of equal variances, a plot) or a stated reason for the
    choice of test ("a rank test, because the data were skewed"). This
    is about what is written, not whether the assumption holds:
    - the text and the code name the same check: *Consistent* (exact);
    - they name different checks: *Differs* (exact);
    - the text names a check that the code does not show: *Not
      verifiable*, since the check may have been run outside the shared
      code;
    - only the code shows a check, or neither addresses the assumption:
      *Not described*.

11. **Plain facts from the data, where derive has them.** For each test it
    recomputes, derive saves the values in each group, and the tool prints
    beside the test: N in each group, the ratio of the largest variance to
    the smallest, the skew of each group, the share of tied values (for a
    rank test), and, for bounded values such as proportions or counts,
    the share at the floor or ceiling. These are context: they set no
    status and carry no threshold, and the reader judges. A test of
    normality, by the authors or the audit, is shown the same way and
    never sets a status (0006 rule 3): with few values it misses real
    departures, and with many it flags trivial ones.

## Example (synthetic)

| Claim | Check | Basis | Values | Status |
|---|---|---|---|---|
| R2.1.a | p from t(22) = 2.10, two-tailed | reported precision | printed 0.047; computed 0.0474 | Consistent |
| R2.1.b | p from F(2, 40) = 3.10 | inequality | printed p < 0.01; computed 0.056 | Differs |
| R2.1.a | N from df, independent t | exact | stated N = 26; implied 24 | Differs |
| R2.1.a | d from t and df, equal groups | reported precision | printed 0.90; computed 0.895 | Consistent |
| R2.2.a | paired or not | exact | text "paired"; code `ttest_ind` | Differs |
| R2.2.a | tails | — | text silent; code `alternative="greater"` | Not described |
| R2.3.a | unit of analysis | exact | text "12 animals"; derivation N = 240 sessions | Differs |
| R2.4.a | correction | exact | Methods "Bonferroni"; code none | Differs |
| R2.5.a | permutations | exact | text 10,000; code 1,000 | Differs |
| R2.6.a | p from W = 31 | — | N not printed | Not verifiable |
| R2.1.a | normality addressed | — | text silent; code silent | Not described |
| R2.2.a | normality addressed | exact | text "Shapiro–Wilk"; code `shapiro` | Consistent |
| R2.7.a | equal variances addressed | — | text "Levene's test"; not in the code | Not verifiable |

For R2.1.a the card would also show, with no status: "Assumes independent
observations, roughly normal group means, equal variances. Data: N = 12
and 12; variance ratio 3.1; skew 0.4 and 1.8."

## Why

These checks find errors that are common in published papers and need only
what the audit already reads: the text, the code, and, where shared, the
data. Each status follows from values set side by side, by rules a reader
can apply by hand, so they fit 0004 (the report leaves judgment to the
reader) and 0007 (statuses are computed).

The new kind, *computed*, keeps the evidence honest. A p worked out from
the printed statistic shows only that the text agrees with itself, which is
weaker than a test recomputed from the data, and the claim card should say
so.

Assumptions are handled the same way. Whether an assumption holds well
enough is a judgment, and a test of it (normality above all) depends on
the sample size more than on the departure. So the audit says what each
test assumes, whether the authors addressed it, and what the data look
like, and leaves the judgment to the reader. Whether a departure changes
the answer is the question for Phase 2.

Computing p and effect sizes is done by the tool, with SciPy (already a
dependency), not by a model, so the same text always gives the same
result (0009).

## Open questions

1. **Tolerance for a resampled p.** One option: the binomial standard
   error of p for the number of resamples, √(p(1 − p)/n), times a fixed
   factor. For p = 0.03 that is about ±0.0017 per error at 10,000
   resamples and ±0.0054 at 1,000. The factor, and what to do when the
   code sets no seed, are to be settled.
2. **Which tests come after t, F, χ², r, and z,** such as rank tests whose
   p needs the group sizes. To be chosen from what the example audits use.
   The table of assumptions (item 9) grows with the same list.

## Later: Phase 2

Judging a test against rules (whether a robust alternative gives the same
answer; whether the test suits the data) is a separate decision. It goes
beyond 0004, which leaves judgment to the reader, so it would need its own
label and its own section of the report. Before Phase 2, count
which tests the example audits use, and keep the counts in those
workspaces.

## Notes

- 2026-11-02: Items 1–4 are built (`rigoraudit.stats`). Two choices made
  in building them:
  - **Rounding of the printed statistic.** A printed t of 2.10 stands for
    any t from 2.095 to 2.105. Each value worked out from a statistic is
    stored with the lowest and highest it can be over that range (a
    comparison's *span*), and it agrees if any value in the span agrees,
    as statcheck does. Without this, rounding alone could give *Differs*.
  - **The tool as drafter.** The findings of items 2–4 are drafted by the
    tool, a third kind of drafter beside a person and a model (0010), dated
    when the test was copied.

  When the text does not state the tails, p is taken as two-tailed for t,
  z, and r, and the finding says so. A d worked out from an independent t
  assumes equal groups, and says so too.
- 2026-11-02: Items 5, 7, 8, and 10 are built. The trace assistant cites
  where the Methods and the code state each setting and each check of an
  assumption, and names what each says in fixed words; the tool sets the
  status, so these findings too are drafted by the tool. A setting the
  Results paragraph states (paired, tails) counts as the text. Two choices
  made in building them:
  - A setting the text states but whose code was not found is *Not
    verifiable*. A correction the code does not apply and the text does not
    mention gives no finding.
  - The compare handoff lists what the tool has checked, and the assistant
    does not repeat it, so p is worked out from the printed statistic once.
    A facet the tool covered needs no finding from the assistant.

  Open question 1 (tolerance for a resampled p) is still open: the settings
  are compared, but no resampled p is yet rerun from the data.
- 2026-11-02: A temporary bridge for audits begun before items 1 and 5.
  Their decompose and trace answers have no tests, and decompose cannot
  simply be redone: derive numbers each claim's values in decompose's
  order, so a fresh split could renumber them under replies already
  written. Until such audits are caught up, decompose writes, for each
  answer from before tests, a handoff that asks only for the tests of the
  same claims; trace does the same for test settings. The reply passes the
  step's usual checks and is merged into the old answer, whose facets stay
  as they are. This code is marked temporary and will be removed in its
  own commit, with a note here.
- 2026-11-02: Items 6, 9, and 11 are built, in derive (instructions v4).
  For each test its script recomputes, a derive reply names the keys
  where the script saves N, what one value is (in fixed words: trial,
  block, session, cell, animal, participant, other), and, if it can, each
  group's values, with the text's words for the unit when the text states
  one. Choices made in building them:
  - The N in the data is compared with the N the text prints, not with the
    N the degrees of freedom imply: the implied N is worked out by the
    tool, not stated, so the two are compared only through the text.
  - The lines of items 9 and 11 are kept in the record as `context`, apart
    from the findings, since they have no status. The table of assumptions
    covers t (by design), F, χ², r (Pearson, or rank by the test's name),
    z, U, and W. The skew is the sample skewness; ties are shown for U, W,
    and tests named as rank tests; floor and ceiling only when the reply
    gives the bounds.
- 2026-11-02: The temporary bridge (note above) is removed. The one audit
  that needed it has its tests added to its old decompose and trace
  answers, so nothing else uses it. Answers from before tests now only
  appear in the guide's list of answers that followed older instructions;
  to redo one, delete it and run the audit again.
- 2026-11-04: Open question 1 is settled, and a test may be printed with
  p only.
  - **Every p is compared to 3 decimal places** (comparison kind `p`), or
    at the decimals shown if fewer, so any p below 0.0005 counts as 0.000,
    and a bound below 0.0005 (`p < 10⁻³⁰⁰`) is read as 0.0005. This applies
    to p worked out from a printed statistic too: a p printed far below
    0.001 is not taken at face value. It is looser than statcheck, which
    would flag a printed 0.0003 worked out as 0.0009.
  - **A resampled p.** A derive reply may name where its script saves the
    p of a test it reruns (instructions v5) and, for a bootstrap or
    permutation test, the number of resamples drawn. The comparison is
    widened by 2·√(p(1 − p)(1/n₁ + 1/n₂)), twice the standard error of the
    difference between two runs of n₁ and n₂ resamples. The authors' n is
    the one trace found in the code or the Methods; if neither states it,
    the rerun's n is assumed and the finding says so. No margin is added
    when the rerun runs the authors' code and trace found that it sets a
    seed. The compare assistant uses the same kind `p` for any p it
    compares (instructions v6).
  - **A test printed with p only** ("permutation test, p = 0.003") is
    copied by its name and p, with no statistic (decompose instructions
    v4). The tool has nothing to work p out from, so it gives no finding
    for that; the settings and a rerun's p are compared as for any test.
