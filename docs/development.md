# Development

How to change the tool itself, and the rules its code and documentation
follow.

## Set up, once per clone

You need [uv](https://docs.astral.sh/uv/); it installs Python 3.12 or later
if needed.

```
uv sync --extra api
scripts/install-hooks
```

`uv sync` creates the project's environment (`.venv/`) with the package and
the development tools, pytest and ruff; `--extra api` adds Anthropic's
package, which the tests of API mode need (without it they are skipped).
`scripts/install-hooks` sets up the
check that keeps audit content out of the repository (below).

## After each change

```
uv run ruff check --fix
uv run ruff format
uv run pytest
```

These fix and report lint problems, format the code, and run the tests. The
tests include rebuilding the example audit
([examples/example-audit/](../examples/example-audit/README.md)) and
comparing it with what is committed; after a change that alters its output,
run `examples/example-audit/rebuild.sh` and commit the result. The same
checks run on Linux, macOS, and Windows at each push
(`.github/workflows/tests.yml`), without Anthropic's package.

## Keeping audit content out

The repository is meant to be public; the audits are not. Nothing from an
audit may be committed: no quotes, values, names, file or script names,
claim IDs, or counts of claims and findings from a real record, and no
materials. Examples in the docs, docstrings, tests, and commit messages are
made up. The hooks run `scripts/check_no_audit_content.py` on each commit,
commit message, and push, and refuse any that contain:

- a term listed in a `release_terms.txt` file, in a workspace or in the
  folder that holds the workspaces (author names, subjects, distinctive
  values; one per line);
- eight or more words in a row that also appear in a workspace's paper
  text, record, or code;
- a material file: a PDF, data or archive file, or any file over 1 MB.

The check looks for workspaces in `../audit_examples/`, beside the
repository, or in the folders listed in `RIGORAUDIT_PRIVATE_ROOTS`. If it
finds none, it checks file types only and says so. To check every tracked
file at any time, run `uv run python scripts/check_no_audit_content.py`.

If the check refuses something, rewrite it as a made-up example. If it is
wrong (a false positive), say so rather than working around it; never skip
the hooks with `--no-verify`.

## Working in an audit's workspace

A coding assistant that helps develop the tool also works in real audits.
What it may open depends on the job it is doing:

- **Doing a task, as the audit's assistant:** the task's files and
  `materials/` only, as a person pasting into a web chat would see. It
  writes only its reply, to the inbox. Anything more makes the audit a
  weaker test of the tool.
- **Developing the tool or reviewing results:** the record through the
  tool's own outputs (task files, `work/checks.json`,
  `work/materials/files.md`, the report), not the files in `work/` and
  `record/` themselves, which are long. `rigoraudit show <claim>` gives
  one claim's part of the record. Needing one of those files is a sign
  the tool lacks a view; add the view.
- **Changing an answer:** through the tool only. To redo a task, delete its
  accepted answer and import the reply again; never edit the saved files
  by hand.

Nobody opens the paper's PDF; the tool's extracted text stands in for it.
The project settings block reading PDFs; block reading `work/**/*.json` in
your own `.claude/settings.local.json`.

## The code

| Module | Does |
|---|---|
| `cli` | The `rigoraudit` command |
| `guide` | The guided audit, `rigoraudit audit`: works out which steps are done and takes the user through the rest, with the same functions as the separate commands |
| `clipboard` | Carries a task to a chat and its reply back, on the computer's clipboard |
| `api` | Optional: sends a task to Claude with the user's own API key (API mode) |
| `settings` | Reads the manifest (`audit.yaml`): the paper, the code and its commit, the checksums, the audited sections, and other settings |
| `osf` | Downloads an OSF project's files, checking each against OSF's checksum |
| `materials` | Lists every file in the materials, what each data file holds, and what the code reads (`rigoraudit materials`) |
| `extract` | Writes the paper's text, outline, and paragraphs, from the publisher's XML or the PDF |
| `grobid` | Optional: reads the PDF with a GROBID server the user runs |
| `breaks` | For paragraphs cut from a PDF: the breaks the tool is unsure of, handed to an assistant, and its decisions applied |
| `paragraphs` | Reads the extracted paragraphs, gives each a label (`R1.2`), and says which are in the audited sections |
| `sections` | Finds the paper's major sections, for laying out the report |
| `equations`, `numbering`, `pictures` | Display equations: their numbers and keys, their pictures as printed, and the page showing each beside the auditor's typed-in LaTeX (drawn with KaTeX, bundled in `katex/`) |
| `handoffs`, `instructions` | What every assistant step shares: the written instructions, reading replies, and the files handed off and accepted |
| `docs`, `segment`, `decompose`, `trace`, `derive`, `compare`, `crosscheck`, `header` | The assistant steps: what each hands off, how each reply is checked, and what is built from accepted replies (record items, derivation scripts run, the record itself, cross-claim findings, the report's header) |
| `codeindex` | An index of the code, for an assistant that cannot browse it |
| `schema` | The record: claims, observations, findings; computes statuses |
| `stats` | Works out p, N, and effect size from each test the paper prints, compares the test's settings and assumption checks that trace cites and the N and unit of analysis that derive saves, and builds those findings; gives the lines shown beside each test (what it assumes, facts about its data) |
| `values` | Writes and reads the outputs of an audit's derivations |
| `matlab` | Starts MATLAB from a derivation script |
| `verify` | Checks every quote, value, and checksum in a record against the materials |
| `coverage` | Lists checkable statements in the audited text that no claim covers |
| `check` | `rigoraudit check`: runs `verify` and `coverage` on a workspace and saves the results |
| `status` | The generated paragraph on where an audit stands |
| `review` | The review log, and the reviewed record (the draft with the log applied) |
| `report` | The report page, `rigoraudit report` |
| `show` | One claim's part of the record, as text, `rigoraudit show` |
| `server` | The review page, `rigoraudit review` |
| `feedback` | The feedback report each run writes, which only the user sends |
| `words` | Wording shared by the tool's messages |

## Principles

These hold for every change.

**Documentation**

- Every document and docstring describes the code as it is now. A change in
  behavior updates the README, the [user guide](guide.md),
  [design.md](design.md), and the docstrings in the same commit.
- Write for a scientist who is not a programmer: plain words, short
  sentences, and as few words as do the job. Explain a term once (the
  guide's glossary) and use it the same way everywhere.
- Each fact has one home. The README says what the tool is and how to start;
  the guide, how to use it; design.md, how it works; the decision records,
  why. Link rather than repeat.
- Accepted decision records are not rewritten: add a dated note, or a new
  decision that says which one it replaces ([decisions](decisions/README.md)).

**What the user sees**

- Every question says what is asked and what pressing Enter does. Every
  message about a problem says what is wrong and what to do next, in a
  sentence or two. A mistake in the user's files gets a message, not a
  traceback.
- Output is short: counts first, then each problem, then the next step.

**Code**

- No legacy code and no backward compatibility until the first release:
  when a format or layout changes, update the workspaces and remove the old
  path. Remove code nothing uses.
- One way to do each thing. The workspace's paths are fixed, and settings
  that belong to an audit live in its manifest, not in command options.
  Shared helpers live in one place (`schema.Frozen`, `words.plural`).
- Efficient in time and in tokens: no loop over paragraphs or claims inside
  another such loop without need, and a handoff carries only what its
  assistant needs.
- Readable: names that say what things are, a docstring on every module and
  public function, and comments that say why rather than what. Match the
  style of the code around a change.
- New behavior gets a test. Test examples are made up.

**Workspaces**

- Every workspace, the example included, follows the layout in the guide
  ([The workspace](guide.md#the-workspace)) and has a `README.md` that says
  what is in it, why, and how to rebuild it.
- A workspace holds only what its audit needs: no backups of earlier
  versions, no outputs of scripts that are gone, and no second script for
  something a command does.

## Design records

[design.md](design.md) describes the design as it stands. Each design
decision has a record in [decisions/](decisions/README.md).
[release.md](release.md) has the steps for publishing the tool.
