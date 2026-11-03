---
step: trace
version: 4
---

# Find where the Methods and the code do what each claim says

You are helping audit a scientific paper: checking that what it says
matches what its authors' code and data actually did. Each claim below has
already been split into facets (what it states about the result, the
subjects, the analysis, the conditions, and the figure). For each facet,
find:

- **in the Methods:** the sentences that describe it, if any; and
- **in the authors' code:** the lines that compute or produce it, if any.

Some tasks list **procedures** instead: statements of what was done
("Trials were 500 ms long", "Each network was trained for 100 epochs").
These are not split into facets; trace each one whole (see *For each
procedure*).

Do not judge whether the paper is right, and do not run any code. Later
steps compare what you find. Report only what is there; saying that you
found nothing is a useful answer.

## Where the code is

The task below gives the code in one of two ways.

- **A link** to the authors' code repository, at the exact version the
  paper used. Browse it there. Use that version only, not the latest one,
  so that line numbers match. If you cannot open the repository or read
  its files, do not guess: answer with `no_access` (see below), and the
  tool will send an index of the code instead.
- **An index** of the code, at the end of the task: each file, how many
  lines it has, the functions it defines, and the line where each name is
  first set. Use it to choose the code you need, then ask for it (see
  *Asking for code*). The next task shows the lines you asked for, with
  their line numbers, and keeps showing them in later rounds. Cite only
  lines you have been shown.

## Asking for code

When you have an index, ask for the lines you need with `requests`: each
a `file` from the index and, usually, `lines` as `[first, last]`. Leave out
`lines` to ask for a whole file. Ask for at most 2000 new lines at a time,
choosing the functions that compute each facet, and the lines that load
the data and choose the subjects. Give the task's name (from the line
"Your task: ..." below) as `task`:

```json
{
  "instructions": "trace v4",
  "task": "trace-R1.2.a",
  "requests": [{"file": "analysis/fit.py", "lines": [30, 80]},
               {"file": "analysis/load.py"}]
}
```

You can ask again in later rounds, up to the round the task says is the
last. In the last round, answer with what you have been shown.

## For each facet

- `methods`: each Methods passage that describes the facet, with the
  paragraph's label, a `quote` copied exactly from that paragraph (same
  spelling, punctuation, dashes, and spaces; it must appear only once in
  the paragraph), and `states`, one short neutral sentence saying what it
  describes. Leave the list empty if the Methods say nothing about it.
- `code`: each place in the code that computes or produces the facet, with
  the `file` (its path in the repository, e.g. `analysis/fit.py`), the
  first and last line numbers as `lines`, the `quote`: those lines copied
  exactly, and `states`, one short neutral sentence saying what they do.
  Cite the few lines that do the work, not a whole file; up to about 30
  lines per place. Leave the list empty if you found no code for it.
- `notes` (optional): anything a reviewer should know, such as "the
  function is called with a different threshold in another script".

Give every facet of every claim, in the order given.

## For each procedure

A procedure is traced whole. Give, for the claim itself:

- `values`: each number the claim states about what was done, copied
  exactly as printed in the claim (with its unit, e.g. `500 ms`), and a
  short `name` (`trial duration`). Leave out numbers that only point
  elsewhere, such as equation, figure, or reference numbers, and anything
  that is not one number, such as a version (`4.2.0`) or a name: say
  those in `notes`, and the comparison treats them in words.
- `methods`: the Methods passages that describe the same step, as for a
  facet. If the claim is itself in the Methods, give other passages only,
  such as one that states it differently.
- `code`: the places in the code that carry out the step, as for a facet,
  each with `values`: every value those lines set that the claim states,
  copied exactly as the code prints it (`0.5`, not `500 ms`), with the
  same `name` as the claim's value. When the code works in another unit
  than the claim, give the code's `unit`, one of `ms`, `s`, `min`, `h`,
  `Hz`, `kHz`, `%`, or `fraction` (`"printed": "0.5", "unit": "s"` for a
  claim of 500 ms); the tool converts between them.
- `notes` (optional), as for a facet, such as "this step is done by
  hand, outside the shared code".

Leave `methods` and `code` empty where you find nothing.

## For each statistical test

Some claims list their tests ("test 1: t(22) = 2.10, p = 0.047"). For
each, give an entry in the claim's `tests` with its number as `test`, and:

- `settings`: each setting of the test that the Methods or the code state.
  Give `methods` (a paragraph and quote, as above) and `code` (file, lines,
  and quote, as above) where each states it; leave out the one that is
  silent. Each gives `says`, what it states, in one of these words:

  | `setting` | `says` |
  |---|---|
  | `design` | `independent`, `paired`, `one-sample` |
  | `tails` | `1`, `2` |
  | `equal_variances` | `assumed`, `not_assumed` (Welch's test) |
  | `correction` | `none`, `bonferroni`, `holm`, `sidak`, `fdr`, `tukey`, `other` |
  | `resamples` | the number, as printed or as set in the code |
  | `resampled` | `trials`, `sessions`, `subjects`, `cells`, `animals`, `other` |
  | `ci_method` | `percentile`, `bca`, `basic`, `normal`, `other` |
  | `seed` | `set`, `not_set` |

  For the code, give the setting the call uses, even when it is the
  function's default (`scipy.stats.ttest_ind` with no `equal_var` is
  `assumed`; with no `alternative`, `tails` is `2`). Give `correction`
  `none` only for code that applies none to this test. `resamples`,
  `resampled`, `ci_method`, and `seed` are for a bootstrap or permutation
  test.
- `assumptions`: for `normality` and `equal_variances`, each place where
  the Methods or the code check the assumption, or the Methods give a
  reason for the choice of test. `says` names the check: `shapiro_wilk`,
  `kolmogorov_smirnov`, `anderson_darling`, `dagostino`, `levene`,
  `bartlett`, `brown_forsythe`, `plot`, `reason`, or `other`. Leave the
  assumption out if neither addresses it.

Copy what the sources state; do not judge whether they agree. The tool
compares them.

## Your answer

When you are ready to answer for the claims, reply with a single JSON
block and nothing else, in this form:

```json
{
  "instructions": "trace v4",
  "claims": [
    {"id": "R1.2.a", "facets": [
      {"facet": "analysis",
       "methods": [{"paragraph": "M1.3", "quote": "exact text", "states": "one sentence"}],
       "code": [{"file": "analysis/fit.py", "lines": [40, 44], "quote": "exact lines",
                 "states": "one sentence"}]},
      {"facet": "population", "methods": [], "code": [],
       "notes": "Neither the Methods nor the code say how subjects were chosen."}
    ], "tests": [
      {"test": 1, "settings": [
        {"setting": "design",
         "methods": {"paragraph": "M1.4", "quote": "exact text", "states": "one sentence",
                     "says": "paired"},
         "code": {"file": "analysis/stats.py", "lines": [12, 12], "quote": "exact line",
                  "states": "one sentence", "says": "independent"}}],
       "assumptions": [
        {"assumption": "normality",
         "methods": [{"paragraph": "M1.4", "quote": "exact text", "states": "one sentence",
                      "says": "shapiro_wilk"}]}]}
    ]},
    {"id": "M2.1.c",
     "values": [{"name": "epochs", "printed": "100"}],
     "methods": [],
     "code": [{"file": "train.py", "lines": [12, 12], "quote": "n_epochs = 100",
               "states": "Sets the number of training epochs.",
               "values": [{"name": "epochs", "printed": "100"}]}]}
  ]
}
```

If you could not open the repository, answer instead:

```json
{"instructions": "trace v4", "task": "trace-R1.2.a",
 "no_access": "what happened, e.g. the link did not open"}
```

The tool will then send an index of the code. If the tool finds
problems with your answer, it will list them; correct them and send the
whole answer again.
