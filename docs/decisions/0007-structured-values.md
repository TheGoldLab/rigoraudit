# 0007 — Structured values, computed statuses, and how evidence was obtained

**Status:** accepted (2026-10-28)

## Problem

The first independent check of a gold record (`rigoraudit.verify`, run on
the first example audit) confirmed every manuscript and code quote it could
reach. It could not check any of the data quotes, and it could not check any
status, because the record holds both as free text. In synthetic form:

- A data quote such as `n = 12,040; mean 374.4 ms (-6.4%)` is a string. Nothing
  links it to the derivation output it came from (`per_subject_design.log`, a
  log written for people), so a mistyped or stale value would pass.
- A tolerance such as `±5% of the predicted mean 400.0 ms (380.0–420.0 ms)` is a
  string. The status beside it (*Differs*) is a judgment that nothing
  recomputes, so a misapplied rule from 0006 would pass.
- *Consistent* findings rest on evidence of very different strength (reading
  code, running the authors' code, recomputing independently), and the
  record does not say which.

Rule 0006 made every status reproducible *by a reader* from what the finding
prints. This decision makes it reproducible *by the tool*.

## Decision

1. **Values are structured.** An observation that states or yields a value
   carries it as data alongside its quote: name, value, unit, and the subject
   or selection it applies to. Stated values also record how they were stated:
   the relation (`=`, `<`, `≤`, `~`) and the precision shown (decimal places).
   The quote stays verbatim. The structured value is what comparisons use.

2. **Audit-derived values name their source.** A data or output anchor whose
   value the audit computed names the derivation script, the output file, and
   the key within it. Derivations write machine-readable output (JSON or CSV)
   alongside any log. `verify` then reads each value back from its output and
   checks that the quote renders from it.

3. **Comparisons are structured, and statuses are computed.** Each
   *Consistent* or *Differs* finding with a numeric basis (*reported
   precision*, *design vs realization*, numeric *exact*) records the values
   compared (stated, predicted where 0006 rule 1 applies, and observed) and a
   structured tolerance, using one of the kinds 0006 already defines:

   | Kind | Example from 0006 |
   |---|---|
   | exact | 41 vs 40 sessions |
   | precision | 4.12 reported vs 4.57 recomputed, at 2 decimals |
   | inequality | "p < 0.001" checked as stated |
   | relative | ±5% of predicted 400.0 ms |
   | absolute | ±2 percentage points of 50% |
   | range | all values within 100–1200 ms |
   | sign | "shallower", "increases" |

   For these findings the schema computes the status from the comparisons
   and fills it in. A builder never needs to set it. A status that disagrees
   with the comparisons fails the build and names the finding, so a record
   cannot contradict its own values. `record.json` still contains the computed
   status, for readability. The printed
   `tolerance` text is generated from the structure, so the rule printed and
   the rule applied cannot diverge. Non-numeric comparisons (codings,
   identities, named tests) keep the current form.

4. **Each observation states how it was obtained**:
   - *quoted*: manuscript text;
   - *read*: code inspected, not run;
   - *executed*: the authors' code run by the audit, by a script that saves
     its output;
   - *recomputed*: the audit's own computation (e.g. SciPy tests).

   The claim card shows this beside each source. A *Consistent* resting only
   on *read* code is visibly weaker than one resting on *executed* or
   *recomputed* values.

5. **Reviewers override from the report; overrides live in `review/`.**
   - `rigoraudit review <workspace>` serves the report locally. Each finding
     has an *Override* button that opens a short form (status, reason) and
     writes the entry to `review/overrides.json`, with the reviewer and date
     (JSON rather than YAML, so the tool needs no YAML dependency).
     The report is not hosted online, because it contains unpublished
     materials.
   - The report shows both, e.g. *Computed: Differs (−6.4%, tolerance ±5%) ·
     Reviewer: Consistent — "reason" (name, date)*. Summaries count
     overridden findings separately.
   - Each override records a fingerprint of the values and tolerance it was
     made against. If a rebuild changes them, the override is marked
     **stale**: it is shown for re-review and not applied.

6. **Findings have stable IDs**, so overrides and other references survive a
   rebuild, e.g. `R1.1.b/condition/mean-B`. IDs are unique within a record.

## Example (synthetic)

| Finding | Values | Tolerance | Computed status |
|---|---|---|---|
| R1.1.b mean, B | predicted 400.0 ms; observed 374.4 ms (recomputed) | relative ±5% | Differs (−6.4%) |
| R1.2.a switch rate, B | stated 30%; observed 33.5% (recomputed) | absolute ±2 pp | Differs |
| R2.1.c SEM, A | reported 4.12 (2 dp); observed 4.57 (recomputed) | precision | Differs |
| R2.1.d | reported "~80" ms; observed 83.0 ms (recomputed) | relative ±10% (hedged) | Consistent |
| F3.B.a sessions, C | stated 41; observed 40 (executed) | exact | Differs |
| R3.2.a | stated larger with larger (+); observed rho −0.31 (recomputed) | sign | Differs |

## Costs

- The schema version becomes 3. Existing records must restate their findings
  in the new form. This is most of the work and is best done claim by claim,
  checking each computed status against the current one. A disagreement is
  either an error in the record or a gap in the rule, and each is worth
  recording.
- The derivations must write machine-readable output. Today most write logs,
  and only some write CSV.
- The review server is new code: a small local web server and the report's
  override form. No dependency is added until it is built and approved.

## Why

An audit that claims to be accurate has to be checkable by something other
than the reader's patience. With values and tolerances as data, `verify` can
confirm every value against its source and every status against its rule.
That leaves human review for what only a person can judge: whether the right
evidence was compared at all.

Disagreements are handled differently depending on who disagrees. When the
builder (the pipeline, or whoever writes the record) disagrees with the
numbers, it is almost always a mistake, so the build refuses it. When a
reviewer disagrees, it is a judgment, so recording it is easy and the
override stays visible. Stale overrides keep a judgment from carrying over
to values the reviewer never saw.

## Notes

- 2026-10-30: [0010](0010-provenance-and-review.md) (proposed) makes an
  override one kind of entry in a single log of review actions, beside
  confirming and correcting a record's structure.
- 2026-10-30: The examples above are synthetic. The originals, from an
  example audit, were moved to that audit's workspace so that this
  repository holds no audit content (see [release.md](../release.md)).
- 2026-10-31: Derivation outputs now also accept lists and true/false.
  A list is stored as numbered keys (`onsets/0`, `onsets/1`), so the record
  still cites one value at a time. True and false are kept as they are, for
  exact comparisons only, and never count as equal to 1 or 0.
- 2026-10-31: Overrides are kept in the review log, `review/log.json`
  (0010), not in `review/overrides.json`, and that file is no longer read.
