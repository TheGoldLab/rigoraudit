# Copyright (c) 2026, Joshua I. Gold
# SPDX-License-Identifier: BSD-2-Clause
"""Compare the sources for each claim, and build the record from the answers
(decisions 0006, 0007, 0011).

After deriving, the decomposed claims are handed to an assistant, up to
:data:`MAX_CLAIMS` at a time, with what each source says about each facet,
every item labelled: the Results quote
and its values, the Methods passages, the code lines, and the values the
derivations saved (``rigoraudit/instructions/compare.md``). The answer gives
the findings: for each facet, which observations it compares, the basis and
the comparisons, by label, and a neutral summary. The tool builds each
finding with :mod:`rigoraudit.schema`, which computes the status of every
numeric comparison and refuses a finding that breaks the record's rules;
its reasons are sent back as problems.

Procedure claims, traced whole, are handed off on their own, up to
:data:`MAX_PROCEDURES` at a time, each with its own words and values, and
the Methods and code the trace found; each gets findings for the claim as a
whole, with no facet (decision 0017).

Accepted answers are kept in ``work/compare/answers/``, with the findings
built from them. :func:`write_record` puts the claims of every accepted
segment answer and these findings together as ``record/record.json``. A
workspace with its own ``record/record.py`` builds its record that way
instead.
"""

from __future__ import annotations

import datetime
import re
from collections import Counter
from collections.abc import Sequence
from pathlib import Path

from pydantic import ValidationError

from rigoraudit import decompose, derive, handoffs, instructions, segment, stats, trace
from rigoraudit.handoffs import AnswerError, Problem, Problems
from rigoraudit.paragraphs import PARAGRAPHS, Paragraph, read_paragraphs
from rigoraudit.schema import (
    RECORD,
    AuditRecord,
    Basis,
    ClaimId,
    ClaimType,
    Comparison,
    Drafter,
    DrafterKind,
    Effect,
    Facet,
    Finding,
    Frozen,
    Kind,
    NonEmptyStr,
    Observation,
    Source,
    Status,
    Trace,
    Value,
)
from rigoraudit.settings import Settings

STEP = "compare"
NOUNS = {"claims": "claim", "findings": "finding", "comparisons": "comparison"}
MAX_CLAIMS = 10
"""Decomposed claims per handoff."""
MAX_PROCEDURES = 15
"""Procedure claims per handoff; each is compared whole."""
WHOLE = "whole"
"""The part of a finding's ID that stands for the whole claim."""
STATING = (Source.RESULTS, Source.METHODS)
"""Sources whose values are stated, not obtained."""
SCRIPT = Path("record") / "record.py"
"""A workspace's own script for its record, if it has one."""


class ComparisonAnswer(Frozen):
    kind: Kind
    stated: tuple[NonEmptyStr, ...]
    """Labels of stated values, e.g. ``O1.v1``; for ``sign``, ``+`` or ``-``
    for the direction the words in ``hedge`` state."""
    observed: tuple[NonEmptyStr, ...]
    predicted: str | None = None
    amount: float | None = None
    hedge: str | None = None


class FindingAnswer(Frozen):
    facet: Facet | None = None
    """None for a procedure, compared whole."""
    scope: str | None = None
    observations: tuple[NonEmptyStr, ...]
    status: Status | None = None
    """Only for findings without comparisons; the tool computes the rest."""
    basis: Basis | None = None
    comparisons: tuple[ComparisonAnswer, ...] = ()
    tolerance: str | None = None
    not_described_in: tuple[Source, ...] = ()
    reason: str | None = None
    summary: NonEmptyStr
    effect: Effect = Effect.UNKNOWN


class ClaimFindings(Frozen):
    claim: ClaimId
    findings: tuple[FindingAnswer, ...]


class CompareAnswer(Frozen):
    instructions: NonEmptyStr
    claims: tuple[ClaimFindings, ...]


class ClaimTask(Frozen):
    claim: ClaimId
    quote: NonEmptyStr
    paragraph: NonEmptyStr
    """The paragraph's label."""
    observations: dict[str, Observation]
    """Each observation by its label, ``O1``, numbered through the handoff."""
    facet_of: dict[str, Facet | None]
    facets: tuple[Facet, ...]
    """Empty for a procedure, compared whole."""
    cannot: tuple[str, ...]
    """Values the derive step could not recompute, and why."""
    checked: tuple[str, ...] = ()
    """What the tool has checked itself (:mod:`rigoraudit.stats`), one line each."""
    checked_facets: tuple[Facet, ...] = ()
    """The facets those checks cover, which need no further finding."""
    whole: bool = False
    """A procedure, compared as a whole claim."""


class Handoff(Frozen):
    name: NonEmptyStr
    instructions: NonEmptyStr
    claims: tuple[ClaimTask, ...]
    paragraphs: dict[str, str]
    places: dict[str, str]


class Accepted(Frozen):
    handoff: NonEmptyStr
    claims: tuple[ClaimId, ...]
    drafted_by: NonEmptyStr
    imported: NonEmptyStr
    answer: CompareAnswer
    findings: tuple[Finding, ...]


def parse_answer(text: str) -> CompareAnswer:
    return handoffs.parse_reply(text, CompareAnswer, NOUNS)


def read_accepted(workspace: Path) -> list[Accepted]:
    return handoffs.read_answers(workspace, STEP, Accepted)


def pending_handoffs(workspace: Path) -> list[Handoff]:
    answered = {a.handoff for a in read_accepted(workspace)}
    return handoffs.read_pending(workspace, STEP, Handoff, answered)


def plan_handoffs(
    workspace: Path,
    settings: Settings,
    max_claims: int = MAX_CLAIMS,
    max_procedures: int = MAX_PROCEDURES,
) -> list[Handoff]:
    """Handoffs for the decomposed claims, then the traced procedures, that no
    accepted answer covers yet, up to ``max_claims`` or ``max_procedures``
    each, in reading order."""
    done = {c for a in read_accepted(workspace) for c in a.claims}
    paragraphs = {p.label: p for p in read_paragraphs(workspace / PARAGRAPHS)}
    version = instructions.load(STEP).label
    groups = []
    for todo, size in (
        (decomposed(workspace), max_claims),
        (procedures(workspace, settings), max_procedures),
    ):
        todo = [c for c in todo if c not in done]
        groups += [todo[i : i + size] for i in range(0, len(todo), size)]
    out = []
    for tasks in claim_tasks(workspace, settings, groups):
        labels = list(dict.fromkeys(c.paragraph for c in tasks))
        out.append(
            Handoff(
                name=f"compare-{tasks[0].claim}",
                instructions=version,
                claims=tuple(tasks),
                paragraphs={lab: paragraphs[lab].text for lab in labels},
                places={lab: paragraphs[lab].place for lab in labels},
            )
        )
    return out


def decomposed(workspace: Path) -> list[str]:
    """The IDs of the decomposed claims, in the order they were answered."""
    return [c.id for a in decompose.read_accepted(workspace) for c in a.answer.claims]


def procedures(workspace: Path, settings: Settings) -> list[str]:
    """The IDs of the traced procedure claims, in reading order."""
    if settings.code is None:
        return []
    traced = trace.procedure_observations(workspace, settings)
    return [
        c.id
        for c in segment.claims_of(workspace, ClaimType.PROCEDURE)
        if c.id in traced
    ]


def claim_tasks(
    workspace: Path, settings: Settings, groups: Sequence[Sequence[str]]
) -> list[list[ClaimTask]]:
    """What each source says about each facet of each decomposed claim, by
    group of claims; the observations are labelled ``O1``, ``O2``, … through
    each group."""
    where = {
        c.id: c
        for c in segment.claims_of(workspace, ClaimType.NEW_RESULT, ClaimType.PROCEDURE)
    }
    results = decompose.results_observations(workspace, settings.manuscript)
    traced = trace.trace_observations(workspace, settings) if settings.code else {}
    whole = trace.procedure_observations(workspace, settings) if settings.code else {}
    derived = derive.derived_observations(workspace, settings)
    stated = derive.stated_values(workspace)
    cannot = derive.cannot(workspace)
    by_tool: dict[str, list[Finding]] = {}
    for f in tool_findings(workspace, settings):
        by_tool.setdefault(f.claim_id, []).append(f)
    out = []
    for group in groups:
        tasks, n = [], 0
        for claim in group:
            if claim in whole:
                observations = {f"O{n + k}": o for k, o in enumerate(whole[claim], 1)}
                n += len(observations)
                tasks.append(
                    ClaimTask(
                        claim=claim,
                        quote=where[claim].quote,
                        paragraph=where[claim].paragraph,
                        observations=observations,
                        facet_of=dict.fromkeys(observations),
                        facets=(),
                        cannot=(),
                        whole=True,
                    )
                )
                continue
            facets = results[claim]
            observations: dict[str, Observation] = {}
            facet_of: dict[str, Facet] = {}
            for facet in Facet:
                found = [
                    *([facets[facet]] if facet in facets else []),
                    *traced.get(claim, {}).get(facet, []),
                    *derived.get(claim, {}).get(facet, []),
                ]
                for o in found:
                    n += 1
                    observations[f"O{n}"] = o
                    facet_of[f"O{n}"] = facet
            tasks.append(
                ClaimTask(
                    claim=claim,
                    quote=where[claim].quote,
                    paragraph=where[claim].paragraph,
                    observations=observations,
                    facet_of=facet_of,
                    facets=tuple(facets),
                    cannot=tuple(
                        f"{s.name} = {s.printed} ({s.facet}): {reason}"
                        if (s := stated.get(claim, {}).get(label))
                        else f"{label}, as stated in words: {reason}"
                        for label, reason in cannot.get(claim, {}).items()
                    ),
                    checked=tuple(
                        f"{f.facet}, {f.scope}: {f.status}. {f.summary}"
                        for f in by_tool.get(claim, [])
                    ),
                    checked_facets=tuple(
                        dict.fromkeys(
                            f.facet for f in by_tool.get(claim, []) if f.facet
                        )
                    ),
                )
            )
        out.append(tasks)
    return out


def describe(label: str, o: Observation) -> list[str]:
    """One observation as Markdown lines: its label, source, place, and
    statement, then its quote and its values, labelled ``O1.v1``, …"""
    a = o.anchor
    where = {
        "manuscript": lambda: f"{a.section}, paragraph {a.paragraph}",
        "code": lambda: f"`{a.file}`, lines {a.line_start}–{a.line_end}",
        "data": lambda: (
            f"`{a.file}`, by `{o.anchor.produced_by.script}`"
            if a.produced_by
            else f"`{a.file}`"
        ),
    }[a.kind]()
    lines = [f"- `{label}` ({o.source}, {o.obtained}; {where}): {o.statement}"]
    if a.kind == "code":
        lines += ["", "  ```", *(f"  {x}" for x in a.quote.splitlines()), "  ```"]
    elif a.kind == "manuscript":
        lines.append(f"  > {a.quote}")
    for i, v in enumerate(o.values, 1):
        extra = [f"for {v.subject}"] if v.subject else []
        extra += [f"{v.decimals} decimals shown"] if v.decimals is not None else []
        lines.append(
            f"  - `{label}.v{i}`: {v.name} {v.printed()}"
            + (f" ({', '.join(extra)})" if extra else "")
        )
    return lines


def render_handoff(h: Handoff) -> str:
    body = []
    for label, text in h.paragraphs.items():
        body += ["", f"## Paragraph {label} ({h.places[label]})", "", text]
        for c in h.claims:
            if c.paragraph != label:
                continue
            body += ["", f"### Claim `{c.claim}`", "", f"> {c.quote}"]
            if c.whole:
                body += ["", "A procedure: compare it as a whole claim.", ""]
                for ref, o in c.observations.items():
                    body += describe(ref, o)
            for facet in c.facets:
                body += ["", f"#### {facet}", ""]
                for ref, o in c.observations.items():
                    if c.facet_of[ref] is facet:
                        body += describe(ref, o)
            if c.cannot:
                body += ["", "#### Values that could not be recomputed", ""]
                body += [f"- {x}" for x in c.cannot]
            if c.checked:
                body += ["", "#### Already checked by the tool; do not repeat", ""]
                body += [f"- {x}" for x in c.checked]
    return handoffs.render(STEP, h.name, h.instructions, _covers(h.claims), body)


def _covers(claims) -> str:
    """What a handoff covers, for its first line."""
    if len(claims) == 1:
        return f"claim `{claims[0].claim}`"
    return f"the {len(claims)} claims below; give findings for every one"


def write_handoffs(workspace: Path, settings: Settings) -> list[Path]:
    """Write the handoffs still needed; return the files to paste."""
    answered = {a.handoff for a in read_accepted(workspace)}
    return handoffs.write_handoffs(
        workspace,
        STEP,
        ((h.name, h, render_handoff(h)) for h in plan_handoffs(workspace, settings)),
        answered,
    )


def _slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", text).strip("-") or "part"


def build_findings(answer: CompareAnswer, h: Handoff) -> tuple[list[Finding], Problems]:
    """The findings an answer gives, and every problem with them."""
    problems = handoffs.version_problem(STEP, answer.instructions)
    tasks = {c.claim: c for c in h.claims}
    problems.extend(handoffs.claims_problems([c.claim for c in answer.claims], tasks))
    findings: list[Finding] = []
    for c in answer.claims:
        if c.claim in tasks:
            found, more = _claim_findings(c, tasks[c.claim])
            findings += found
            problems.extend(more)
    return findings, problems


def _claim_findings(
    answer: ClaimFindings, h: ClaimTask
) -> tuple[list[Finding], Problems]:
    """One claim's findings, and every problem with them."""
    problems = Problems()
    if h.whole:
        if not answer.findings:
            problems.add(
                "finding-missing",
                f"Claim {h.claim} has no finding; give one for the claim as a whole, "
                "if need be as not_verifiable with the reason.",
            )
        if any(f.facet for f in answer.findings):
            problems.add(
                "facet-given",
                f"Claim {h.claim} is a procedure, compared whole: give its findings "
                "no facet.",
            )
    elif any(f.facet is None for f in answer.findings):
        problems.add(
            "facet-not-named",
            f"Claim {h.claim} is split into facets: give each finding its facet.",
        )
    covered = {f.facet for f in answer.findings} | set(h.checked_facets)
    for facet in h.facets:
        if facet not in covered:
            problems.add(
                "facet-missing",
                f"Claim {h.claim} has no finding for the {facet}; give one, if need be as "
                "not_verifiable with the reason.",
            )
    findings, ids = [], Counter()
    for n, f in enumerate(answer.findings, 1):
        where = f"Claim {h.claim}, finding {n} ({f.facet or 'whole claim'})"
        unknown = [o for o in f.observations if o not in h.observations]
        if unknown:
            problems.add(
                "unknown-label",
                f"{where} names {', '.join(unknown)}, which the task does not have.",
            )
            continue

        items = {o: h.observations[o] for o in f.observations}

        def value(ref: str, where=where):
            label, _, i = ref.partition(".v")
            o = h.observations.get(label)
            if o is None or not i.isdigit() or not 1 <= int(i) <= len(o.values):
                raise LookupError(f"{where} names value {ref}, which the task does not have.")  # fmt: skip
            return o.values[int(i) - 1]

        def stated(c: ComparisonAnswer, where=where, items=items) -> tuple[Value, ...]:
            if c.kind is not Kind.SIGN or c.stated not in (("+",), ("-",)):
                return tuple(value(r) for r in c.stated)
            words = [k for k, o in items.items() if o.source in STATING]
            if not c.hedge or not words:
                raise LookupError(
                    f"{where}: a direction stated as {c.stated[0]} needs the words "
                    'that state it in hedge ("higher in block A"), and the Results '
                    "or Methods item with those words among the observations."
                )
            v = Value(name="direction", value=1 if c.stated == ("+",) else -1)
            o = items[words[0]]
            if v not in o.values:
                items[words[0]] = o.model_copy(update={"values": (*o.values, v)})
            return (v,)

        try:
            comparisons = [
                Comparison(
                    kind=c.kind,
                    stated=stated(c),
                    observed=tuple(value(r) for r in c.observed),
                    predicted=value(c.predicted) if c.predicted else None,
                    amount=c.amount,
                    hedge=c.hedge,
                )
                for c in f.comparisons
            ]
        except LookupError as e:
            problems.add("unknown-label", str(e))
            continue
        except ValidationError as e:
            for err in e.errors():
                problems.add(
                    "finding-invalid",
                    f"{where}, a comparison: {err['msg'].removeprefix('Value error, ')}.",
                )
            continue
        fid = f"{h.claim}/{f.facet or WHOLE}" + (
            f"/{_slug(f.scope)}" if f.scope else ""
        )
        ids[fid] += 1
        try:
            findings.append(
                Finding(
                    id=fid,
                    claim_id=h.claim,
                    facet=f.facet,
                    scope=f.scope,
                    status=f.status,
                    basis=f.basis,
                    comparisons=tuple(comparisons),
                    tolerance=f.tolerance,
                    summary=f.summary,
                    observations=tuple(items.values()),
                    not_described_in=f.not_described_in,
                    reason=f.reason,
                    effect=f.effect,
                )
            )
        except ValidationError as e:
            for err in e.errors():
                problems.add(
                    "finding-invalid",
                    f"{where}: {err['msg'].removeprefix('Value error, ')}.",
                )
    for fid, count in ids.items():
        if count > 1:
            problems.add(
                "finding-twice",
                f"{count} findings are for {fid}; give each a different scope "
                "(the part of the facet it covers).",
            )
    return findings, problems


def import_answer(
    workspace: Path,
    reply: str,
    drafted_by: str,
    handoff: str | None = None,
    today: datetime.date | None = None,
) -> tuple[Path | None, list[Problem]]:
    """Check a reply and, if it has no problems, save it with its findings."""
    try:
        answer = parse_answer(reply)
    except AnswerError as e:
        return None, e.problems
    chosen = handoffs.choose(
        pending_handoffs(workspace),
        handoff,
        [c.claim for c in answer.claims],
        lambda h: [c.claim for c in h.claims],
        STEP,
    )
    if isinstance(chosen, Problem):
        return None, [chosen]
    findings, problems = build_findings(answer, chosen)
    if problems:
        return None, problems
    record = Accepted(
        handoff=chosen.name,
        claims=tuple(c.claim for c in chosen.claims),
        drafted_by=drafted_by,
        imported=(today or datetime.date.today()).isoformat(),
        answer=answer,
        findings=tuple(findings),
    )
    return handoffs.save_answer(workspace, STEP, chosen.name, record), []


# --- The record ---------------------------------------------------------------


def _drafter(name: str, stage: str, when: str) -> Drafter:
    """An assistant as drafter; the name it was given ("Claude (website)")
    stands for its model too."""
    return Drafter(
        kind=DrafterKind.MODEL,
        name=name,
        model_id=name,
        stage=stage,
        prompt_version=instructions.load(stage).label,
        date=datetime.date.fromisoformat(when),
    )


def build_record(workspace: Path, settings: Settings) -> AuditRecord:
    """The record: every accepted segment answer's claims, with the findings,
    the tool's own findings on each copied test (:func:`tool_findings`),
    and the lines shown beside each test (:func:`rigoraudit.stats.test_context`).

    A claim with findings is traced. One that rests on citations is
    deferred (decision 0005); one that rests on other claims is supported
    through them; any other is pending.
    """
    accepted = read_accepted(workspace)
    split = segment.read_accepted(workspace)
    if not split:
        raise ValueError("there are no claims yet: the segment step comes first")
    first = accepted[0] if accepted else split[0]
    stage = STEP if accepted else segment.STEP
    drafter = _drafter(first.drafted_by, stage, first.imported)
    by_claim = {c.id: a for a in split for c in a.answer.claims}
    findings = [f for a in accepted for f in a.findings]
    checked = tool_findings(workspace, settings)
    traced = {f.claim_id for f in [*findings, *checked]}
    claims = []
    for c in segment.record_claims(workspace, settings.manuscript):
        if c.id in traced:
            state = Trace.TRACED
        elif c.type is ClaimType.REFERENCED_RESULT:
            state = Trace.DEFERRED
        elif c.depends_on:
            state = Trace.VIA_DEPENDENCIES
        else:
            state = Trace.PENDING
        a = by_claim[c.id]
        own = None
        if a.drafted_by != drafter.name:
            own = _drafter(a.drafted_by, segment.STEP, a.imported)
        claims.append(c.model_copy(update={"trace": state, "drafted_by": own}))
    for a in accepted:
        if a.drafted_by != drafter.name:
            own = _drafter(a.drafted_by, STEP, a.imported)
            findings = [
                f.model_copy(update={"drafted_by": own})
                if f.claim_id in a.claims
                else f
                for f in findings
            ]
    findings += checked
    pages = {(p.section, p.number): p for p in read_paragraphs(workspace / PARAGRAPHS)}
    findings = [_with_pages(f, pages) for f in findings]
    return AuditRecord(
        drafted_by=drafter,
        claims=tuple(claims),
        findings=tuple(findings),
        context=tuple(stats.test_context(workspace)),
    )


def tool_findings(workspace: Path, settings: Settings) -> list[Finding]:
    """The tool's own findings on each copied test: p, N, and effect size
    from the printed statistic, the settings and assumption checks the
    trace cites, and the N and unit of analysis behind a recomputed test
    (:mod:`rigoraudit.stats`)."""
    found = stats.test_findings(workspace, settings.manuscript)
    found += stats.derived_test_findings(workspace, settings)
    if settings.code is not None:
        found += stats.traced_test_findings(workspace, settings)
    return found


def _with_pages(f: Finding, paragraphs: dict[tuple[str, int], Paragraph]) -> Finding:
    """The finding with each quote's page taken from the paragraphs as now
    extracted, so extracting again corrects it."""
    observations = []
    for o in f.observations:
        a = o.anchor
        p = paragraphs.get((a.section, a.paragraph)) if a.kind == "manuscript" else None
        if p is not None:
            o = o.model_copy(
                update={
                    "anchor": a.model_copy(update={"page": p.page_at(a.char_start)})
                }
            )
        observations.append(o)
    return f.model_copy(update={"observations": tuple(observations)})


def draft_record(workspace: Path, settings: Settings) -> AuditRecord | None:
    """The draft record as it stands: built from the accepted answers, or,
    for an audit with its own :data:`SCRIPT`, read from ``record/record.json``
    (``None`` until that script has run)."""
    if (workspace / SCRIPT).is_file():
        path = workspace / RECORD
        if not path.is_file():
            return None
        return AuditRecord.model_validate_json(path.read_text(encoding="utf-8"))
    return build_record(workspace, settings)


def write_record(workspace: Path, settings: Settings) -> Path:
    """Build the record from the accepted answers and save it."""
    if (workspace / SCRIPT).is_file():
        raise ValueError(
            f"this audit builds its record with its own {SCRIPT}; run that instead"
        )
    record = build_record(workspace, settings)
    path = workspace / RECORD
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(record.model_dump_json(indent=1) + "\n", encoding="utf-8")
    return path
