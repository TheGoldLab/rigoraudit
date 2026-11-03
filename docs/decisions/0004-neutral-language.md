# 0004 — Thorough, professional, neutral language

**Status:** accepted (2026-10-27)

## Decision

The report describes what each source states and where they differ; it does
not characterize intent or quality.

- Status labels are descriptive: *Consistent*, *Differs*, *Not described*,
  *Not verifiable* — not "error", "failed", "wrong", "undisclosed", or
  "suspicious".
- Findings are ordered by **potential effect on the reported result** (e.g. a
  difference in exclusion criteria behind a headline statistic before a
  rounding difference), not by a severity judgment.
- Phrasing pattern: "Methods states X (location). The code does Y (location)."
  No adjectives about the authors or the work.
- *Not verifiable* always states the reason, without implying fault (e.g.
  "Data for this analysis are not included in the materials provided").
- Every claim is reported, including consistent ones, so the report reads as a
  complete account rather than a list of problems.

## Why

Readers may be authors, reviewers, editors, or a lab internally, and the
intended audience is not yet fixed. Neutral, evidence-first wording serves all
of them, avoids reputational harm from false positives, and keeps the tool
credible.
