# 0010 — Provenance, verification levels, and review of a record's structure

**Status:** accepted (2026-10-30)

## Problem

A record is drafted by a person or a model (0009): by hand in `gold/` now,
by the pipeline later. The mechanical checks (schema, `verify`, `coverage`)
show that the record is accurate to the materials: every quote exists, every
value matches, every status follows from its values. They cannot show that
the record made the right choices: where one claim ends and the next begins,
each claim's type, which Methods text, code, and derivation trace it, and
whether a summary is fair.

Those choices have so far been made by Claude in Claude Code sessions and
reviewed in part by the user, and nothing records which parts. A reader
cannot tell how far to trust a record, and a reviewer who disagrees with a
choice can only override a status (0007), not correct the structure behind
it.

## Decision

1. **Every item records who drafted it.** Each claim, observation, finding,
   and derivation records whether it was drafted by a person (named) or a
   model (named, with version, stage, and prompt version), and when.

2. **Verification has four levels, recorded per item.**

   | Level | What it establishes | How |
   |---|---|---|
   | Mechanical | Quotes, values, checksums, and statuses agree with the materials; derivations are current; uncovered statements are listed | Automatic on every build |
   | Reviewed | A person has checked the item's structure (below) and confirmed or corrected it | Review operations, logged |
   | Independent | A second person, without seeing the record, annotated a sample; agreement is measured | Separate annotation, compared by script |
   | Author-checked | The paper's authors have seen the findings and may respond | Responses logged in `review/` |

   A partial review states what it covered: for example, every finding that
   is not *Consistent*, plus a random sample of the rest, with the sample
   size and seed.

3. **Reviewers act through a fixed set of operations.**

   On claims (structure):

   | Operation | Use |
   |---|---|
   | Confirm | Boundaries and type are right |
   | Edit | Change the quote's extent or the type |
   | Remove | Not a checkable claim, or already covered by another |
   | Split | One claim is two or more, each with its own quote |
   | Merge | Two or more claims are one |
   | Add | A claim the record missed |

   On findings (traces and status):

   | Operation | Use |
   |---|---|
   | Confirm | Sources, code, and derivation are the right ones and the summary is fair |
   | Edit trace | Change an anchor, or add or remove an observation |
   | Add, Remove | A facet not traced, or a finding that does not belong |
   | Override | Disagree with the computed status (0007) |

4. **One log holds every review action.** Each entry in `review/` records the
   operation, its target, the reviewer, the date, a required reason, and a
   fingerprint of the target as the reviewer saw it. Nothing is deleted from
   the log. Overrides (0007) become one kind of entry.

5. **The reviewed record is the draft with the log applied.** Corrections are
   not made by editing the draft (`gold/record.py` or a stage's output), so a
   rebuilt draft keeps them. An entry whose fingerprint no longer matches the
   rebuilt draft is shown as stale and is not applied until re-reviewed. The
   difference between draft and reviewed record is kept, and is what 0009
   scores a drafter on.

6. **Corrections pass the same checks as the draft.** A new or edited claim's
   quote must be found in the manuscript; new code anchors must match git;
   new values must come from quotes or derivation outputs.

7. **Structural changes reset what depends on them.** A claim that is split,
   merged, retyped, or re-quoted loses its findings: the new claims start as
   *pending*, and the old findings remain only in the log. Claims are
   therefore reviewed before they are traced, in two passes:
   - after segment and classify: the claim operations;
   - after trace: the finding operations.

8. **IDs are never reused.** A split gives new IDs that record their origin
   (R2.1.c → R2.1.c1, R2.1.c2). A merge keeps one ID and records those it
   absorbed. A removed ID stays retired. References in notes, overrides, and
   authors' responses keep pointing to the right thing.

9. **Every audit states where it stands.** The report header and the
   workspace README carry a paragraph generated from the record and log,
   never written by hand: who drafted it and when, the mechanical results,
   counts of each review action, whether an independent annotation or the
   authors' response exists, and what remains to reach the next level. For
   example:

   > 140 claims, 0 findings. Drafted by Claude (Opus 5.5) in Claude Code
   > sessions, 2026-10-01. Mechanical checks pass. Reviewed: 0 claims.
   > Independent annotation: none. Authors: not contacted.

## Why

Trust in an audit depends on knowing which of its judgments a person has
checked. Recording provenance and review per item lets the report say so
exactly, and lets a partial review be stated honestly. Keeping corrections as
a log over the draft makes them survive rebuilds and makes the drafter's
error rate measurable, which 0009 needs before any model stage is used.
Resetting findings after structural changes, and reviewing claims before
tracing, keeps tracing effort from being spent on claims that change.

## Not yet decided

- The log's file format, and whether it replaces `review/overrides.json` or
  sits beside it.
- How an *Add* or *Split* is entered in the review page (selecting text in
  the manuscript is the likely form).
- Whether removed or merged claims are listed in the report.
- How the independent annotation is compared with the record when their
  claim boundaries differ.

## Notes

- 2026-10-31: Rule 1 is built (schema version 4). The record names its
  drafter once and an item names its own only when it differs, rather than
  repeating it on every item. The log is `review/log.json` and replaces
  `review/overrides.json`, which is converted once. Its entries hold every
  operation in rule 3; only overrides are applied so far.
- 2026-10-31: Rule 9 is built (`rigoraudit.status`). Check scripts save
  their results with the digest of the record they checked, so the
  paragraph cannot report checks on an earlier version as current.
- 2026-10-31: Rules 5, 7, and 8 are built (`review.apply`). Claims that
  depended on a split or merged claim are pointed at its replacements; an
  entry that would leave the record invalid is refused with the reason
  rather than applied.
- 2026-10-31: The review page offers the claim operations and Confirm,
  Override, Remove on findings. Add and Split are entered by selecting text
  in the manuscript paragraph (the first open question above); the quote
  is taken from the extraction. Edit trace and Add finding are not yet in
  the page.
- 2026-10-31: Edit trace and Add finding are in the page. New evidence is
  a selected manuscript passage or code lines, whose quote the tool reads
  from the local copy at the record's commit (rule 6); data and output
  evidence, and numeric comparisons, are still added in the record, since
  they name a derivation. The status paragraph counts the mechanical checks
  only when they were run on the reviewed record (rule 6), and the report
  page (`rigoraudit report`) moved into the tool and shows the reviewed
  record.
- 2026-10-31: `review/overrides.json` is no longer converted or read; the
  log is the only record of review actions. The review page always uses
  the tool's report, and the checks are run with `rigoraudit check`, so a
  workspace needs no scripts of its own to render or check the record.
- 2026-11-02: A third kind of drafter, the tool, for findings it works out
  with no judgment, such as p from a printed t
  ([0015](0015-statistical-tests.md)). It names its stage, as a model
  does, and has no model identifier or prompt version.
- 2026-11-03: Confirm and Override on cross-claim findings
  ([0016](0016-cross-claim-checks.md)), a third kind of target. They are
  worked out from the reviewed record rather than kept in it, so these
  entries change nothing in it; the report shows the latest one beside
  the computed status.
