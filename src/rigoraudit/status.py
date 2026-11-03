# Copyright (c) 2026, Joshua I. Gold
# SPDX-License-Identifier: BSD-2-Clause
"""Where an audit stands: a paragraph generated from the record and log.

Decision 0010, rule 9. The report header and the workspace README carry
this paragraph, never written by hand: who drafted the record and when,
the mechanical results, what review has covered, whether an independent
annotation or the authors' response exists, and what remains to reach the
next level of verification. The workspace's check scripts save what they
found with :func:`save_checks`; the paragraph reads it back, and says the
checks were not run if the reviewed record (the draft with the review log
applied) has changed since. For example:

    3 claims, 2 findings. Drafted by A. Reviewer, 2026-01-01. Mechanical
    checks pass: 6 anchors verified; coverage not checked. Reviewed: 1 of 3
    claims, 0 of 2 findings (1 confirmed). Independent annotation: none.
    Authors: not contacted. Next: review 2 claims and 2 findings, claims
    first.
"""

from __future__ import annotations

import hashlib
import re
from collections import Counter
from collections.abc import Iterable, Sequence
from pathlib import Path, PurePosixPath

from pydantic import BaseModel, ConfigDict

from rigoraudit import review
from rigoraudit.coverage import Report
from rigoraudit.schema import AuditRecord, Drafter, DrafterKind
from rigoraudit.verify import AnchorCheck, Outcome
from rigoraudit.words import plural

CHECKS = PurePosixPath("work") / "checks.json"
"""Where a workspace keeps the results of its latest checks."""
BEGIN = "<!-- rigoraudit status: generated, do not edit -->"
END = "<!-- /rigoraudit status -->"

_FAILED = {
    Outcome.MISMATCH: ("does not match", "do not match"),
    Outcome.WRONG_PAGE: ("is on the wrong page", "are on the wrong page"),
    Outcome.STALE: ("comes from a stale derivation", "come from stale derivations"),
}
"""What a failing anchor does, for one anchor and for several."""
_PAST = {
    review.Operation.CONFIRM: "confirmed",
    review.Operation.EDIT: "edited",
    review.Operation.REMOVE: "removed",
    review.Operation.SPLIT: "split",
    review.Operation.MERGE: "merged",
    review.Operation.EDIT_TRACE: "retraced",
    review.Operation.OVERRIDE: "overridden",
}


class Checks(BaseModel):
    """What the latest mechanical checks found, for one version of the record."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    record_digest: str
    """:func:`digest` of the record that was checked."""
    anchors: dict[Outcome, int] | None = None
    """Anchors by outcome, from :func:`rigoraudit.verify.check_record`."""
    uncovered: int | None = None
    """Checkable items no claim covers, from the coverage check."""
    items: int | None = None
    """Checkable items in the audited text, from the coverage check."""


def digest(record: AuditRecord) -> str:
    """A short digest of the whole record."""
    return hashlib.sha256(record.model_dump_json().encode()).hexdigest()[:16]


def load_checks(workspace: Path) -> Checks | None:
    path = workspace / CHECKS
    return (
        Checks.model_validate_json(path.read_text(encoding="utf-8"))
        if path.is_file()
        else None
    )


def save_checks(
    workspace: Path,
    record: AuditRecord,
    *,
    anchors: Sequence[AnchorCheck] | None = None,
    coverage: Report | None = None,
) -> None:
    """Save check results for ``record``, keeping the other check's if it saw the same record."""
    old = load_checks(workspace)
    if old is None or old.record_digest != digest(record):
        old = Checks(record_digest=digest(record))
    update: dict = {}
    if anchors is not None:
        update["anchors"] = dict(Counter(c.outcome for c in anchors))
    if coverage is not None:
        update["uncovered"] = coverage.n_uncovered
        update["items"] = coverage.n_items
    path = workspace / CHECKS
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        old.model_copy(update=update).model_dump_json(indent=1) + "\n", encoding="utf-8"
    )


def _drafter(d: Drafter) -> str:
    if d.kind is DrafterKind.PERSON:
        return f"{d.name}, {d.date}"
    return f"{d.name} ({d.stage}), {d.date}"


def _drafted(record: AuditRecord) -> str:
    items: list = [*record.claims, *record.findings]
    for f in record.findings:
        items += f.observations
        items += [
            o.anchor.produced_by
            for o in f.observations
            if getattr(o.anchor, "produced_by", None) is not None
        ]
    others = sum(1 for i in items if i.drafted_by not in (None, record.drafted_by))
    text = f"Drafted by {_drafter(record.drafted_by)}."
    if others:
        text += f" {plural(others, 'item')} drafted by someone else."
    return text


def _mechanical(record: AuditRecord, checks: Checks | None) -> tuple[str, bool]:
    """The sentence on mechanical checks, and whether they pass."""
    if checks is not None and checks.record_digest != digest(record):
        return "Mechanical checks: not run on this version of the record.", False
    if checks is None or checks.anchors is None:
        return "Mechanical checks: not run.", False
    outcomes = Counter(checks.anchors)
    failed = [
        f"{plural(outcomes[o], 'anchor')} {what[outcomes[o] != 1]}"
        for o, what in _FAILED.items()
        if outcomes[o]
    ]
    passed = not failed
    if passed:
        verified = outcomes[Outcome.VERIFIED] + outcomes[Outcome.VERIFIED_NORMALIZED]
        text = f"Mechanical checks pass: {plural(verified, 'anchor')} verified"
        if outcomes[Outcome.UNCHECKED]:
            text += f", {outcomes[Outcome.UNCHECKED]} with nothing to check against"
    else:
        text = "Mechanical checks fail: " + ", ".join(failed)
    if checks.uncovered is None:
        text += "; coverage not checked"
    elif checks.uncovered:
        text += f"; {plural(checks.uncovered, 'checkable item')} not covered (listed)"
    return text + ".", passed


def _touched(e: review.Entry) -> set[str]:
    """IDs an applied entry leaves reviewed: its target, or what replaced it."""
    if e.operation is review.Operation.SPLIT:
        return {c.id for c in e.claims}
    return {e.target}


def _reviewed(applied: review.Applied) -> tuple[str, int, int]:
    """The sentence on review, and how many claims and findings are unreviewed.

    A claim or finding counts as reviewed once an applied entry has touched
    it, which includes the claims a reviewer adds or splits off.
    """
    record = applied.record
    touched = set().union(*(_touched(e) for e in applied.applied))
    claims = {c.id for c in record.claims} & touched
    findings = {f.id for f in record.findings} & touched
    actions = Counter(e.operation for e in applied.applied)
    n_claims, n_findings = len(record.claims), len(record.findings)
    text = (
        f"Reviewed: {len(claims)} of {plural(n_claims, 'claim')}, "
        f"{len(findings)} of {plural(n_findings, 'finding')}"
    )
    details = [f"{n} {_PAST[op]}" for op, n in actions.items() if op in _PAST]
    if actions[review.Operation.ADD]:
        details.append(f"{actions[review.Operation.ADD]} added")
    if details:
        text += f" ({', '.join(details)})"
    if stale := len(applied.stale):
        text += f"; {plural(stale, 'review action')} {'needs' if stale == 1 else 'need'} re-review"
    if refused := len(applied.refused):
        text += f"; {plural(refused, 'review action')} could not be applied"
    return text + ".", n_claims - len(claims), n_findings - len(findings)


def paragraph(
    record: AuditRecord,
    entries: Iterable[review.Entry] = (),
    *,
    checks: Checks | None = None,
    independent: str | None = None,
    authors: str | None = None,
) -> str:
    """The status paragraph for an audit: ``record`` is the draft, and the
    counts are of the reviewed record, the draft with ``entries`` applied.

    ``checks`` are the saved results of the workspace's checks
    (:func:`load_checks`), which count only if they were run on the reviewed
    record (:func:`rigoraudit.review.reviewed`). ``independent``
    and ``authors`` describe an independent annotation and the authors'
    response, when there are any, e.g. ``"20 claims, 91% agreement"``.
    """
    applied = review.apply(record, tuple(entries))
    # The checks are of the reviewed record (decision 0010, rule 6)
    mechanical, passed = _mechanical(applied.record, checks)
    reviewed, claims_left, findings_left = _reviewed(applied)
    if not passed:
        next_step = "make the mechanical checks pass"
    elif claims_left or findings_left:
        parts = [
            f"{plural(claims_left, 'claim')}" if claims_left else "",
            f"{plural(findings_left, 'finding')}" if findings_left else "",
        ]
        next_step = "review " + " and ".join(p for p in parts if p)
        if claims_left and findings_left:
            next_step += ", claims first"
    elif independent is None:
        next_step = "an independent annotation of a sample"
    elif authors is None:
        next_step = "send the findings to the authors"
    else:
        next_step = ""
    reviewed_record = applied.record
    counts = (
        f"{plural(len(reviewed_record.claims), 'claim')}, "
        f"{plural(len(reviewed_record.findings), 'finding')}."
    )
    sentences = [
        counts,
        _drafted(reviewed_record),
        mechanical,
        reviewed,
        f"Independent annotation: {independent or 'none'}.",
        f"Authors: {authors or 'not contacted'}.",
    ]
    if next_step:
        sentences.append(f"Next: {next_step}.")
    return " ".join(sentences)


def update_block(text: str, status: str) -> str:
    """Put ``status`` between the status markers in ``text`` (e.g. a README).

    The block is added at the end if the markers are absent.
    """
    block = f"{BEGIN}\n{status}\n{END}"
    pattern = re.compile(re.escape(BEGIN) + r".*?" + re.escape(END), re.DOTALL)
    if pattern.search(text):
        return pattern.sub(lambda _: block, text, count=1)
    return text.rstrip("\n") + "\n\n" + block + "\n"
