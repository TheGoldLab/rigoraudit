# 0012 — Feedback reports: written every run, sent only by the user

**Status:** accepted (2026-10-30)

## Problem

The tool will meet papers, code, and assistants it was not developed
against: a new programming language, a manuscript laid out differently, an
assistant that keeps making the same mistake, a step that fails outright.
The people who meet these problems are users, not the developers, and
today nothing reaches the developers unless a user writes it up from
scratch.

The obvious fix, sending reports automatically, does not suit this tool.
An audit's materials are often unpublished manuscripts and private code,
and a report that carries any of it, even a quote inside an error message,
would leak it.

## Decision

1. **Every run writes a feedback report into the workspace,** by default,
   at `work/feedback/<date>-<time>.md`. The guided command (0011) writes
   one when it stops, whether it finished, was stopped, or failed; each
   separate command adds its part to the report for that day.

2. **The report holds what happened to the tool, never what is in the
   audit:**
   - the tool's version, the Python version, and the operating system;
   - the steps run, how long each took, and how each ended;
   - for every answer an assistant gave: which step, which instructions
     version, which way it was produced (0011 item 3), how many rounds of
     corrections it took, and the *kind* of each problem found (a short
     fixed name such as `quote-not-found` or `lines-do-not-match`), not
     its text;
   - for a failure: the kind of error and where in the tool's own code it
     happened, without the error's message, which can contain file names
     or text from the materials;
   - paths with the workspace replaced by `<workspace>`, and nothing from
     inside `materials/`;
   - a space at the top for the user's own words: what they were trying to
     do, and what went wrong or was confusing.

3. **Nothing is sent by the tool.** The tool never connects to the network
   to report. `rigoraudit feedback` shows the latest report, says exactly
   what it contains, and gives the two ways to send it: a new issue on the
   tool's public repository (with a form that has a place for the report),
   or email to the developers. It says plainly that an issue is public.

4. **The user may add more, by choice.** If a problem cannot be understood
   without an example, such as an assistant's reply that the checks
   refused, the user can include it. `rigoraudit feedback --include <file>`
   adds it in a section marked as audit material, and recommends email
   rather than a public issue.

5. **Reports are read in a standard way,** written in `docs/feedback.md`:
   - each report is sorted into one kind: *a bug* (the tool did the wrong
     thing), *unclear instructions* (assistants keep making the same
     mistake), *a new situation* (a language, layout, or kind of claim the
     tool does not handle), *confusing to use*, or *a request*;
   - each gets one outcome, recorded on the issue: fixed in the code;
     instructions revised (a new version, 0011 item 7); documented;
     deferred to a decision; or declined, with the reason;
   - a fix starts with a test that reproduces the problem using an
     invented example, never the user's material (0001, and the
     repository's rule against audit content);
   - every few months, the problem kinds across all reports are counted by
     step and instructions version, to find which instructions assistants
     follow worst and which steps fail most.

## Why

Reports written by default mean the information exists whenever a user is
willing to share it, without asking them to reconstruct what happened. The
user decides whether to send it, and can read every word first, because
the tool cannot know which of their materials are private. Recording kinds
of problems rather than their text keeps reports safe to share while still
showing what goes wrong and how often. A standard way of reading them
means each report gets an answer, and repeated problems show up as
patterns rather than as scattered complaints.

## What it needs

- Every problem the checks report gets a fixed kind as well as its plain
  words. The checks now return only the words.
- The import and handoff commands record each round in the workspace, so
  the report can count corrections.

## Not yet decided

- The email address, and the issue form, which need the public repository
  (`docs/release.md`).
- Whether to offer, later, a way to send many users' counts of problem
  kinds together, with no report text at all.

## Notes

- 2026-11-01: One report per audit, `work/feedback/report.md`, instead of
  one per day and one per guided run (item 1): a single day of work had
  made dozens of reports, too many to read. Every command and guided run
  adds to it, and it opens with a summary in plain sentences that says
  whether it is worth sending.
