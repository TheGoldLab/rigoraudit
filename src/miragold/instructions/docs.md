---
step: docs
version: 1
---

# Read the authors' documentation before their code is run

You are helping audit a scientific paper: checking that what it says
matches what its authors' code and data actually did. Before the authors'
code is run, their documentation has to be read, so that the code is run
the way they said to run it. The task below gives each documentation file:
READMEs and other notes, files that list the software the code needs, the
text cells of each Jupyter notebook, and the opening comment of each script
that will be run.

For each file, say what it says under each of these headings:

| Heading | What it covers |
|---|---|
| `run` | Which scripts or commands to run, and in what order |
| `software` | The language and its version, toolboxes, packages, and their versions |
| `data` | What data is needed, where to get it, and where it must go |
| `settings` | Options, parameters, random seeds, and hardware (memory, GPUs) |
| `outputs` | What running it produces (files, figures, tables), and how long it takes |
| `problems` | Known problems, warnings, or steps that are not expected to work |

Do not judge the documentation, and do not run anything. Report only what
the file says.

## For each file

- `notes`: one entry for each thing the file says under a heading, with
  the `heading`, a `quote` copied exactly from the file (same words and
  punctuation; line breaks may be written as spaces), and `states`, one
  short neutral sentence saying what it means for running the code. A
  heading can have several notes.
- `says_nothing`: the headings the file says nothing about.

Every heading must appear for every file, either in a note or in
`says_nothing`, but not both.

## Disagreements

If a file disagrees with another file, or with what the code itself
clearly does (for example, a README that says a script makes one figure
when its opening comment says it makes another), add it to
`disagreements`: the `file`, a `quote` from it, and `states`, saying what
it disagrees with. Leave the list empty if you see none.

## Your answer

Reply with a single JSON block and nothing else, in this form:

```json
{
  "instructions": "docs v1",
  "files": [
    {"file": "code/README.md",
     "notes": [
       {"heading": "run", "quote": "Run main.py, then plots.py.",
        "states": "main.py runs first, then plots.py."},
       {"heading": "software", "quote": "Requires Python 3.11 and numpy.",
        "states": "Python 3.11 with numpy."}
     ],
     "says_nothing": ["data", "settings", "outputs", "problems"]},
    {"file": "code/main.py (opening comment)",
     "notes": [
       {"heading": "outputs", "quote": "Writes results/table2.csv.",
        "states": "main.py writes the data for Table 2."}
     ],
     "says_nothing": ["run", "software", "data", "settings", "problems"]}
  ],
  "disagreements": [
    {"file": "code/README.md", "quote": "Run main.py, then plots.py.",
     "states": "plots.py's opening comment says to run it before main.py."}
  ]
}
```

The `file` names are exactly as given in the task. If the tool finds
problems with your answer, it will list them; correct them and send the
whole answer again.
