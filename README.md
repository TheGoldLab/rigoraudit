# rigoraudit

Audits a scientific paper together with its code and data. The audit identifies every claim, along with its supporting evidence (Methods, code, and data), in the paper (**transparency**) and checks for agreement between each claim and its evidence (**consistency**).

Several stages of the audit can be (tediously) done by hand but are typically done with an AI assistant. These stages include extracting claims from the paper; parsing them into testable components; aligning them with appropriate sections of methods, code, and data; and running the relevant code. The remaining stages, involving cross-checking the claims and writing the report, are done by code included in this repository.

The result is a report that displays the manuscript text beside a card for each claim the paper
makes. Each card says what the Results, Methods, code, and data show for that
claim, including quoting the exact text, code lines, or values behind each statement. The card also indicates whether or not the claim is consistent across all those conditions, and if not how they differ. A human reviewer can add to (but not edit or replace) the record, for example to add context that might help explain mismatched claims (e.g., "expected variability across samples").

This tool has been designed and tested primarily using neuroscience studies and thus is likely to have quirks (e.g., what counts as a "result") specific to that domain. It also provides a way to have AI guide a user through a full audit but is intended to be used in a way that is not fully automated. Instead, human review is expected at multiple stages to check on and, if necessary, adjust how the specific set of claims for the paper are extracted and parsed. Moreover, the final report is purely descriptive and leaves judgment to the reader/reviewer.


## How an audit works

1. **Collect materials.** Put the paper, code, and data in one folder (the
   audit's *workspace*), unchanged, and list them in a manifest,
   `audit.yaml`. The tool lists every file, what each data file holds, and
   what the code reads, so nothing is taken as missing without a look.
2. **Extract information.** The tool takes the paper's text, paragraph by
   paragraph, from the publisher's XML file or from the PDF.
3. **Parse claims.** An AI assistant splits the text into claims, splits
   each claim into the parts that can be checked, and finds the Methods
   passages and code lines behind each. The tool writes the instructions and
   checks every answer against the paper and the code before accepting it.
4. **Re-derive claims.** Where a number has to be reproduced, a short script
   reruns the authors' code or recomputes it from the data.
5. **Record results.** Claims, evidence, and comparisons are assembled into
   one record. Whether sources agree is computed from the values, never
   typed in.
6. **Check claims.** The tool checks every quote, code line, checksum, and
   value in the record against the materials, and lists numbers and
   comparisons in the paper that no claim covers.
7. **Report and review.** The tool writes the report; a person reviews it in
   the browser, confirming or correcting each claim and finding, with a
   reason for each change.

The tool guides every step (`rigoraudit audit`), with whichever AI
assistant you have; the review in step 7 is yours. The
[user guide](docs/guide.md) covers every step.

## What works, and what does not yet

This is a first version, for testing. Every step above works from start to
finish and has been tried on real papers, but expect rough edges, and
please [report them](docs/guide.md#feedback). Known limits:

- **Cited results are not checked.** A claim that rests on another paper is
  marked as such, and the cited paper is not read.
- **Paragraphs from a PDF alone are a best guess.** With the publisher's
  XML they are exact, but its text can still differ from the printed page,
  and the quote check then reports a mismatch to look at.
- **A sentence continued after a full-page figure** is not found by the
  quote check.
- **Code:** Python, MATLAB, R, and Julia files and Jupyter notebooks are
  read. Files inside archives (`.zip`, `.tar.gz`) are listed but not read
  when tracing claims to code. A derivation script may be allowed to start
  MATLAB without asking; one that starts any other program waits for you to
  read it and agree.
- **Audits run only on a Mac so far.** The tests pass on Windows and Linux
  too, but no real audit has been run on them yet.

## Install

You need [uv](https://docs.astral.sh/uv/getting-started/installation/), a
free tool that installs Python programs. Then, in a terminal, from a copy of
this repository:

```
uv tool install --editable .
```

This puts the `rigoraudit` command on your path, so it can be run from any
folder. (Changes to the repository take effect without reinstalling.) To
let the tool send tasks to Claude itself with your Anthropic API key
(optional, and it costs money: see the guide's
[API mode](docs/guide.md#api-mode)), install it with that option instead:

```
uv tool install --editable '.[api]'
```

## Try it

A complete small audit of a made-up paper is in
[examples/example-audit/](examples/example-audit/README.md). To rebuild it
and open it in the review page:

```
examples/example-audit/rebuild.sh
rigoraudit review examples/example-audit
```

Then open http://127.0.0.1:8765/ in a browser. Press Ctrl-C in the terminal
to stop.

## Start an audit

```
rigoraudit audit my-audit
```

makes the folder `my-audit` with a manifest to fill in, and then takes you
through each step in order. Run it again at any time to pick up where you
left off. See the [user guide](docs/guide.md).

## Commands

Each command works on the current folder, or on the workspace you name last
(e.g., `rigoraudit check my-audit`). `rigoraudit <command> --help` gives the
details.

| Command | Does |
|---|---|
| `audit` | The guided audit: takes you through every step in order |
| `materials` | Lists every file in the materials, what each data file holds, and what the code reads |
| `extract` | Writes the paper's paragraphs, from the publisher's XML or the PDF |
| `handoff <step>` | Writes the files to give an AI assistant for a step: `breaks`, `docs`, `segment`, `decompose`, `trace`, `derive`, `compare`, `crosscheck`, or `header` |
| `import <step> <reply>` | Checks an assistant's reply and saves it if it passes |
| `record` | Builds the record, `record/record.json`, from the accepted answers |
| `check` | Checks the record against the materials, and lists what no claim covers |
| `show <claim>` | Prints everything the audit holds on one claim, as text |
| `report` | Writes the report page, `report/audit.html` |
| `review` | Shows the report in your browser, with review actions |
| `equations` | Shows each display equation as printed beside your typed-in version |
| `osf <link> <folder>` | Downloads an OSF project's files, checking each one |
| `feedback` | Shows where the feedback report is and how to send it (nothing is sent) |

## Documentation

- [User guide](docs/guide.md): every step of an audit, the workspace's
  layout, and the manifest.
- [Design](docs/design.md): the design as it stands, and
  [decisions](docs/decisions/README.md): why it is so.
- [Development](docs/development.md): changing the tool, and the rules for
  its code and documentation.
- [Feedback reports](docs/feedback.md) and [release](docs/release.md).

## License

Copyright (c) 2026, Joshua I. Gold. Released under the BSD 2-Clause License;
see [LICENSE](LICENSE). The package bundles KaTeX (`src/rigoraudit/katex/`),
which draws the maths on the equations page, under the MIT License; see
[its license](src/rigoraudit/katex/LICENSE).
