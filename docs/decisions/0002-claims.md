# 0002 — Definition of a claim, claim types, and facets

**Status:** accepted (2026-10-27); segmentation rules to be refined from
hand-annotated examples.

## Decision

- A **claim** is the smallest statement that could be true or false on its own
  and that has a single evidentiary source. Claims are sub-sentence units;
  each keeps an anchor to its exact span in the manuscript.
- Claim types: new result, referenced result, comparison, interpretation,
  procedure stated in Results, no stated support.
- New-result claims are decomposed into **facets** from the start: quantity,
  population, analysis, condition, display.
- Claims are extracted from Results first. Abstract, Discussion, figure
  legends, and supplement will be added, with their claims linked to the
  Results claims they restate.

## Why

Sentences routinely mix claim types ("X increased [new], larger in condition B
[new], consistent with [12] [comparison]"). Most inconsistencies sit in a
single facet (e.g. the statistic matches but the sample size does not), so
facet-level comparison is needed to find and explain them.

## Notes

- 2026-10-30: Figure legends and tables are segmented alongside the Results
  in the example audits; legend claims that repeat a Results claim are
  linked to it (`restates`). Questions they raised for the segmentation
  rules are listed in [design.md](../design.md#open-questions).
- 2026-10-30: How statements are split into claims, from re-reading the
  example audits for merged claims. Several values of one statement stay one
  claim and are checked by scope within it ("rates rose in both groups, by 12
  and 15 sp/s" is one claim). Separate statements in one sentence are
  separate claims, even when they share a subject ("rates rose after onset
  and fell before the response" is two). A legend sentence that restates a
  Results claim is a claim of its own with `restates`, so a mismatch between
  the two can be found; a Results sentence that only repeats a nearby claim
  is a coverage exclusion naming the claim it restates.
- 2026-11-02: Procedures, in the Results or anywhere else, are traced and
  compared whole, with no facets ([0017](0017-procedures-traced-whole.md)).
