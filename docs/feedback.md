# Reading feedback reports

How the developers read the feedback reports users send
([decision 0012](decisions/0012-feedback-reports.md)). Every report gets an
answer, and every answer is one of the outcomes below.

## What a report holds

A report (`work/feedback/report.md` in the user's workspace, one for the
whole audit) has:

- *Summary*: the rest of the report in a few plain sentences, and whether
  it is worth sending, for the user;
- *In your words*: what the user was trying to do and what went wrong;
- *The tool*: the tool's version, Python, and the operating system;
- *What happened*: each command, the step and instructions version, how it
  ended, how long it took, and the kinds of problems found in the answer;
- *Tries per accepted answer*, *Problems sent back, by kind*, and
  *Failures*: the error's type and where in the tool's code it happened;
- sometimes, *Audit material you added*: text the user chose to include.

It holds no text from the materials unless the user added it.

## For each report

1. **Check for audit material.** If a public issue carries material from a
   manuscript or code that may be private, hide the issue's text and ask
   the user to send it by email instead.
2. **Sort it into one kind:**
   - *Bug*: the tool did the wrong thing, or failed (a *Failures* entry);
   - *Unclear instructions*: assistants keep making the same mistake (one
     problem kind sent back many times, or many tries per answer);
   - *New situation*: a language, a manuscript layout, or a kind of claim
     the tool does not handle;
   - *Confusing to use*: the tool worked, but the user could not tell what
     to do;
   - *Request*: something the tool does not do and the user would like.
3. **Give it one outcome**, and write it on the issue:
   - *Fixed*: a code change, with the commit;
   - *Instructions revised*: a new version of the step's instructions
     (`src/rigoraudit/instructions/`), with the version number;
   - *Documented*: a change to the README or docs;
   - *Deferred to a decision*: a record in `docs/decisions/`, proposed;
   - *Declined*: with the reason.
4. **Fix with an invented example.** A fix starts with a test that
   reproduces the problem using made-up text, code, and values with the same
   structure as the user's. Never copy the user's material into the
   repository, even when they sent it (decision 0001, and `CLAUDE.md`).

## Every few months

Count the problem kinds across all reports since the last count, by step
and instructions version. The kinds sent back most often, and the steps
with the most tries per answer, show which instructions assistants follow
worst; rewrite those first. Note the count and what was changed below.

## Counts

None yet.
