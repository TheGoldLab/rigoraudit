# 0005 — Initial scope and deferrals

**Status:** accepted (2026-10-27)

## Decision

- **Deferred:** tracing referenced results through citations. Referenced
  claims are still identified and classified, and the report states how many
  claims rest on citations and were not checked.
- **Later, planned:** claims from Abstract, Discussion, figure legends, and
  supplement, linked to the Results claims they restate.
- **First:** schema, then a hand-annotated gold set from the user's example
  papers, then the pipeline.

## Why

Citation verification is close to a separate product, and tools for it already
exist. The distinctive value is paper ↔ code ↔ data consistency, so that is
built first.

## Notes

- 2026-10-30: The schema and the first gold-set example are done. Figure
  legends were brought into scope with the Results in the examples. A
  second example is segmented and classified; the pipeline is not yet begun.
