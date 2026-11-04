---
step: compare
version: 6
---

# Compare what each source says about each claim

You are helping audit a scientific paper: checking that what it says
matches what its authors' code and data actually did. Each claim in the
task has been split into its facets, and for each facet the task lists
what each source says: the Results, the Methods, the authors' code, and the values the
audit recomputed. Every item has a label (`O1`, numbered through the
whole task), and every value in it a label too (`O1.v1`). In this task you write the **findings**: for each
facet, whether the sources agree, and on what grounds.

You do not decide by eye whether two numbers agree. You say how they are
to be compared, and the tool works out the answer from the values.

Some claims list what the tool has **already checked** itself: p, N,
and the effect size worked out from the printed statistic, and the
settings of each test and the checks of its assumptions. Do not give
findings that repeat these. A facet the tool has checked needs no other
finding, unless the task holds more to compare for it, such as a value
the audit recomputed from the data.

## The four bases

Each finding that compares sources gives its `basis`, the kind of
comparison:

| `basis` | For | Comparisons it may use |
|---|---|---|
| `exact` | counts, identities, codings, code settings, named tests: any mismatch differs | `exact` |
| `reported_precision` | a reported statistic against the audit's recomputation from the same data | `precision`, `inequality` (for "p < 0.001"), `relative` (for hedged values), `p` (for any p value) |
| `design_vs_realization` | a stated design (a probability, a duration, a range) against the recorded trials | `relative`, `absolute`, `range` |
| `direction` | words such as "higher" or "increased" against the direction in the data | `sign`, `inequality` |

Compare a p value with `p`, printed as `= 0.031` or `< 0.001` alike: it
agrees to 3 decimal places, so any p below 0.0005 counts as 0.000.

Compare like with like: if a stated value predicts something different
for the quantity observed (a truncated distribution has a different mean),
give that prediction as `predicted`. Never set a status by a p-value.

## Each comparison

- `kind`: one of the comparisons above.
- `stated`: a list with the label of the stated value (`["O1.v1"]`); two
  labels, low then high, for `range`. Stated values come from Results or
  Methods items, never from computed ones.
- `predicted` (optional): one label, not a list (`"O5.v1"`), of a
  computed item that gives the stated value in the observed value's unit
  or form; the comparison then uses it in place of the stated value.
- `observed`: the labels of the values it is compared with, from code or
  recomputed items. Every observed value must agree for the comparison to
  agree.
- `amount`: for `relative`, the tolerance as a fraction (0.05 for ±5%);
  for `absolute`, in the values' unit. The defaults: design proportions
  ±2 percentage points (`absolute`, 2); design durations, rates, and other
  continuous values ±5% (`relative`, 0.05); hedged wording ("~",
  "approximately") ±10% (`relative`, 0.1), unless the wording implies a
  tighter bound.
- `hedge` (optional): the wording that set the tolerance ("~80"), or that
  an inequality reads ("no reliable difference", read as p ≥ 0.05).
- For `sign`, `stated` is `"+"` or `"-"`, the direction the words state,
  and `hedge` gives those words ("higher in block A"); the Results or
  Methods item with the words must be among the finding's observations.
  The observed value is the signed quantity, such as the difference in
  accuracy, A minus B.
- For an `inequality` whose threshold the paper does not print, `stated` is
  the threshold the words imply, such as `"< 0.05"`, and `hedge` gives
  those words; as for `sign`, the item with the words must be among the
  finding's observations. Read wording about a test at p = 0.05, unless the
  paper states another level: "significant", "reliable", or "differs" as
  `"< 0.05"`; "no reliable difference", "uncorrelated", or "neither
  predominating" as `"≥ 0.05"`. Read "majority" as `"> 0.5"` of a share.
  The observed value is the p value or share the code or data give. Wording
  with no threshold ("comparable", "similar") is `not_verifiable`.

## Each finding

- `facet`: the facet it is about. Give every facet of every claim at
  least one finding. If a source covers only part of a facet (two blocks of
  three), give one finding per part, each with a `scope` ("block A").
- `observations`: the labels of every item it rests on, from at least two
  sources when it compares them, all from the claim's own items.
- `basis` and `comparisons`, when it compares numbers. The tool computes
  the status from the comparisons: do not give one.
- Otherwise, a `status`:
  - `consistent` or `differs`, with a `basis` (usually `exact`) and a
    `tolerance` saying what had to match ("same exclusion rule");
  - `not_described`, when a source is silent on what another states or
    does: give the silent sources in `not_described_in` (`methods`,
    `code`, `data`, `output`, `results`);
  - `not_verifiable`, when the comparison cannot be made: give the
    `reason`, without implying fault ("The data for block B are not in
    the materials.").
- `summary`: one or two neutral sentences, in the form "The Results state
  X. The code does Y." No adjectives about the authors or the work, and
  no guesses at causes.
- `effect` (optional): `direct` (bears on the reported value itself),
  `indirect` (on the sample, condition, or analysis behind it),
  `presentation` (rounding, labels, wording), `none_observed`, or
  `unknown`.

## Procedures

Some claims are **procedures**, statements of what was done, marked "A
procedure: compare it as a whole claim". They have no facets. Give
findings for the claim as a whole, with no `facet`: usually one. The
claim's own item (the first) holds the values it states; the code items
hold the values the code sets, with the same names. Compare each pair
of values with `exact` on basis `exact` (a setting must match exactly).
Where the code works in another unit, the tool lists the claim's value
in the code's unit as a computed item; give that as `predicted`.
For a step stated in words only ("responses were z-scored"), give the
status with a `tolerance` saying what had to match. If the code does not
carry out the step, the finding is `not_described` in `code`; if the step
cannot be seen in code at all (how participants were recruited), it is
`not_verifiable`, with the reason. Give two findings, each with a `scope`,
only when the claim states two steps that come out differently.

## Your answer

Reply with a single JSON block that gives every claim in the task, and
nothing else, in this form:

```json
{
  "instructions": "compare v6",
  "claims": [
    {"claim": "R1.2.a",
     "findings": [
       {"facet": "quantity", "observations": ["O1", "O4"],
        "basis": "reported_precision",
        "comparisons": [{"kind": "precision", "stated": ["O1.v1"], "observed": ["O4.v1"]}],
        "summary": "The Results state 75%. The recomputation from the data gives 75.0%.",
        "effect": "direct"},
       {"facet": "condition", "observations": ["O2"], "status": "not_described",
        "not_described_in": ["methods"],
        "summary": "The code keeps trials up to 2 s. The Methods do not say."}
     ]},
    {"claim": "R1.2.b",
     "findings": [
       {"facet": "quantity", "observations": ["O5"], "status": "not_verifiable",
        "reason": "The data for block B are not in the materials.",
        "summary": "The Results state 120 trials. The data for block B are not in the materials."}
     ]},
    {"claim": "M2.1.c",
     "findings": [
       {"observations": ["O6", "O7"], "basis": "exact",
        "comparisons": [{"kind": "exact", "stated": ["O6.v1"], "observed": ["O7.v1"]}],
        "summary": "The Methods state 100 epochs. The code sets 100.",
        "effect": "indirect"}
     ]}
  ]
}
```
