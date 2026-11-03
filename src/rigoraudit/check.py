# Copyright (c) 2026, Joshua I. Gold
# SPDX-License-Identifier: BSD-2-Clause
"""The mechanical checks of a workspace's record: ``rigoraudit check``.

Both checks run on the reviewed record (the draft with the review log
applied, decision 0010, rule 6), and read everything else from the
workspace:

- **Anchors** (:mod:`rigoraudit.verify`): every manuscript quote against
  the PDF's text layer (``work/extract/published.txt``) and its paragraph
  in ``paragraphs.json``; every code quote against the cited lines at its
  commit; every data file against its checksum in the manifest; every
  value against the derivation output it names. Quotes from paragraphs
  marked ``transcribed`` (typed in from a figure's image) are not in the
  text layer, so they are reported as unchecked, not as mismatches.
- **Coverage** (:mod:`rigoraudit.coverage`): every number, comparison word,
  and test name in the audited sections (the manifest's ``settings ›
  scope``) must be inside a claim, a quote used as evidence, or an
  exclusion: an item the segment step left out, with its reason, or one
  listed in ``record/coverage_exclusions.json``.
- **Cross-claim checks** (:mod:`rigoraudit.crosscheck`): values printed
  in more than one claim, in the groups the crosscheck step confirmed,
  compared with each other, are written to
  ``work/crosscheck/findings.json``. A value that differs is reported in
  the report, not as a problem with the record, and so is a step still
  waiting for its answer.
- **Gaps**: every claim named in the manifest's ``gaps`` must be in the
  record. Names a gap gives that are in the materials (a data file, a name
  saved in one, a function) are shown to look at again, without failing.

The results are saved in ``work/checks.json`` for the status paragraph
(:mod:`rigoraudit.status`).
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from rigoraudit import (
    crosscheck,
    materials,
    review,
    segment,
    settings,
    stats,
    status,
)
from rigoraudit.coverage import (
    EXCLUSIONS,
    Exclusion,
    Exclusions,
    Report,
    record_coverage,
)
from rigoraudit.extract import TEXT, read_text
from rigoraudit.paragraphs import PARAGRAPHS, in_scope, read_paragraphs
from rigoraudit.schema import RECORD, AuditRecord, CrossFinding
from rigoraudit.verify import AnchorCheck, Outcome, check_record
from rigoraudit.words import plural

FAILED = (Outcome.MISMATCH, Outcome.WRONG_PAGE, Outcome.STALE)
"""Anchor outcomes that fail the check."""


@dataclass(frozen=True)
class Result:
    anchors: list[AnchorCheck]
    coverage: Report
    exclusions: int
    gap_claims: tuple[str, ...] = ()
    """Claims named in the manifest's gaps that are not in the record."""
    gap_notes: tuple[str, ...] = ()
    """Names a gap gives that are in the materials, to look at again; they
    do not fail the checks (:func:`rigoraudit.materials.gap_notes`)."""
    cross: tuple[CrossFinding, ...] | None = ()
    """Values printed in more than one claim, compared; ``None`` while the
    crosscheck step waits for an answer. Neither fails the checks."""

    @property
    def passed(self) -> bool:
        return not (
            any(c.outcome in FAILED for c in self.anchors)
            or self.coverage.gaps
            or self.coverage.unused
            or self.gap_claims
        )


def read_exclusions(workspace: Path) -> tuple[Exclusion, ...] | None:
    """The coverage exclusions: the segment step's left-out items, then those
    in :data:`~rigoraudit.coverage.EXCLUSIONS`; ``None`` if there are neither."""
    path = workspace / EXCLUSIONS
    own = (
        Exclusions.model_validate_json(path.read_text(encoding="utf-8")).exclusions
        if path.is_file()
        else None
    )
    left_out = segment.exclusions(workspace)
    if own is None and not left_out:
        return None
    return left_out + (own or ())


def run(workspace: Path) -> Result:
    """Check the workspace's reviewed record and save the results."""
    path = workspace / RECORD
    if not path.is_file():
        raise FileNotFoundError(f"no record in {workspace}: {RECORD} is missing")
    record = review.reviewed(
        AuditRecord.model_validate_json(path.read_text(encoding="utf-8")), workspace
    )
    s = settings.load(workspace)
    paragraphs = read_paragraphs(workspace / PARAGRAPHS)
    anchors = check_record(
        record,
        workspace / "materials",
        read_text(workspace / TEXT),
        workspace=workspace,
        paragraphs={(p.section, p.number): p.text for p in paragraphs},
        checksums=s.checksums,
        image_sections={p.section for p in paragraphs if p.transcribed},
        readings=stats.READINGS,
    )
    label = {(p.section, p.number): p.label for p in paragraphs}
    claim_para = {
        c.id: label[key]
        for c in record.claims
        if (key := (c.anchor.section, c.anchor.paragraph)) in label
    }
    audited = {p.label: p.text for p in paragraphs if in_scope(p.section, s.scope)}
    exclusions = read_exclusions(workspace) or ()
    coverage = record_coverage(record, audited, claim_para, exclusions)
    status.save_checks(workspace, record, anchors=anchors, coverage=coverage)
    ids = {c.id for c in record.claims}
    unknown = sorted({c for g in s.gaps for c in g.claims} - ids)
    notes = tuple(materials.gap_notes(workspace, s, s.gaps))
    cross = crosscheck.write(workspace, record)
    return Result(anchors, coverage, len(exclusions), tuple(unknown), notes, cross)


def describe(result: Result) -> str:
    """What the checks found, for people: counts, then each problem."""
    outcomes = Counter(c.outcome for c in result.anchors)
    verified = outcomes[Outcome.VERIFIED] + outcomes[Outcome.VERIFIED_NORMALIZED]
    counts = [f"{verified} verified"]
    for outcome, what in (
        (Outcome.UNCHECKED, "with nothing to check against"),
        (Outcome.MISMATCH, "not matching"),
        (Outcome.WRONG_PAGE, "on the wrong page"),
        (Outcome.STALE, "from a derivation that needs rerunning"),
    ):
        if outcomes[outcome]:
            counts.append(f"{outcomes[outcome]} {what}")
    cov = result.coverage
    lines = [
        f"Anchors: {len(result.anchors)} checked; {', '.join(counts)}.",
        (
            f"Coverage: {cov.n_items} numbers, comparison words, and test names "
            f"in the audited sections; {cov.n_uncovered} not covered. "
            f"{plural(result.exclusions, 'exclusion')}, {len(cov.unused)} unused."
        ),
        crosscheck.describe(result.cross),
    ]
    for c in result.anchors:
        if c.outcome in FAILED:
            lines += [
                "",
                f"{c.outcome.replace('_', ' ').upper()}: {c.location}",
                f"  quote: {c.quote[:120]!r}",
                f"  {c.detail}",
            ]
    for g in cov.gaps:
        lines += [
            "",
            f"NOT COVERED in {g.paragraph}: {', '.join(i.text for i in g.items)}",
            f"  {g.sentence}",
        ]
    for e in cov.unused:
        lines += [
            "",
            (
                f"UNUSED EXCLUSION in {e.paragraph}: its quote is no longer in "
                f"the paragraph: {e.quote!r}"
            ),
        ]
    if result.gap_claims:
        lines += [
            "",
            f"GAPS name claims not in the record: {', '.join(result.gap_claims)}",
        ]
    for note in result.gap_notes:
        lines += [
            "",
            (
                f"LOOK AGAIN: {note} If the gap names them to say what is "
                f"there, nothing to do. If not, make sure what it calls missing "
                f"is not there ({materials.LIST.as_posix()} lists every file)."
            ),
        ]
    verdict = (
        "All checks pass."
        if result.passed
        else "Fix each problem above (in the record, the paragraphs, the "
        "exclusions, or the manifest's gaps), then run rigoraudit check again."
    )
    lines += ["", f"{verdict} The results are saved in {status.CHECKS}."]
    return "\n".join(lines)
