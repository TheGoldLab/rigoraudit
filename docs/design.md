# miragold — design

This file describes the current overall design, including work in progress. Settled choices and their reasons are recorded in [`decisions/`](decisions/).

## Purpose

Audit a scientific manuscript together with its code and data, to maximize:

1. **Transparency** — make explicit exactly what was done for every analysis,
   model, and reported result.
2. **Consistency** — check that what Methods describes, what Results reports,
   what the code does, and what the data contain all agree.

Readers may be authors (pre-submission), lab members, colleagues, or reviewers/editors. The output is written to be thorough, professional, and neutral. It describes what each source says and where they differ, and leaves judgment to the reader.

## Core concepts

### Claim

The smallest statement in the manuscript that could be true or false on its
own and that has a single evidentiary source. One sentence often contains
several claims. See [0002](decisions/0002-claims.md).

Claim types:

| Type | Traced to |
|---|---|
| New result | Methods → code → data → generated output |
| Referenced result | Citation → cited work *(deferred, see [0005](decisions/0005-scope-and-deferrals.md))* |
| Comparison | Both of the above, plus whether the stated agreement holds |
| Interpretation | The claims it depends on |
| Procedure | Checked whole against the Methods and the code, not split into facets ([0017](decisions/0017-procedures-traced-whole.md)) |
| No stated support | Nothing — recorded as such |

New-result claims are decomposed from the start into **facets**: quantity,
population, analysis, condition, and display (figure/table). Each facet is
traced and compared separately.

### Evidence graph

Defined in [`src/miragold/schema.py`](../src/miragold/schema.py).

- **Anchors** — precise locations, each carrying a verbatim quote: manuscript
  (section, paragraph, character span, page and line number if present), code
  (file, line range, commit), data or generated output (file, field,
  selection, and how the audit derived the value).
- **Claims** — ID, type, manuscript anchor, relations to other claims
  (*depends on*; *restates*, for a claim outside the Results, such as in a
  figure legend or the Discussion, that repeats a Results claim) or to
  citations, and an explicit trace state:
  *pending*, *traced* (has findings), *via dependencies* (interpretations),
  or *deferred* (citation-based).
- **Observations** — what one source (Methods, Results, code, output, data)
  states or does, as a neutral paraphrase plus an anchor. Decomposing a claim
  into facets produces its Results observations; tracing produces the rest.
- **Findings** — for one facet of one claim (or a named part of it, when a
  source covers only part): a status, a one-sentence neutral summary, the
  observations compared, the potential effect on the reported result
  (including *none observed*), and (where needed) the silent sources or the
  reason it could not be verified.
- **Cross-claim findings** — for one thing the manuscript prints in two or
  more claims: the values as printed, each with its anchor, the rules that
  proposed them, the assistant's reason for joining them, and whether they
  agree (consistent or differs only). Kept apart from findings, which
  belong to one claim, and worked out by the tool from the record and the
  cross-check answer ([0016](decisions/0016-cross-claim-checks.md)).

The transparency ledger and the consistency report are two views of this one
graph.

### Status vocabulary

| Status | Meaning |
|---|---|
| Consistent | All available sources agree |
| Differs | Two or more sources state different things |
| Not described | The code/data do something the manuscript does not state (or vice versa) |
| Not verifiable | Could not be checked; the reason is always given (e.g. data not shared) |

*Consistent* and *Differs* always state how the sources were compared (exact,
reported precision, design vs realization, or direction) and the tolerance
applied. Design statements are checked per subject. See
[0006](decisions/0006-comparison-rules.md).

For numeric comparisons the values and tolerance are stored as data, and the
status is computed from them, never set by hand. Each observation states how
it was obtained (*quoted*, *read*, *executed*, *recomputed*, or *computed*
from printed values, such as p from a printed t; a computed value is compared
with the text it was worked out from). Reviewers who
disagree with a computed status record an override from the report. The
override is kept in `review/`, shown beside the computed status, and marked
stale if the values change. See [0007](decisions/0007-structured-values.md).

## Verification

`miragold.verify` checks a record against the materials independently of
how the record was built. Manuscript quotes are checked against the PDF text
layer and their stated page, code quotes against git at the anchor's commit,
and data anchors against the manifest's checksums. Values the audit derived
are read back by key from their derivation's output (`miragold.values`).
An output whose script or inputs have changed since it was written is
reported as stale. Every value must appear in the quote the reader sees,
except a test setting stated in fixed words, which is a reading of the code
(`paired` for a paired t-test call; `miragold.stats.READINGS`), and a statement about data may cite only numbers its quote shows (a
derived value's statement, which says how it was computed, is exempt).
Statuses are checked against their rule by the schema itself (0007).

`miragold.coverage` looks for what the record leaves out. Every number,
comparison word, and named statistical test in the audited text must lie
inside a claim, inside a manuscript quote used as evidence, or inside an
exclusion that gives its reason (often that the text restates another
claim, which it names). The segment step's left-out items are exclusions,
and an audit can add its own in `record/coverage_exclusions.json`. Uncovered items are reported by sentence. The check
cannot see claims stated without such words, such as an interpretation in
plain prose, or paragraphs that were never extracted.

## Review

`miragold review` serves the report locally with the review operations
on each claim and finding (`miragold.server`): Confirm, Edit, Split,
Merge, Remove, Add finding on claims; Confirm, Override, Edit trace, Remove
on findings; Confirm and Override on cross-claim findings; and Add claim from a text selection in a manuscript
paragraph. Selections give the quotes for Edit, Split, and Add; the server
takes the quote from the extracted paragraph and refuses a selection that
does not match it. New evidence for a finding is a selected manuscript
passage or lines of code, read from the local copy at the record's commit;
evidence from data or outputs, and numeric comparisons, name a derivation,
so they are added in the record. Every review action is an entry in one
log, `review/log.json` (`miragold.review`): the operation, its target,
reviewer, date, a required reason, and a fingerprint of the target as the
reviewer saw it (for a claim: type, quote, and what it cites or rests on;
for a finding: status, comparisons, and evidence; for a cross-claim
finding: status and values). The operations are those
of [0010](decisions/0010-provenance-and-review.md): Confirm, Edit, Remove,
Split, Merge, Add on claims; Confirm, Edit trace, Add, Remove, Override on
findings. Each entry is checked for the payload its operation takes (a
Split's parts get IDs that start with the original's, an Add carries the new
item). `review.apply` gives the reviewed record: the draft with the log's
entries applied in order, each checked against its target as it stands
after the ones before. An entry whose target has changed is stale and not
applied; one that would leave the record invalid, or reuse a retired ID,
is refused with the reason. Edit, Split, and Merge reset the claims they
touch to pending and drop their findings; claims that depended on a split
or merged claim are pointed at what replaced it. Overrides apply through
`review.current`: the latest per finding is in force unless its
fingerprint no longer matches, in which case it is shown as needing
re-review. Overrides of findings no longer in the record are
counted, not dropped. Cross-claim findings are worked out from the
reviewed record, not stored in it, so their entries are left out of
`review.apply`; `review.current_cross` gives the latest Confirm or
Override of each, stale in the same way.

Every record names who drafted it (`AuditRecord.drafted_by`: a person, or a
model with its ID and stage, and the date); a claim, observation, finding,
or derivation names its own drafter only when it differs (schema version 4,
[0010](decisions/0010-provenance-and-review.md)).

Each audit carries a generated paragraph on where it stands
(`miragold.status`): who drafted it, the mechanical results, how many
claims and findings review has covered (an item counts once it has a
review action whose fingerprint still matches), the independent annotation
and authors' response if any, and the next step. `miragold check` saves
its results to `work/checks.json` with the digest of the record it
checked; if the record has changed since, the paragraph says the checks
were not run on this version. The checks are of the reviewed record (the
draft with the review log applied, 0010 rule 6). The report puts the
paragraph in its header and between markers in the workspace README.

The report (`miragold.report`) shows the reviewed record (`review.apply`), and marks claims
(`data-claim-id`), findings (`data-finding-id`), and paragraph text
(`data-section`, `data-paragraph`, with claim labels inside marked
`data-not-text`) for the page's script.

Planned (0010): claims reviewed before tracing (a pipeline stage order, not
yet enforced).

## Report organization

The report (`miragold report`, `miragold.report`)
follows the manuscript's own major sections, named and ordered as
in the PDF outline (`miragold.sections`): a summary of potential issues,
then one collapsible block per major section with its text beside its claim
cards. Subsections appear as headings inside a block. Figure legends and
panel text go with the subsection that cites the figure most often. Sections
with no claims are listed as not covered. A PDF without an outline falls
back to standard headings (Abstract, Introduction, Results, Discussion,
Methods, Appendices, and Other for back matter), each with its common
variants ("Materials and Methods", "Experimental Procedures", "STAR
Methods", ...), found as lines of their own in the text. That fallback finds
major sections only.

## Audit workspaces

The tool (this repository) and the audits are separate. Each audit lives in a
workspace at a location the user chooses. See [0001](decisions/0001-workspaces.md).

```
<workspace>/
  audit.yaml      # manifest: roles → paths, versions, hashes, gaps, settings
  materials/      # as received, never modified
  work/           # the tool's step outputs and check results (machine-facing)
  derivations/    # the audit's own computations and their outputs (0007)
  record/         # record.py builds record.json; coverage_exclusions.json
  review/         # the review log (log.json)
  report/         # audit.html, and the audit's own header.html and footer.html
  notes/          # the auditor's notes: open questions, decisions
```

Every path is fixed, so commands need no options to find their inputs.
The manifest says which sections are audited (`settings: scope`, patterns
matched at the start of a paragraph's section), and segment, the report,
and the coverage check all use it.
Its gaps (what could not be run or checked from the materials, and the
claims each affects) head the report; the check makes sure each claim
named is in the record, and points out names a gap gives that are in the
materials after all ([guide](guide.md#1-collect-materials)).

`derivations/` holds scripts that run the authors' code or recompute values
independently, the values they write (read back by `miragold.values`), and
any stand-ins for toolbox functions the audit environment lacks. Each
stand-in is named in the manifest's gaps. Equations typed in for a
derivation are kept, in LaTeX, in `derivations/equations.yaml`, so
`miragold equations` can show each beside its picture as printed. They
are keyed by the number printed, never renumbered; the auditor's
corrections to numbers the tool misread are in
`derivations/equation_numbers.yaml` (`miragold.numbering`).

Materials are never reorganized. The manifest maps whatever structure they
arrive in onto roles (manuscript, supplement, code, data, figures), and
records what is absent. Planned: an inventory stage drafts the manifest —
including a proposed script → figure/table map — and a human confirms it;
for now the manifest is written by hand.

## Pipeline

| Stage | Does | Built |
|---|---|---|
| inventory | materials → every file, what each data file holds, and what the code reads; draft manifest (human-confirmed) | the list, `work/materials/files.md`, written at every guided run (`materials`, [0014](decisions/0014-list-the-materials.md)); manifests are hand-written |
| extract | manuscript → structured text with anchors; code and data indexed | `miragold extract`: paragraphs from the publisher's XML (with characters it leaves out put in from the PDF), or a best guess from the PDF (the tool's own, or GROBID's if a server is named); code indexed for trace (`codeindex`). Each build of the record finds every quote again in the paragraphs as now extracted, so extracting again after later steps is safe (`Paragraph.locate`) |
| segment | text → claims | instructions, files to paste into an assistant, the check and import of its reply, and record claims built from accepted replies (`segment`) |
| classify | claim → type | done in the same pass as segment (instructions v2) |
| decompose | new-result claim → facets | instructions, the check and import of an assistant's reply, and the Results observations built from it (`decompose`); values are read from the text as printed. Each reported test is copied part by part, and the tool works out p, N, and the effect size from it and builds those findings itself, drafted by the tool (`stats`, [0015](decisions/0015-statistical-tests.md)) |
| docs | the authors' documentation → what each file says about running the code | listing, handoff, and check (`docs`); the guided command does it before segment, and derive hands its notes to the assistant writing scripts |
| trace | facets, and procedures whole → methods statements → code → data/outputs | Methods and code, with an assistant that browses the public repository at the manifest's commit or, failing that, reads an index of the code and asks for lines (`trace`, `codeindex`); every citation is checked against the local copy. For each copied test it also cites the test's settings and any check of its assumptions, and the tool compares them (`stats`, [0015](decisions/0015-statistical-tests.md)) |
| derive | facets → recomputed values | an assistant writes one script for up to ten claims; the tool checks it, runs it (once the user agrees, if the script checks flag it; starting MATLAB through `miragold.matlab` is not flagged if the manifest allows it), and builds output and data observations from what it saved, and code observations from the lines that set a value (`derive`). For each test the script recomputes, it saves the N, what one value is, the values in each group, and, if it reruns the test, its p; the tool compares the N, the unit, and p with the text (p widened for resampling error) and describes the values, with no status (`stats`, [0015](decisions/0015-statistical-tests.md)) |
| compare | sources → status per link | an assistant names the observations and comparisons for each facet, or for a procedure as a whole ([0017](decisions/0017-procedures-traced-whole.md)); statuses are computed from them (`compare`, `schema`), and `miragold record` builds the record from the answers |
| cross-check | record → values printed in more than one claim, compared with each other | rules R1–R3 (restates, same place, same label) propose groups; an assistant confirms, splits, or adds them (R4); the tool compares within each group, in `miragold check`, and writes `work/crosscheck/findings.json` (`crosscheck`, [0016](decisions/0016-cross-claim-checks.md)) |
| verify | record → checks of every quote, value, and status against the materials | `miragold check` (`verify`, `values`, `coverage`) |
| report | evidence graph → human-readable report | `miragold report`, and the review page (`miragold review`); one claim as text (`miragold show`); an assistant drafts the page's header from the manifest and the paper's first page, as plain text the tool checks and writes out (`header`) |

Segment, classify, decompose, trace, derive, compare, cross-check, the report's header, and the inventory's script map are
expected to use a language model; the other stages never do. A model's
output passes the same checks as a hand-built record before it is accepted.
See [0009](decisions/0009-language-models.md).

The instructions for each step that needs judgment are written into the
package (`miragold/instructions/`), versioned, and given to whichever
assistant does the step; one guided command takes the user through every
step: tasks carried to and from a chat on the clipboard (or as files), an
inbox a coding assistant writes its replies to, or, only if the user
confirms the cost, a model asked through the API (`guide`, `clipboard`,
`api`; [0011](decisions/0011-guided-audit.md)).

Each stage writes its accepted answers to `work/<stage>/`, so stages can
be run, evaluated, and replaced independently. The record is assembled
from those answers by `miragold record` (`compare.write_record`), or by
a script in the workspace (`record/record.py`), from the same answers
(`segment.record_claims`, `decompose.results_observations`,
`trace.trace_observations`, `derive.derived_observations`) or by hand. The
example audit's record is built by its own script; the stages are developed
and tested against real audits kept outside the repository, built both
ways.

## Output

Human readability is a hard requirement. See [0003](decisions/0003-readable-output.md)
and [0004](decisions/0004-neutral-language.md).

- The manuscript itself is the backbone: every claim is marked in place with a
  stable ID; selecting it opens its claim card.
- Claim cards use a fixed template: the quoted claim, its type, the tests
  it reports when there are several (numbered, as its findings name them),
  a facet × source table (Methods / Code / Data / Results), and any
  differences, each with quoted evidence and its location.
- Layered: summary → claim cards → raw evidence. Consistent claims are shown
  but collapsed.
- Every claim gets a card, not only those with differences; the complete
  ledger is the transparency output.
- No finding exists without a manuscript anchor and quoted evidence from each
  source involved.

## Open questions

- Exports alongside the HTML report (CSV, Markdown).
- How reviewer decisions in `review/` carry across manuscript revisions.
- Claim segmentation rules, refined from the example audits (0002). They
  have raised:
  - *Notation.* Symbols such as subscripted signal names and Greek
    statistics render differently in the XML and the PDF text layer, so
    quotes are often trimmed to their non-math span. Either quotes may omit a
    claim's symbolic subject, or quote matching needs a mode for math.
  - *Support outside the paper.* A claim can rest only on material in the
    published peer-review record (a "Reviewer Figure"). The schema has no
    source for it.
  - *Wrong cross-references.* A sentence can cite the wrong table or
    figure for values that are correct where they are printed. A finding
    needs two sources, and this has only the manuscript, so for now it is
    stated in the summary of the finding that checks the values. It may
    later become a cross-claim check (0016).
- Quotes interrupted by a full-page figure. `verify` joins a quote across
  adjacent pages only, so a sentence continued after a figure page is not
  found.
