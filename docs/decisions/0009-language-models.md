# 0009 — Which stages may use a language model, and how their output is checked

**Status:** accepted (2026-10-30)

## Problem

The pipeline stages that would build a record (segment, classify, decompose,
trace, and parts of inventory) require reading prose and code with
judgment. A language model is the likely way to automate them. The design
does not yet say which stages may use one, how its output is checked, or how
the tool reaches a model. The gold records were themselves drafted in
Claude Code sessions under the user's direction, so a model already takes
part in building records, though not through the tool's code.

## Decision

1. **Stages are of two kinds.**
   - *Model-assisted:* inventory (the proposed script → figure/table map),
     segment, classify, decompose, and trace (finding the Methods statements
     and code lines behind a facet, and saying what the code does).
   - *Deterministic:* extract (text and sections), compare,
     verify, coverage, report, review, and running the authors' code or the
     audit's derivations. These never call a model.

2. **A model proposes; the checks decide.** A model-assisted stage writes its
   output to `work/` like any other stage. That output enters a record only
   by passing the same checks as a hand-built record: the schema, `verify`,
   and `coverage`. A record with failing checks is not accepted, whoever
   built it.

3. **A model never supplies a value or a status.** Values come from a
   verbatim quote or from a derivation's output (0007). Statuses are computed
   (0007). A model may write a derivation script, but its values count only
   once the script has run and `verify` has read them back.

4. **Every claim, observation, and finding records how it was produced:** by
   a person, or by a named model and version with the stage's prompt
   version. The report shows it, and reviewers can filter on it. See
   [0010](0010-provenance-and-review.md).

5. **Model stages are measured before use.** Each is scored against the
   reviewed gold records: the draft with a person's corrections applied
   (0010). The score counts claims found, missed, and invented, types that
   agree, and traces that match. The gold records were drafted by Claude
   and corrected by a person, so a Claude model's agreement with them can
   be inflated by shared habits, and errors both make go uncounted. Scores
   are therefore reported beside the agreement between two people on the
   same sample (0010's *Independent* level), and with that caveat until a
   gold record drafted without a model exists. Gold records are for
   evaluation only: no model is trained or fine-tuned on them, since records
   drafted with a provider's service fall under its terms against using it
   to develop or train models.

6. **Model access is optional and the user's own.** Model calls go through a
   single interface in the tool, with the provider and model set in
   configuration and the API key read from the environment
   (`ANTHROPIC_API_KEY` or the provider's equivalent). Without a key the
   model-assisted stages are unavailable and everything else works. The
   client library is an optional dependency. The tool ships no key and never
   uses a personal subscription.

7. **Review stays human.** Overrides (0007) are made by people. A model may
   draft a reason, but a person records the override.

## Why

The tool's value rests on every statement in the report being checkable
against the materials. Item 2 keeps that true whatever builds the record,
so a model's errors appear as failed checks, not as plausible text. Items 3
and 4 keep the two things a reader most needs to trust, the numbers and who
or what made each judgment, out of a model's discretion. Item 6 lets anyone
run the checks for free, and keeps the tool's release independent of any
provider's terms.

## Not yet decided

- Which provider and model to start with, and the interface's shape.
- Schema fields for item 4 (shared with 0010).

## Notes

- 2026-10-31: The schema fields for item 4 are built with 0010 rule 1
  (`Drafter`: model name, model ID, stage, prompt version, date).
