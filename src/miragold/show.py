# Copyright (c) 2026, Joshua I. Gold
# SPDX-License-Identifier: BSD-2-Clause
"""Everything the audit holds on one claim, as text (``miragold show``).

A view of the record for whoever develops the tool or reviews results,
so they need not open the files in ``work/`` and ``record/``
(docs/development.md, "Working in an audit's workspace"). It gives the
claim; what each source says about each facet, every observation labelled
``O1``, ``O2``, … as in the compare handoff; the values that could not be
recomputed; the findings, by those labels; the gaps that name the claim;
the cross-claim findings that hold it; and the review actions on it.

The record is built from the accepted answers, as ``miragold record``
builds it, so it shows the latest answers; an audit with its own
``record/record.py`` is read from ``record/record.json``. Either way the
review log is applied, as in the report.
"""

from __future__ import annotations

from pathlib import Path

from miragold import compare, crosscheck, review, settings
from miragold.report import BASIS_LABEL, EFFECT_LABEL
from miragold.schema import RECORD, AuditRecord, Comparison, Facet, Observation
from miragold.settings import Settings


def _record(workspace: Path, s: Settings) -> tuple[AuditRecord, str | None]:
    """The draft record, and a note if the saved one is older than the answers."""
    built = compare.draft_record(workspace, s)
    if built is None:
        raise FileNotFoundError(
            f"no record in {workspace}: run {compare.SCRIPT} to build {RECORD}"
        )
    path = workspace / RECORD
    note = None
    own = (workspace / compare.SCRIPT).is_file()
    if (
        not own
        and path.is_file()
        and AuditRecord.model_validate_json(path.read_text(encoding="utf-8")) != built
    ):
        note = (
            f"{RECORD} is older than the accepted answers shown here; the report "
            "and the check read it, so run `miragold record` to bring it up to date."
        )
    return built, note


def _values(c: Comparison) -> str:
    def shown(vs) -> str:
        return ", ".join(
            f"{v.name} {'= ' if v.relation == '=' else ''}{v.printed()}" for v in vs
        )

    against = f" (predicted: {shown([c.predicted])})" if c.predicted else ""
    if c.span:
        against += f" (span: {shown(c.span)})"
    line = f"{c.kind}: stated {shown(c.stated)}{against}; observed {shown(c.observed)}"
    return f"{line} — agrees" if c.agrees() else f"**{line} — does not agree**"


def render(workspace: Path, claim_id: str) -> str:
    """Everything the audit holds on claim ``claim_id``, as Markdown."""
    s = settings.load(workspace)
    draft, note = _record(workspace, s)
    entries = review.load(workspace / review.LOG)
    applied = review.apply(draft, entries)
    record = applied.record
    claim = next((c for c in record.claims if c.id == claim_id), None)
    if claim is None:
        if claim_id in applied.retired:
            raise ValueError(
                f"claim {claim_id} was removed, split, or merged in review; "
                "see review/log.json"
            )
        first = record.claims[0].id if record.claims else "R1.1.a"
        raise ValueError(
            f"there is no claim {claim_id} in the record; claim IDs look like {first}"
        )
    findings = [f for f in record.findings if f.claim_id == claim_id]
    overrides, _ = review.current(record, entries)

    a = claim.anchor
    page = f", page {a.page}" if a.page else ""
    out = [f"# Claim {claim.id}", ""]
    if note:
        out += [f"Note: {note}", ""]
    out += [
        f"{claim.type}, {claim.trace}; {a.section}, paragraph {a.paragraph}{page}.",
        "",
        f"> {a.quote}",
    ]
    links = [
        ("Rests on", ", ".join(claim.depends_on)),
        ("Cites", "; ".join(claim.citations)),
        ("Restates", claim.restates or ""),
    ]
    if any(text for _, text in links):
        out.append("")
        out += [f"- {name}: {text}" for name, text in links if text]

    # Observations from the answers, then any a finding holds that they lack
    task = None
    if claim_id in compare.decomposed(workspace):
        [[task]] = compare.claim_tasks(workspace, s, [[claim_id]])
    labelled: dict[str, Observation] = dict(task.observations) if task else {}
    facet_of: dict[str, Facet | None] = dict(task.facet_of) if task else {}
    for f in findings:
        for o in f.observations:
            if o not in labelled.values():
                label = f"O{len(labelled) + 1}"
                labelled[label] = o
                facet_of[label] = f.facet
    if labelled:
        out += ["", "## What each source says"]
        for facet in dict.fromkeys(facet_of.values()):
            out += ["", f"### {facet or 'whole claim'}", ""]
            for label, o in labelled.items():
                if facet_of[label] == facet:
                    out += compare.describe(label, o)
    context = [x for x in record.context if x.claim_id == claim_id]
    if context:
        out += ["", "## Beside each test (no status)", ""]
        for x in context:
            lines = " ".join(t for t in (x.assumes, x.data) if t)
            head = f"{x.scope.capitalize()}, {x.test}" if x.scope else x.test
            out.append(f"- {head}{': ' + lines if lines else ''}")
    if task and task.cannot:
        out += ["", "### Values that could not be recomputed", ""]
        out += [f"- {x}" for x in task.cannot]

    if findings:
        out += ["", "## Findings"]
    for f in findings:
        out += ["", f"### `{f.id}`: {f.status}", "", f.summary, ""]
        compared = [
            next(lab for lab, o in labelled.items() if o == x) for x in f.observations
        ]
        out.append(f"- Observations: {', '.join(compared)}")
        if f.basis:
            out.append(f"- Compared by {BASIS_LABEL[f.basis]}")
        out += [f"- {_values(c)}" for c in f.comparisons]
        if tolerance := f.tolerance_text:
            out.append(f"- Tolerance: {tolerance}")
        if f.not_described_in:
            out.append(f"- Silent: {', '.join(f.not_described_in)}")
        if f.reason:
            out.append(f"- Why it cannot be compared: {f.reason}")
        if effect := EFFECT_LABEL[f.effect]:
            out.append(f"- Possible effect: {effect}")
        if r := overrides.get(f.id):
            stale = ", made before the finding last changed" if r.stale else ""
            out.append(
                f"- Reviewer's status: {r.override.status} "
                f"({r.override.reviewer}{stale})"
            )

    gaps = [g for g in s.gaps if claim_id in g.claims]
    if gaps:
        out += ["", "## Gaps", ""]
        out += [
            f"- Missing: {g.missing}" + (f" Instead: {g.instead}" if g.instead else "")
            for g in gaps
        ]

    cross = crosscheck.current(workspace, record)
    if cross is None:
        out += ["", "## Cross-claim checks", "", crosscheck.describe(None)]
    elif mine := [x for x in cross if claim_id in x.claim_ids]:
        out += ["", "## Cross-claim checks", ""]
        for x in mine:
            out.append(f"- `{x.id}`: {x.status}. {x.summary} {x.reason}")
            out += [
                f"  - {cid}: “{a.quote}” ({a.section})"
                for cid, a in crosscheck.quotes(x)
            ]

    mine = [
        e
        for e in entries
        if e.target == claim_id or e.target.startswith(f"{claim_id}/")
    ]
    if mine:
        stale = set(map(id, applied.stale)) | {id(e) for e, _ in applied.refused}
        out += ["", "## Review", ""]
        for e in mine:
            status = f" to {e.status}" if e.status else ""
            flag = (
                " (not applied: its target changed or it was refused)"
                if id(e) in stale
                else ""
            )
            out.append(
                f"- {e.date}, {e.reviewer}: {e.operation}{status} `{e.target}`: "
                f"{e.reason}{flag}"
            )
    return "\n".join(out) + "\n"
