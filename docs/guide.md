# User guide

How to audit a paper with rigoraudit, step by step. The [README](../README.md)
says how to install the tool and try the example audit first.

Contents: [What you need](#what-you-need) ·
[The guided audit](#the-guided-audit) ·
[1. Collect materials](#1-collect-materials) ·
[2. Extract information](#2-extract-information) ·
[3. Parse claims](#3-parse-claims) ·
[4. Re-derive claims](#4-re-derive-claims) ·
[5. Record results](#5-record-results) ·
[6. Check claims](#6-check-claims) ·
[7. Report and review](#7-report-and-review) ·
[Equations](#equations) ·
[Practical advice](#practical-advice) ·
[Feedback](#feedback) ·
[The workspace](#the-workspace) ·
[Glossary](#glossary)

## What you need

- The paper as a PDF, and the code and data in the versions the paper used
  (a git commit or archive for the code; checksums or a repository DOI for
  the data).
- If there is one, the article's XML file, beside the PDF
  ([Getting the article's XML](#getting-the-articles-xml)). It is optional,
  but worth the few minutes it takes to look.
- Whatever the authors' code needs to run (MATLAB, R, Python packages), if
  values are to be reproduced, and enough memory and disk for it.
- An AI assistant. A website chat (such as Claude in a browser) is enough:
  the tool gives it one task at a time and checks every answer. A coding
  assistant (such as Claude Code) opened in the workspace folder can do
  more on its own: read every material, try a derivation and fix it, or
  write the record by hand ([step 5](#5-record-results)).

## The guided audit

```
rigoraudit audit my-audit
```

takes you through the audit in order, and picks up where you left off each
time you run it. On a folder with no manifest, it makes the
[workspace's folders](#the-workspace) and a manifest, `audit.yaml`, to fill
in. Then it:

1. checks that the paper is in `materials/`, and downloads the authors'
   code from the repository the manifest names, at the version the paper
   used;
2. extracts the paper's paragraphs. Paragraphs cut from a PDF are a best
   guess, so it offers to stop for you to look them over, unless a coding
   assistant does the tasks;
3. asks once which kind of assistant will do the tasks: a chat in your
   web browser, a coding assistant on your computer
   ([With a coding assistant](#with-a-coding-assistant)), or none, so
   that the tool asks Claude itself, which costs money
   ([API mode](#api-mode)). Then it asks the assistant's name, for the
   record; the model is optional. If the authors' code includes MATLAB
   files, it also asks whether the assistant's scripts may start MATLAB
   without asking each time ([step 4](#4-re-derive-claims));
4. for each step that needs judgment (reading the authors' documentation,
   splitting the text into claims, splitting each claim into facets,
   finding the Methods and code behind each facet), puts each task on
   your clipboard to paste into the assistant's chat, and reads the reply
   you copy back. Every reply is checked; a reply with problems gets a note
   to paste back to the assistant, on the clipboard too. (Where the tool
   cannot use the clipboard, it gives you a file to paste or attach, and
   asks for the path of the reply you saved.)
5. for the claims with numbers, has the assistant write scripts that
   recompute them ([step 4](#4-re-derive-claims)), and runs each; a script
   the checks flag runs only once you have read it and agreed;
6. for every claim, has the assistant compare what the sources say, and
   builds the record from the answers ([step 5](#5-record-results));
   then has it say which values, printed in different claims, are about
   the same thing ([step 6](#6-check-claims));
7. if the audit has no `report/header.html` yet, has the assistant draft
   it from the manifest and the paper's first page
   ([The report](#the-report));
8. checks the record ([step 6](#6-check-claims)) and, if every check
   passes, writes the report ([step 7](#7-report-and-review)).

Press Enter at any question to stop, except while a task is on your
clipboard: there Enter means you have copied the reply, and `q` stops.
Every step is also a command of its own, described below.

### With a coding assistant

A coding assistant on your computer (Claude Code, Codex, Cursor) can do the
tasks without any copying. Once you have answered the guide's first
questions, tell the assistant:

```
Run rigoraudit audit my-audit and do the tasks it gives you.
```

When the assistant runs it, the guide lists the tasks waiting and where
each reply goes: `work/<step>/inbox/<task>.txt`. Each run checks every
reply in the inbox, keeps the good ones in `work/<step>/replies/`, writes
the problems with any other beside it (`<task>.problems.txt`) for the
assistant to correct (the list of tasks names those replies), and moves on
to the next step when one is done.

A script the assistant writes runs as soon as its reply passes the checks,
unless the script checks flag it ([step 4](#4-re-derive-claims)); starting
MATLAB is not flagged if you allowed it when the guide asked. A
flagged script waits for you: run `rigoraudit audit my-audit` yourself in
a terminal; it lists the scripts waiting and what was found in each, for
you to read, and asks once whether to run them.

### API mode

With an Anthropic API key (in `ANTHROPIC_API_KEY`) and the tool installed
with its `api` option (see the [README](../README.md#install)), the guide
can send each task to Claude itself instead of giving you files to paste.
It is off unless you choose it (answer 3) when the guide asks which kind
of assistant you will use. It costs a substantial amount: roughly a dollar or two per claim
on the default model, so hundreds of dollars for a whole paper, billed to
your API account (not a Claude subscription). The guide says so and asks
you to confirm before turning it on; a spending limit in the Anthropic
Console caps what it can cost. It asks before each step, and before running a script the checks flag. A reply
with problems is sent back to the model with the problems, up to three
times; after that, or if the API cannot be reached, you take over that
step by hand. Every reply is kept in `work/<step>/replies/`. The paper's
text and passages of the authors' code and documentation are sent to
Anthropic, and the API's charges apply. The model is set in the manifest:

```yaml
settings:
  assistant:
    model: claude-opus-5-5
```

A model asked this way cannot open the authors' repository, so the trace
step gives it an index of the code (as `code_access: index` does).

## 1. Collect materials

Copy the paper, code, and data into `materials/`, unchanged (large data can
be linked instead of copied). From then on nothing in `materials/` is
edited: the authors' code is run from a copy, or with its output paths
redirected, and anything the audit adds goes in `derivations/` or `work/`.

Then write the manifest, `audit.yaml` (an assistant can draft it): each
material, where it came from, its version and checksum, the gaps, and the
settings. The tool reads only a few entries; the rest is for people:

```yaml
materials:
  manuscript:
    path: manuscript/paper.pdf
    supplement: manuscript/figures.pdf  # optional (below)
  code:
    path: code
    repository: https://github.com/<owner>/<repo>
    commit: 0123abc...            # the version the paper used, 40 characters
  data:
    path: data
    files:                        # a checksum for each data file the record cites
      - path: data/trials.csv
        sha256: 0123abc...
gaps:
  - missing: The list of trials each figure uses.
    instead: Rebuilt from the selection rule in the Methods.
    claims: [R1.2.a, R1.3.b]
settings:
  scope: [Results, Figure, Table] # the audited sections (below)
```

Paths are relative to `materials/`. Any entry with both a `path` and a
`sha256` gives that file's checksum, which `rigoraudit check` compares the
file against. `settings: scope` lists the audited sections: each is matched
against the start of a paragraph's section, so `Results` takes every Results
subsection. Patterns can be more exact: `'Figure \d+ legend$'` takes the
legends of the main figures only. The default is the Results, figure
legends, and tables. The extract step ends by naming the paper's
sections, to copy from.

The guide (or `rigoraudit materials`) lists every file in `materials/` in
`work/materials/files.md`, wherever it is: data saved inside the code
repository too. For each data file it gives what the file holds: the
variables of a MATLAB file and the fields of each structure, the first row
of a table, the arrays of a NumPy archive, the keys of a JSON file; for an
archive (`.zip`, `.tar`, `.tar.gz`), it lists the files inside. It also
lists each file the code reads by a name written in the code, and says
whether that file is in the materials, is made by the code itself, or is
neither. Only the last kind is missing. Reads that build the file's name
while the code runs are counted but not followed, so check those by hand.

A gap is anything the audit could not run or check from the materials as
given: code the paper describes that is not included, functions the code
calls that are not provided, data or intermediate files not shared, a
script that stops partway. Each says what is `missing`, what the audit did
`instead` (a stand-in, a rerun, or nothing), and, if it affects particular
claims, which (`claims`). Before you record something as missing, look
for it in `work/materials/files.md`, by file name and by the names saved
in the files: authors often keep results such as selected units or fitted
values next to the code that made them. Add gaps as the audit finds them. The report
lists them at the top, and each claim's card links to the gaps that affect
it; `rigoraudit check` fails if a gap names a claim not in the record.

Some journals print part of the paper in a separate PDF: often the figure
supplements' legends, which the paper's PDF gives only as titles. Name that
file as the manuscript's `supplement`, and its text is searched too.

### Code on OSF

If the authors shared their code on OSF (osf.io) rather than GitHub, give
the project's link as the code's `repository` (no commit is needed) and the
guide offers the download, or run:

```
rigoraudit osf https://osf.io/<id>/ materials/code --list   # see what is there
rigoraudit osf https://osf.io/<id>/ materials/code          # download it
```

Files over 10 MB (usually data) are left out unless you add `--max-mb` or
`--all`. Every file is checked against OSF's checksum. Since OSF has no
commits, `osf_files.json` in the folder records what was downloaded
instead: each file's size, checksum, OSF version, and date, and the files
left out. If a download stops, run it again: files already there are not
downloaded again. Only the project's own OSF storage is read, not its
sub-projects or linked storage such as Dropbox.

### Getting the article's XML

Many journals make a second copy of each article as an XML file: plain text
in which every heading, paragraph, figure legend, and table is marked as
such. With it, the tool gets every paragraph exactly right. With the PDF
alone, it has to guess where paragraphs begin and end from how the lines
are printed, and on some layouts it guesses badly, leaving more for you to
check.

- **PubMed Central** (most NIH-funded and open-access papers). Find the
  article's PMCID under its title on PubMed (it looks like `PMC1234567`),
  and open this address in a browser, with your PMCID in both places:
  `https://pmc-oa-opendata.s3.amazonaws.com/PMC1234567.1/PMC1234567.1.xml`.
  If the page says `NoSuchKey`, PubMed Central does not share that
  article's XML; try the journal.
- **PLOS journals:** the article page's Download menu has an "XML" link.
- **bioRxiv:** there is no link on the page, but bioRxiv makes the XML for
  every version of a preprint. Ask your assistant to get it for the version
  you are auditing, from `https://api.biorxiv.org/details/biorxiv/` followed
  by the preprint's DOI (the `jatsxml` entry for each version).

Put the file in `materials/manuscript/`, beside the PDF, as the only `.xml`
file there. It must be the same version as the PDF. PubMed Central often
has only the *author manuscript* (the accepted text before the journal's
copyediting), which can differ in small ways; the tool checks every
sentence against the PDF and lists those it cannot find. If it lists many,
the two are different versions: remove the XML and use the PDF alone. Some
journals (the Journal of Neuroscience, for one) are free to read in PubMed
Central but do not share their XML, and older papers often have none.

## 2. Extract information

```
rigoraudit extract
```

(the guide runs it for you) writes, in `work/extract/`:

- `published.txt`: the PDF's text, page by page. Every quote in the record
  is checked against it. A supplement's pages follow the paper's, numbered
  on from them and marked with the file's name (`=== PAGE 31
  (figures.pdf) ===`); the check and the report name them as in that file
  ("page 1 of figures.pdf").
- `outline.json`: the section headings; the report is laid out by them.
- `paragraphs.json`: the paragraphs, in reading order, each with its
  section (`Results › Learning`), its number in the section, its pages
  (and, if it runs onto another page, where in its text each page starts,
  so each quote names the page it is printed on), and its text. Each
  paragraph gets a short label, such as `R1.2` for the second
  paragraph of the first Results subsection, and claim IDs are built from
  it (`R1.2.a`).

With the XML, the paragraph breaks are exact, but its words can still
differ from the printed PDF, and quotes are checked against the PDF.
Where the XML only leaves out a few characters the PDF prints (a "∼"
before a number, a "θ̂", an item's "2.", or a formula it has only as a
picture), the tool puts them in from the PDF and lists the sentence as the
XML had it under `from_pdf`. Any other
sentence not found in the PDF is listed under `not_in_pdf`: check those,
and fix the paragraph before segmenting. With the PDF alone, the breaks between
paragraphs are a best guess: open the file and fix any paragraph that was
split or run together before going on. Do it before segmenting, since claim
IDs follow the paragraph numbers. If you find the XML later, put it beside
the PDF and run `rigoraudit extract --replace`; without `--replace` an
existing paragraphs file, which may hold your corrections, is left alone.
Extracting again after later steps is safe as long as the paragraphs keep
their numbers: the next time the record is built (`rigoraudit record`, or
the guide's last step), each quote is found again in its paragraph, and
takes in what the new text puts in from the PDF (a "∼", an "x̄", an
item's "2.", a formula; never a word). A quote whose words changed
stops the build and is named, with what to do. The cross-claim step then
asks again about values whose quotes changed.

A paragraph you type in yourself, such as text printed inside a figure,
is marked `"transcribed": true`: its quotes cannot be found in the PDF's
text, so the check reports them as unchecked rather than as mismatches.

**Doubtful breaks.** To have an assistant look at the breaks the tool is
unsure of, run `rigoraudit handoff breaks` (the guide offers it). The
handoff holds only those places, each with the text around it, and the
assistant answers whether a new paragraph starts there;
`rigoraudit import breaks` checks the answer and makes the splits and joins.
The answer holds no text, so no word can change.

**GROBID.** Without the XML, GROBID (a free program that reads scientific
PDFs) finds paragraph breaks better than the tool does, most of all in
two-column layouts. Run it yourself as a server (its Docker image is the
easiest way) and name it in the manifest,

```yaml
settings:
  extract:
    grobid: http://localhost:8070
```

or add `--grobid http://localhost:8070` to `rigoraudit extract`. The PDF is
sent to that server, so use one you run. Anything GROBID could not place is
put at the end under "Unplaced text", for you to move. If the server does
not answer, the tool reads the PDF itself and says so.

Display equations (set on lines of their own) are not in the paragraphs'
text: a mark such as `[Equation 3]` stands where each is set. See
[Equations](#equations).

## 3. Parse claims

Each of these steps is done by an assistant, one file at a time:

```
rigoraudit handoff segment             # writes work/segment/handoffs/*.md
# paste or attach each file in the chat; save the reply as a text file
rigoraudit import segment reply.txt --by "<assistant>"
```

A reply with problems is not saved: the tool prints them in a block to paste
back to the assistant. Accepted replies are kept in `work/<step>/answers/`,
with who wrote them and when. The guide runs these commands for you.
When a step's instructions change, answers accepted under the older version
stay in use; the guide lists them each time it runs. To redo one, delete
its file in `work/<step>/answers/` and run `rigoraudit audit` again.

- **docs.** Before anyone runs the authors' code, an assistant reads their
  documentation: every README and dependency file, the text cells of each
  Jupyter notebook, and the opening comment of each script the run will start (`settings: run: scripts:` in the
  manifest, or `--script`). Its notes quote the documentation word for word.
  Record in `audit.yaml` wherever the run departs from it.
- **segment.** The audited paragraphs are split into claims: the smallest
  statements that could be true or false on their own. Each gets a type:
  new result, referenced result, comparison, interpretation, procedure, or
  no stated support. Results paragraphs come first; legends and tables
  follow, and may say which Results claim they restate. Every number,
  comparison word, and test name must be in a claim or left out with a
  reason; the left-out items are the coverage check's exclusions (step 6).
- **decompose.** Each new-result claim is split into facets: quantity,
  population, analysis, condition, and display. The assistant copies each
  number as printed; the tool reads the value from it, including powers
  of ten whose superscript the PDF's text flattens (`p<10−5`). A number
  printed without a unit takes the unit of the next one when the two are
  joined by ±, a dash, or "to" (`168.25 ± 4.1 ms`, `5–10%`). It also
  copies each statistical test the claim reports, part by part: the
  statistic, its degrees of freedom, p, N, the tails and whether the test
  is paired (only if the text says), and the effect size. A test printed
  with p only ("permutation test, p = 0.003") is copied by its name and
  p. From these the
  tool itself works out p, the N the degrees of freedom imply, and the
  effect size, and compares each with what is printed, allowing for the
  rounding of the printed statistic. Every p is compared to 3 decimal
  places, so any p below 0.0005 counts as 0.000: a printed p = 10⁻³⁰⁰
  agrees with any p below 0.0005, and so does p < 10⁻³⁰⁰. These findings are the tool's own;
  `rigoraudit record` adds them to the record. A test it cannot work out
  (a rank test, say, or one printed without its degrees of freedom) is
  *not verifiable*, with the reason
  ([0015](decisions/0015-statistical-tests.md)).
- **trace.** For each facet, the assistant finds the Methods passages that
  describe it and the code lines that compute it. It browses the authors'
  public repository at the manifest's commit; when it cannot (or when the
  manifest says `settings: trace: code_access: index`), the handoff carries
  an index of the code instead, and the assistant asks for the lines it
  wants, for up to four rounds. Every quoted line is checked against the
  local copy in `materials/`. A Jupyter notebook counts as its code cells
  only, laid end to end, each headed by a comment line; line numbers in a
  notebook are those of this view. The index lists the headings of a
  notebook's text cells, each with the line where the code after it
  starts. A browser shows a notebook differently,
  so when the code holds one, trace sends the index (unless the manifest
  says `code_access: repository`).
  For each test that decompose copied, the assistant also cites where the
  Methods and the code state its settings (paired or not, tails, Welch's
  version, a correction for multiple tests, and, for a bootstrap or
  permutation test, the number of resamples, what is resampled, the method
  for the confidence interval, and the seed), and any check of normality or
  equal variances. It names what each place says in fixed words. The tool
  compares them itself: the same in text and code is *consistent*; different
  is *differs*; a setting only the code shows is *not described*; one the
  text states with no code found is *not verifiable*. A check of an
  assumption that only the text names is *not verifiable* (it may have been
  run outside the shared code); an assumption neither addresses is *not
  described* ([0015](decisions/0015-statistical-tests.md)).
  Procedure claims are not decomposed; trace takes them whole, up to 15 in
  a task of their own. The assistant copies the numbers each claim states,
  and cites the Methods and the code lines that carry the step out, with
  the values those lines set. Where the code works in another unit (s for
  ms, a fraction for %), it names that unit, and the tool works out the
  claim's value in it ([0017](decisions/0017-procedures-traced-whole.md)).

## 4. Re-derive claims

Where a value has to be reproduced, a derivation recomputes it: a script in
`derivations/` that runs the authors' code or recomputes the value from
the data. An assistant writes one for every ten claims or so:

```
rigoraudit handoff derive              # writes work/derive/handoffs/*.md
rigoraudit import derive reply.txt --by "<assistant>"
```

Each handoff covers up to ten claims. It gives the numbers each claim
prints, the Methods passages and code lines the trace found, the notes on
the authors' documentation, and a list of the materials. The reply says,
for each number, where the script saves its value, which lines of code set
it (a setting such as a time window, which nothing computes), or why it
cannot be recomputed, and gives one script for all the claims, which saves each
claim's values to `derivations/output/values/<claim>.json`. The tool checks
the reply, saves the script in `derivations/` (named for the claims it
covers, such as `R1.1.a_to_R1.3.b.py`), and
runs it. A script that fails, does not save
a value it promised, or saves a printed number as anything but a number,
is sent back with what went wrong. So is a setting
whose lines do not show its value.

For each statistical test a claim reports that the script recomputes, the
reply also says where the script saves the N behind it and what one of
those values is, in fixed words (a trial, a block, a session, a cell, an
animal, a participant), with the words of the text that state it, if any.
It may also save the values in each group, and, if the script reruns
the test, the p it gets. The tool compares that p with the printed p, to
3 decimal places. A bootstrap or permutation test draws at random, so for
one the reply also says where the script saves how many resamples it
drew, and the comparison is widened by twice the chance difference
between two such runs, 2·√(p(1 − p)(1/n₁ + 1/n₂)) for n₁ and n₂
resamples (about ±0.02 for p = 0.05 at 1,000 each). The authors' number
is the one trace found; if none was found, the rerun's is assumed, and
the finding says so. When the rerun runs the authors' code and trace
found that it sets a seed, nothing is added. The tool compares the N with
the N the text states, and the unit with the text's: different is
*differs*, and a unit the text does not state is *not described*. From the
values, the claim card shows, with no status, N and skew in each group,
the ratio of the largest variance to the smallest, the share of tied
values for a rank test, and the share at a floor or ceiling. It also shows,
for every copied test, what the test assumes. The reader judges these
([0015](decisions/0015-statistical-tests.md), items 6, 9, and 11). When a
claim reports several tests, the findings call them "test 1", "test 2",
and so on; the card lists each, as the text prints it, under the claim's
location.

A script is a program that could change or delete files on your computer.
Before running one, the tool reads it (without running it) and flags, line
by line, anything a derivation should not need: importing a module that
can start programs, change files, or reach the network (such as `os`,
`shutil`, or `subprocess`, which running MATLAB or R needs); writing
outside `derivations/`, or where the check cannot tell; deleting or
renaming a file; running text as code; and paths outside the workspace. A
flagged script runs only once you have read it and agreed; open it in a
text editor (or ask your assistant to explain it). The check catches
mistakes, not a script written to get past it.

A script runs the authors' MATLAB code through `rigoraudit.matlab`, which
finds MATLAB on the computer. If the code includes MATLAB files, the guide
asks once whether scripts may start MATLAB without asking each time, and
saves the answer in the manifest. The check still flags anything else in
the script, but it does not read MATLAB code: whatever the authors' code
does, MATLAB does.

Everything a script uses must be inside the workspace. Output from a run of
the authors' code made elsewhere goes in `derivations/output/`, or is
linked there.

The manifest's settings for this step:

```yaml
settings:
  derive:
    run: ask            # ask before every script; the default, auto, runs
                        # a script the checks do not flag
    programs: [matlab]  # start MATLAB without asking; [] to ask each time
```

A derivation saves its results with `rigoraudit.values.write_values`. It
records the script's checksum and its inputs', so the check can tell when a
value is out of date:

```python
write_values(
    HERE / "output" / "values" / "trials.json",
    {"trials": {"all": len(trials)}, "accuracy_pct": {"session_1": 60.1}},
    script=Path(__file__),
    inputs=[DATA],
    workspace=WORKSPACE,
)
```

The record cites each value by its key (`accuracy_pct/session_1`), so every
number in a finding can be regenerated. Stand-ins for toolbox functions the
audit's computer lacks go in `derivations/` too, each named in the
manifest's gaps.

## 5. Record results

The record (`record/record.json`) holds the claims, the observations of each
source, and the findings that compare them. An assistant writes the
findings, up to ten claims at a time:

```
rigoraudit handoff compare             # writes work/compare/handoffs/*.md
rigoraudit import compare reply.txt --by "<assistant>"
rigoraudit record                      # builds record/record.json
```

Each handoff lists, for each facet of each claim, what each source says,
with a label on every item and value: the Results quote, the Methods
passages, the code lines, and the recomputed values. It also lists what the
tool has already checked for each claim (p, N, and effect size from the
printed test; the test's settings and assumption checks), so the assistant
does not check it again, and a facet the tool covered needs no other
finding. Procedures come in tasks of their own, up to 15 each, and get
findings for the claim as a whole, with no facet: the claim's values beside
the values the code sets, compared exactly. The reply gives the
findings by those labels: which items each compares, the basis, and the
comparisons; the tool computes each status from the values. A finding the
record's rules refuse (a comparison with one source, a status that
contradicts the values) is sent back with the reason. `rigoraudit record`
then puts every claim of step 3, these findings, and the tool's findings on
each copied test together, with the lines shown beside each test (the
record's `context`).

A record can also be built by a Python script of the audit's own,
`record/record.py`, which constructs it with `rigoraudit.schema`; the guide
and `rigoraudit record` then leave the record to it. Building it in code
means a malformed record is rejected at once: an unknown claim type, a
claim marked traced with no findings, a status set by hand. The accepted
answers of steps 3 and 4 can be turned into record items with
`segment.record_claims`, `decompose.results_observations`,
`trace.trace_observations`, and `derive.derived_observations`. A made-up claim, built by hand:

```python
from rigoraudit.schema import Claim, ClaimType, ManuscriptAnchor

text = paragraphs[("Results › Learning", 2)]
quote = "accuracy rose from 62% to 81% over 12 sessions"
start = text.index(quote)
claim = Claim(
    id="R1.2.a",
    type=ClaimType.NEW_RESULT,
    anchor=ManuscriptAnchor(
        file="manuscript.pdf",
        section="Results › Learning",
        paragraph=2,
        char_start=start,
        char_end=start + len(quote),
        page=4,
        quote=quote,
    ),
)
```

For each facet, compare the sources and choose how they should agree:
exactly, to the reported precision, or in direction
([0006](decisions/0006-comparison-rules.md)). Numeric comparisons store the
values and the tolerance, and the tool computes the status from them
([0007](decisions/0007-structured-values.md)). The example audit's
[`record.py`](../examples/example-audit/record/record.py) shows every kind of
item, with helpers worth copying.

## 6. Check claims

```
rigoraudit check
```

checks the record (with the review log applied) against the materials:

- every manuscript quote is in the PDF's text, on the page it states, and
  at the character positions it states in its paragraph;
- every code quote matches the cited lines, at the cited commit;
- every data file, and every file in a data folder, matches its checksum
  in the manifest;
- every value is the one its derivation last wrote, and the derivation's
  script and inputs have not changed since.

It also lists every number, comparison word ("higher", "differed"), and
named statistical test in the audited sections that no claim covers. The
text the segment step left out, each piece with its reason, counts as
covered. For anything else, add a claim, or list it in
`record/coverage_exclusions.json` with the reason it holds no checkable
claim (a label, a prediction, a restatement):

```json
{"exclusions": [
  {"paragraph": "R1.1", "quote": "(4 and 8 kHz)",
   "reason": "Describes the task, as the Methods do; it reports no result."}
]}
```

`paragraph` is the paragraph's label, and `restates` (optional) names the
claim the text repeats. Fix each problem the check reports and run it again
until it passes. The results are saved in `work/checks.json`, and the
report's status paragraph says whether they are current. The check also
fails if a gap in the manifest names a claim the record does not have. It
says LOOK AGAIN, without failing, when a gap names something that is in
the materials: a data file, a name saved in one, a function defined inside
another code file, or a package folder. Gaps often name things that are
there on purpose ("each session has its trial lists but not these"); then
there is nothing to do. If not, make sure what the gap calls missing is
not there.

The check also sets side by side the values the paper prints in more than
one claim, such as a count in the Results and again in a figure legend
([0016](decisions/0016-cross-claim-checks.md)). An assistant first says
which values are about the same thing: the same quantity, for the same
population and condition:

```
rigoraudit handoff crosscheck          # writes work/crosscheck/handoffs/crosscheck.md
rigoraudit import crosscheck reply.txt --by "<assistant>"
```

The handoff lists every printed value, claim by claim, and candidate groups
proposed by three rules: one claim restates the other; their findings cite
the same code lines, data, or Methods paragraph; or the values have the
same name, subject, and unit. The assistant confirms, splits, or sets aside
each candidate, with a reason, and adds groups the rules missed (a count
called "subjects" in one claim and "participants" in another). The tool
then compares the values of each group at the coarser of the two printed
precisions; a value printed as approximate ("∼50") agrees with one within
10% of it. The results are written to `work/crosscheck/findings.json` and
shown in the report; a difference does not fail the check. The answer is
used only for the values it was given: if the record changes, the step is
handed off again, and until it is answered the check and the report say it
is not done.

## 7. Report and review

### The report

```
rigoraudit report
```

writes `report/audit.html` from the record with the review log applied, and
prints the file's full path to open in your browser. It lays out the
paper's sections in order, each paragraph with its claims marked, beside a
card for each claim that sets out what the Results, Methods, code, and data
say, with the evidence behind each statement. A finding that differs
names, in bold, the printed values that do not agree with what was found
(`rigoraudit show` marks those comparisons in bold too). The gaps in the materials
come first, after the summary, then the values printed in more than one
claim (step 6), each also noted on the cards of the claims it involves. Filters pick claims by type, section, and
finding. The page shows the paragraphs of the audited sections
and any other paragraph with a claim.

The page's header is the audit's own, in `report/header.html`: a heading
with the paper, what the audit covers, and where each material came from
(the example audit's
[header](../examples/example-audit/report/header.html) shows the form).
Write it yourself, or have an assistant draft it:

```
rigoraudit handoff header              # writes work/header/handoffs/header.md
rigoraudit import header reply.txt --by "<assistant>"
```

The assistant answers with the parts in plain text, from the manifest and
the paper's first page; the tool checks the paper's title is on that page
word for word and that the manuscript and the code each have a line, then
writes the file. Edit it as you like: once the file is there, the step is
done. Text
in `report/footer.html` is added to the footer. The report also puts its
status paragraph in the workspace's `README.md`, between markers.

### Review

```
rigoraudit review
```

shows the report at http://127.0.0.1:8765/ (on this computer only), with
review buttons:

- on each claim: Confirm, Edit, Split, Merge, Remove, Add finding;
- on each finding: Confirm, Override, Edit trace, Remove;
- on each value in the Cross-claim checks list: Confirm, Override.

Selecting text in a paragraph gives the quote for an Edit or a Split's
parts, and offers *Add claim from selection*. *Edit trace* keeps or drops
each piece of a finding's evidence and adds new evidence: a passage
selected in the paper, or lines of the code by file and line numbers. A
finding that compares numbers, or rests on data, names the derivation
behind it, so it is added in the record, not the page. A change that would
leave a finding invalid is refused, with the reason.

Each action needs a reason, and is saved in the review log,
`review/log.json`; the report then shows the reviewed record. The record
itself is never edited by the review: if the record is rebuilt with changes,
an action whose claim or finding changed is marked as needing re-review
([0010](decisions/0010-provenance-and-review.md)).

### One claim

```
rigoraudit show R1.2.a
```

prints everything the audit holds on claim R1.2.a, as text: the claim; what
each source says about each facet, labelled `O1`, `O2`, … as in the compare
step; the values that could not be recomputed and why; the findings, with
their comparisons; the gaps that name it; and the review actions on it. It
works at any step after segment, from the accepted answers, so it shows the
latest even before `rigoraudit record`, and says when `record/record.json`
is older than them. An audit with its own `record/record.py` is shown from
`record/record.json`.

## Equations

Each display equation is listed in `work/extract/equations.json`, with its
number, the paragraph its mark is in, its page, and where it is on the page,
and `work/extract/equations/` has a picture of each as printed (`001.png`
for the first). An equation's text in the list is only a rough guide, since
a formula's layout is lost: check an equation against its picture. A quote
may include a mark such as `[Equation 3]`; the check then finds the words
on each side of it, and does not compare the equation itself. In the
report, each mark is followed by its equation's picture, small; click it to
see it full size, and again to make it small.

An equation printed with a number is known by that number. One printed
without a number is known by where it is: `p22@233` is on page 22, its top
233 points (about 8 cm) down the page. (One in the XML that is not found in
the PDF is known by the number before it: `A12+1` is the first after A12.)
A number read from the PDF that is out of order with the rest is not used,
and a gap in the numbers is noted, not filled. Where the tool has a number
wrong, give the printed one (or `null` for none) in
`derivations/equation_numbers.yaml`, by the equation's place key; a key a few
points off still matches the nearest equation:

```yaml
p26@412: A14
p26@530: null
```

To check equations in a derivation, type them in LaTeX in
`derivations/equations.yaml`, by number or place key, and run
`rigoraudit equations`:

```yaml
"3": '\frac{dx}{dt} = -\lambda x'
A12:
  latex: 'p(x \mid \theta) = \mathcal{N}(\mu, \sigma^2)'
  note: typed from page 21; the printed subscript is unclear
p22@233: 'y = a + b'
```

It writes `work/equations.html`, which opens in a browser without a
connection: each equation's picture as printed, beside your version drawn as
maths, so a slip in the typing can be told from a slip in the paper. It
lists typed keys that match no equation, and LaTeX it could not draw. It
also applies `equation_numbers.yaml` to `equations.json`; the marks in the
paragraphs change at the next `rigoraudit extract --replace`.

## Practical advice

- Read the authors' documentation before running their code, and run it
  the way it says ([0013](decisions/0013-authors-documentation.md)).
- Expect the authors' code not to run as received. It often calls helper
  functions or toolboxes it does not include, hard-codes the authors'
  paths, or needs more memory than you have. Record each problem in
  `audit.yaml`, prefer the authors' own published helpers over stand-ins,
  and check that a stand-in gives identical output where it can be
  compared.
- Never drop or alter data quietly to make code run. Report what was
  excluded and why.
- Ask the assistant to report a surprising result plainly, not to adjust
  the analysis until it matches the paper.
- Keep notes on open questions in `notes/`, and a `README.md` in the
  workspace saying what is there and how to rebuild it.
- Keep the workspace out of any public repository: it holds the paper, the
  data, and the audit's findings.

## Feedback

Each `rigoraudit audit`, `handoff`, `import`, and `extract` adds to the
audit's one feedback report, `work/feedback/report.md`: the tool's version,
the steps run and how each ended, and the kinds of problems found in
assistants' answers. Its summary at the top says this in plain sentences,
and whether the report is worth sending. It holds no text, values, or file
names from your materials, and the tool never sends it. `rigoraudit
feedback` shows where the report is and how to
send it, if you choose to; `--include <file>` adds a file you want the
developers to see, marked as audit material. How the developers read
reports is in [feedback.md](feedback.md).

## The workspace

Every audit has its own folder, outside this repository. The tool finds
everything in it by these fixed paths:

| Path | Holds |
|---|---|
| `audit.yaml` | The manifest: the materials, their versions and checksums, the gaps, and the settings |
| `materials/` | The paper, code, and data, as received; never edited |
| `work/materials/files.md` | Every file in `materials/`, what each data file holds, and what the code reads (step 1; written at every run of the guide) |
| `work/extract/` | The paper's text, outline, paragraphs, and equations (step 2) |
| `work/<step>/` | Handoffs to an assistant, its accepted answers, every reply it gave (`replies/`, unless you saved them as files yourself), and a coding assistant's replies still to check (`inbox/`) (steps 3 to 6, and the report's header in step 7). For a coding assistant, `work/trace/methods.md` holds the Methods once, and each trace task points to it |
| `work/checks.json` | The results of the latest `rigoraudit check` |
| `work/crosscheck/findings.json` | Values printed in more than one claim, compared (step 6); the handoff and answer that grouped them are beside it, as for every step |
| `work/feedback/` | The feedback report and its log |
| `derivations/` | Scripts that rerun the authors' code or recompute values (one for each task an assistant did, named for its claims, step 4); their outputs in `derivations/output/` |
| `record/` | `record.json` (written by `rigoraudit record`, or by the audit's own `record.py`), and `coverage_exclusions.json` |
| `review/log.json` | Every review action |
| `report/` | `audit.html`, and the audit's own `header.html` and `footer.html` |
| `notes/` | The auditor's notes |
| `README.md` | What is in the workspace, how to rebuild it, and the generated status paragraph |

## Glossary

| Term | Meaning |
|---|---|
| Workspace | One audit's folder ([0001](decisions/0001-workspaces.md)) |
| Materials | The paper, code, and data as received; never modified |
| Manifest | `audit.yaml`: what each material is, where it came from, its checksum, the gaps, and the settings |
| Record | The audit's claims, observations, and findings (`record/record.json`) |
| Claim | The smallest statement that could be true or false on its own, with a single source of evidence ([0002](decisions/0002-claims.md)) |
| Facet | One checkable part of a new-result claim: quantity, population, analysis, condition, or display. Procedures are checked whole, with no facets |
| Anchor | An exact location with a verbatim quote: paper text, code lines at a commit, or a data or output value |
| Observation | What one source (Methods, Results, code, data, output) states or does, with its anchor and how it was obtained |
| Obtained | How an observation was got: *quoted* (paper), *read* (code inspected), *executed* (authors' code run), *recomputed* (the audit's own computation), or *computed* (worked out by the tool from numbers the paper prints, such as p from t) |
| Derivation | A script in `derivations/` that runs the authors' code or recomputes a value; its outputs are read back by key |
| Finding | The comparison of sources for one facet, or for a whole procedure: a status, a neutral summary, the observations compared, and the potential effect on the result |
| Status | *Consistent*, *Differs*, *Not described*, or *Not verifiable* (with a reason) |
| Basis, tolerance | How sources were compared (exact, reported precision, design vs realization, direction) and how far they may differ ([0006](decisions/0006-comparison-rules.md)) |
| Computed status | A status that follows from the stored values and tolerance, never set by hand ([0007](decisions/0007-structured-values.md)) |
| Trace state | Whether a claim is *pending*, *traced*, traced *via dependencies* (interpretations), or *deferred* (rests on a citation) |
| Coverage | The check for numbers, comparison words, and named tests in the audited text that no claim covers |
| Handoff | A file to give an assistant: a step's instructions, then the material for one task |
| Review log | Every reviewer action, with its reason; the report shows the record with the log applied |
| Override | A reviewer's status for a finding, with a reason; shown beside the computed status, and stale if the finding changes |
