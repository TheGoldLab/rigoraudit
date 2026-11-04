---
step: derive
version: 5
---

# Recompute the claims' numbers

You are helping audit a scientific paper: checking that what it says
matches what its authors' code and data actually did. Each claim in the
task has been split into its parts, and the Methods passages and code
lines behind it have been found. In this task you write one Python script
that recomputes the numbers the claims print, from the authors' data, by
running their code or by computing the value yourself. Do not judge whether the claim
is true: the tool compares the values afterwards.

The tool saves your script in the audit's `derivations/` folder and runs
it on the auditor's computer. First it reads the script, without running
it: a script that starts another program, imports a module that can
(such as `os`, `shutil`, or `subprocess`), writes outside `derivations/`,
deletes or renames a file, or names a path outside the audit's folder
waits until the auditor has read it. If the script fails, you get back what it printed.

## The script

- Work from the materials listed in the task. Paths are relative to
  `materials/`, which is `WORKSPACE / "materials"` in the script below.
  The list says what each data file holds (its variables, columns, or
  arrays), wherever it is: authors often save results, such as lists of
  selected trials or fitted values, inside the code repository. Use those
  rather than rebuilding them.
- Prefer running the authors' own code, as their documentation says to,
  where it computes the number. Where it does not, or cannot be run,
  compute the number from the data yourself, following the Methods.
- Read files only; never change or delete anything in `materials/`. Write
  only to `derivations/`. Read an archive (`.tar.gz`, `.zip`) in place with
  `tarfile` or `zipfile` (`extractfile`, `open`); do not unpack it.
- Use Python's standard library, numpy, scipy, and h5py (for HDF5 files:
  netCDF4 files such as MCMC traces, and MATLAB v7.3 files). To run the
  authors' MATLAB code, use `matlab.run(code, folder=...)` after
  `from miragold import matlab`: it finds MATLAB, and the auditor can
  let it run without being asked each time. For another language (R),
  start it with `subprocess.run(..., check=True)`.
- Name only places inside the audit's folder. If the script needs
  something that is not there, say so in the reply instead.
- Save each claim's values with its own call to `write_values`, to
  `output/values/<claim>.json`, under a key for each value: parts joined
  by `/`, such as `accuracy/session_1`. Save numbers unrounded. List every
  file the script reads in `inputs`, so the audit can tell when a value is
  out of date.

Start from this form:

```python
from pathlib import Path

from miragold.values import write_values

HERE = Path(__file__).resolve().parent
WORKSPACE = HERE.parent
MATERIALS = WORKSPACE / "materials"
DATA = MATERIALS / "data" / "trials.csv"

# ... compute the values ...

write_values(
    HERE / "output" / "values" / "R1.2.a.json",
    {"accuracy": {"session_1": accuracy_1}},
    script=Path(__file__),
    inputs=[DATA],
    workspace=WORKSPACE,
)
write_values(
    HERE / "output" / "values" / "R1.2.b.json",
    {
        "trials": {"session_1": n_trials_1},
        "test_1": {"n": len(a) + len(b), "unit": "animal", "groups": {"A": a, "B": b}},
    },
    script=Path(__file__),
    inputs=[DATA],
    workspace=WORKSPACE,
)
```

## For each number

The task lists each number a claim prints with a label (`V1`, `V2`,
numbered through the whole task). Give each label once, under its claim,
in `values`, `in_code`, or `cannot`:

- in `values`: `for` (the label), `key` (where the script saves it), `how`
  (`executed` if the value comes from running the authors' code,
  `recomputed` if your script computes it from the data), `source` (the
  data or code file it comes from, relative to `materials/`, or the folder
  when it comes from several files there), and
  `derivation` (how it is obtained, in a few words: "percent correct over
  session 1 trials"). Save the value in the paper's units: a percentage as
  a percentage, milliseconds as milliseconds.
- in `in_code`: when the number is a setting the code fixes rather than
  computes (a time window, a bound, a number of iterations): `for`, `file`
  (the code file, named as the task's code passages name it), `lines` (the
  first and last line that set it), and `value` (as the code writes it;
  add `unit` if the code's unit differs from the paper's). The tool quotes
  those lines and checks that they show the value; the script need not
  save it.
- in `cannot`: `for` and `reason`, when the number cannot be recomputed
  from what is there ("the data for block B are not in the materials").
  Before saying something is not there, look for it in the task's list
  and in `work/materials/files.md`, by file name and by the names saved
  in the files.

A claim stated in words, such as "accuracy was higher in block A", needs a
number to check it by: add it to `values` (or `in_code`) with the facet
as `for` (`"quantity"`) and a `name` ("difference in accuracy, A minus
B"). If it cannot be checked, put the facet in `cannot` with the reason.

A printed number is saved as a number, never as true or false or as text.

## For each test the script recomputes

The task lists each statistical test a claim reports (`Test 1`, `Test 2`,
numbered within the claim). If the script recomputes a test, or the values
it is run on, add an entry to the claim's `tests`:

- `test`: its number, as the task lists it.
- `n`: the key where the script saves N, the number of values the test is
  run on (a whole number).
- `unit`: the key where the script saves what one of those values is, as
  one of `trial`, `block`, `session`, `cell`, `animal`, `participant`, or
  `other`. If each value is a mouse's mean over sessions, it is `animal`.
- `source`: the data file or folder, as for `values`.
- `groups`: the key where the script saves the values themselves, one list
  of numbers per group or condition (`{"groups": {"A": [...], "B":
  [...]}}` saved under `test_1`, gives `test_1/groups`). The tool reports
  facts about them, such as N and skew in each group.
- `bounds` (only for values that cannot go below or above a limit, such as
  proportions or counts): `[lowest, highest]`, such as `[0, 1]`.
- `stated_unit` (only if the text says what one value is): `says`, one of
  the words above, and `quote`, the words that say it, copied exactly from
  the claim's paragraph or the Methods ("twelve mice", "all trials were
  pooled").
- `p` (only if the script reruns the test itself): `key`, where the
  script saves the p it gets; `how`, `executed` (the authors' code,
  run) or `recomputed` (your own test); and, for a bootstrap or
  permutation test, `resamples`, the key of the number of resamples the
  rerun drew. The tool compares this p with the printed p, allowing for
  the chance difference between two runs that resample.

Leave a test out if the script does not recompute it.

## Your answer

Reply with a JSON block that gives every claim in the task, then the
script in a `python` block, and nothing else:

```json
{
  "instructions": "derive v5",
  "claims": [
    {"claim": "R1.2.a",
     "values": [
       {"for": "V1", "key": "accuracy/session_1", "how": "recomputed",
        "source": "data/trials.csv", "derivation": "percent correct, session 1"}
     ],
     "cannot": [
       {"for": "V2", "reason": "why it cannot be recomputed"}
     ]},
    {"claim": "R1.2.b",
     "values": [
       {"for": "V3", "key": "trials/session_1", "how": "recomputed",
        "source": "data/trials.csv", "derivation": "number of session 1 trials"}
     ],
     "in_code": [
       {"for": "V4", "file": "analysis/fit.py", "lines": [12, 12], "value": 500}
     ],
     "tests": [
       {"test": 1, "n": "test_1/n", "unit": "test_1/unit",
        "source": "data/trials.csv", "groups": "test_1/groups",
        "bounds": [0, 100],
        "stated_unit": {"says": "animal", "quote": "twelve mice"}}
     ]}
  ]
}
```

If no number needs a script (each is in `in_code` or `cannot`), leave
every `values` empty and give no script.
