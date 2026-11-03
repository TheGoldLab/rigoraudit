# Copyright (c) 2026, Joshua I. Gold
# SPDX-License-Identifier: BSD-2-Clause
"""Cross-claim checks: values the paper prints in more than one claim, set
side by side (decision 0016).

Compare sets each claim beside its own sources, never beside another claim.
This step takes every value the manuscript prints (the values of the
Results and Methods observations quoted from it), and an assistant says
which values from different claims are about the same thing: the same
quantity, for the same population and condition.

Three rules propose candidate groups, which the assistant confirms, splits,
or sets aside; it also adds groups the rules miss:

- **restates** (R1): one claim restates the other, and the values have the
  same name and unit, and the same subject where both give one;
- **same place** (R2): their findings cite overlapping lines of one code
  file, the same data file, field, and selection, or the same Methods
  paragraph, and the values have the same name, subject, and unit;
- **same label** (R3): the values have the same name, subject, and unit,
  and both name a subject.

Names, subjects, and units are matched in lower case, with spaces tidied.
The rules alone join too much (one function serves several conditions; one
word names a quantity in two tasks) and too little (one count, named
"subjects" in one claim and "participants" in another), so no group is
compared until the assistant has confirmed it (rule R4).

The tool then compares every pair of values in a group from different
claims and different printed text, by compare's rules (decision 0006):
numbers at the coarser of the two printed precisions, a bound and a number
as the bound states (p < 0.05 and p = 0.03 agree), two bounds by whether
any value meets both, a value printed as approximate within :data:`HEDGE`
of it (∼50 and 52 agree), and words exactly. Each group makes one
:class:`~rigoraudit.schema.CrossFinding`, which differs if any pair
differs.

The answer holds the values it was given, so an answer for an earlier
record is not used: the step is handed off again. ``rigoraudit check``
writes the findings to :data:`FINDINGS`; the report works them out from
the record it shows.
"""

from __future__ import annotations

import datetime
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from pydantic import Field

from rigoraudit import compare, handoffs, instructions, review
from rigoraudit.handoffs import AnswerError, Problem, Problems
from rigoraudit.schema import (
    AuditRecord,
    ClaimId,
    CodeAnchor,
    Comparison,
    CrossFinding,
    CrossValue,
    DataAnchor,
    Facet,
    Frozen,
    Kind,
    ManuscriptAnchor,
    NonEmptyStr,
    Relation,
    Rule,
    Source,
    Status,
    Value,
    is_stated,
    same_value,
)
from rigoraudit.settings import Settings
from rigoraudit.words import plural

STEP = "crosscheck"
NAME = "crosscheck"
NOUNS = {"groups": "group", "set_aside": "set-aside candidate"}
FINDINGS = PurePosixPath("work") / "crosscheck" / "findings.json"
"""Where the cross-claim findings are written."""
MAX_QUOTE = 200
"""Characters of a value's quote given in the handoff."""
HEDGE = 0.10
"""How far a value printed as approximate (``∼50``) may be from another
value and still agree: ±10% of it, as compare's default (decision 0006)."""

_LOWER = {Relation.GT, Relation.GE}
_UPPER = {Relation.LT, Relation.LE}


class CrossCheck(Frozen):
    """The cross-claim findings of one record, as written to :data:`FINDINGS`."""

    findings: tuple[CrossFinding, ...] = ()


# --- The values and the rules ------------------------------------------------


@dataclass(frozen=True)
class _Item:
    claim: int
    """The claim's position in the record."""
    value: CrossValue


def _norm(text: str | None) -> str | None:
    return " ".join(text.lower().split()) if text else None


def _label(v: Value) -> tuple[str | None, ...]:
    return _norm(v.name), _norm(v.subject), _norm(v.unit)


def _places(v: Value) -> int:
    """Decimal places printed."""
    if v.decimals is not None:
        return v.decimals
    text = repr(float(v.value))
    return 0 if "e" in text else len(text.split(".")[1].rstrip("0"))


def _plain(v: Value) -> Value:
    return v.model_copy(update={"relation": Relation.EQ, "decimals": None})


def agree(a: Value, b: Value) -> bool:
    """Whether two printed values for the same thing agree."""
    if any(isinstance(v.value, bool | str) for v in (a, b)):
        return same_value(a.value, b.value)
    bounds = [v for v in (a, b) if v.relation in _LOWER | _UPPER]
    if len(bounds) == 2:
        lower = [v for v in bounds if v.relation in _LOWER]
        if len(lower) != 1:  # both bound the same side: some value meets both
            return True
        (lo,) = lower
        (hi,) = [v for v in bounds if v is not lo]
        if lo.value != hi.value:
            return lo.value < hi.value
        return lo.relation is Relation.GE and hi.relation is Relation.LE
    if bounds:
        (bound,) = bounds
        point = b if bound is a else a
        c = Comparison(kind=Kind.INEQUALITY, stated=(bound,), observed=(_plain(point),))
        return c.agrees()
    hedged = [v for v in (a, b) if v.relation is Relation.APPROX]
    if hedged:  # agrees if within HEDGE of either hedged value
        return any(
            Comparison(
                kind=Kind.RELATIVE,
                amount=HEDGE,
                stated=(h,),
                observed=(_plain(b if h is a else a),),
            ).agrees()
            for h in hedged
        )
    coarse, fine = sorted((a, b), key=_places)
    stated = coarse.model_copy(
        update={"relation": Relation.EQ, "decimals": _places(coarse)}
    )
    c = Comparison(kind=Kind.PRECISION, stated=(stated,), observed=(_plain(fine),))
    return c.agrees()


def _items(record: AuditRecord) -> tuple[list[_Item], dict[str, list[int]]]:
    """Every printed value, once per claim and place, and the values of each
    finding."""
    order = {c.id: i for i, c in enumerate(record.claims)}
    items: list[_Item] = []
    seen: dict[tuple, int] = {}
    of_finding: dict[str, list[int]] = defaultdict(list)
    for f in record.findings:
        for o in f.observations:
            if not is_stated(o) or not isinstance(o.anchor, ManuscriptAnchor):
                continue
            for v in o.values:
                key = (f.claim_id, *_text(o.anchor, v))
                if key not in seen:
                    seen[key] = len(items)
                    cv = CrossValue(
                        claim_id=f.claim_id, facet=f.facet, value=v, anchor=o.anchor
                    )
                    items.append(_Item(order[f.claim_id], cv))
                of_finding[f.id].append(seen[key])
    items_order = sorted(
        range(len(items)),
        key=lambda i: (items[i].claim, items[i].value.anchor.char_start),
    )
    new = {old: k for k, old in enumerate(items_order)}
    return [items[i] for i in items_order], {
        f: [new[i] for i in ids] for f, ids in of_finding.items()
    }


def _text(a: ManuscriptAnchor, v: Value) -> tuple:
    """The printed text a value comes from."""
    return a.section, a.paragraph, a.char_start, a.char_end, v.name, v.value


def _places_cited(record: AuditRecord) -> list[tuple[str, tuple, str]]:
    """(kind and file, extent, finding ID) for every place a finding cites."""
    out = []
    for f in record.findings:
        for o in f.observations:
            a = o.anchor
            if isinstance(a, CodeAnchor):
                out.append((f"code:{a.file}", (a.line_start, a.line_end), f.id))
            elif isinstance(a, DataAnchor):
                out.append((f"data:{a.file}", (a.field, a.selection), f.id))
            elif o.source is Source.METHODS:
                out.append((f"methods:{a.section}", (a.paragraph,), f.id))
    return out


def _same_place(record: AuditRecord) -> set[tuple[str, str]]:
    """Pairs of findings, of different claims, that cite the same place."""
    claim = {f.id: f.claim_id for f in record.findings}
    by_file: dict[str, list[tuple[tuple, str]]] = defaultdict(list)
    for where, extent, fid in _places_cited(record):
        by_file[where].append((extent, fid))
    pairs = set()
    for where, cited in by_file.items():
        for i, (x, f) in enumerate(cited):
            for y, g in cited[i + 1 :]:
                if claim[f] == claim[g]:
                    continue
                if where.startswith("code:"):
                    same = x[0] <= y[1] and y[0] <= x[1]
                else:
                    same = x == y
                if same:
                    pairs.add((f, g))
    return pairs


def _comparable(a: CrossValue, b: CrossValue) -> bool:
    """Whether two values can be compared: different claims, different text."""
    return a.claim_id != b.claim_id and _text(a.anchor, a.value) != _text(
        b.anchor, b.value
    )


def _edges(record: AuditRecord, items: list[_Item], of_finding) -> dict:
    """Pairs of values joined by a rule, each with the rules that join it."""
    edges: dict[tuple[int, int], set[Rule]] = defaultdict(set)

    def join(i: int, j: int, rule: Rule) -> None:
        if _comparable(items[i].value, items[j].value):
            edges[min(i, j), max(i, j)].add(rule)

    by_claim: dict[str, list[int]] = defaultdict(list)
    for i, it in enumerate(items):
        by_claim[it.value.claim_id].append(i)
    for c in record.claims:
        if c.restates is None:
            continue
        for i in by_claim[c.id]:
            for j in by_claim[c.restates]:
                (n1, s1, u1), (n2, s2, u2) = (
                    _label(items[k].value.value) for k in (i, j)
                )
                if n1 == n2 and u1 == u2 and (s1 == s2 or None in (s1, s2)):
                    join(i, j, Rule.RESTATES)
    for f, g in _same_place(record):
        for i in of_finding.get(f, ()):
            for j in of_finding.get(g, ()):
                if _label(items[i].value.value) == _label(items[j].value.value):
                    join(i, j, Rule.SAME_PLACE)
    by_label: dict[tuple, list[int]] = defaultdict(list)
    for i, it in enumerate(items):
        label = _label(it.value.value)
        if label[1] is not None:
            by_label[label].append(i)
    for same in by_label.values():
        for k, i in enumerate(same):
            for j in same[k + 1 :]:
                join(i, j, Rule.SAME_LABEL)
    return edges


def _groups(n: int, edges) -> list[list[int]]:
    """The values joined, directly or through others, in order."""
    parent = list(range(n))

    def root(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i, j in edges:
        parent[root(i)] = root(j)
    joined: dict[int, list[int]] = defaultdict(list)
    for i in sorted({k for e in edges for k in e}):
        joined[root(i)].append(i)
    return sorted(joined.values())


def _rules(ids: list[int], edges) -> tuple[Rule, ...]:
    """The rules that join any two of the values, in the order of :class:`Rule`."""
    within = set(ids)
    found = {r for e, rs in edges.items() if set(e) <= within for r in rs}
    return tuple(r for r in Rule if r in found)


# --- The handoff -------------------------------------------------------------


class Row(Frozen):
    """One printed value, as handed off."""

    label: NonEmptyStr
    """``V1``, ``V2``, …, in the order of the claims."""
    claim_id: ClaimId
    facet: Facet | None = None
    name: NonEmptyStr
    subject: str | None = None
    unit: str | None = None
    value: NonEmptyStr
    """As shown: ``< 0.05``, ``60%``."""
    quote: NonEmptyStr
    """The words it is printed in (the first :data:`MAX_QUOTE` characters)."""
    same_text: str | None = None
    """The row that is this value in the same printed words, quoted by
    another claim; the two are never compared."""


class ClaimRow(Frozen):
    id: ClaimId
    section: NonEmptyStr
    quote: NonEmptyStr


class Candidate(Frozen):
    label: NonEmptyStr
    """``C1``, ``C2``, …"""
    values: tuple[NonEmptyStr, ...]
    rules: tuple[Rule, ...]


class Handoff(Frozen):
    name: NonEmptyStr
    instructions: NonEmptyStr
    claims: tuple[ClaimRow, ...]
    rows: tuple[Row, ...]
    candidates: tuple[Candidate, ...]


class Group(Frozen):
    values: tuple[NonEmptyStr, ...] = Field(min_length=2)
    """Row labels."""
    reason: NonEmptyStr
    """Why they are one thing, naming the population and the condition."""


class SetAside(Frozen):
    candidate: NonEmptyStr
    reason: NonEmptyStr


class CrossAnswer(Frozen):
    instructions: NonEmptyStr
    """The instructions the answer followed, e.g. ``"crosscheck v1"``."""
    groups: tuple[Group, ...] = ()
    set_aside: tuple[SetAside, ...] = ()


class Accepted(Frozen):
    handoff: NonEmptyStr
    drafted_by: NonEmptyStr
    imported: NonEmptyStr
    """Date the answer was accepted, ``YYYY-MM-DD``."""
    rows: tuple[Row, ...]
    """The values it was given; it is used only for a record with these."""
    answer: CrossAnswer


def _rows(items: list[_Item]) -> tuple[Row, ...]:
    first: dict[tuple, str] = {}
    rows = []
    for k, it in enumerate(items):
        cv, label = it.value, f"V{k + 1}"
        key = _text(cv.anchor, cv.value)
        quote = cv.anchor.quote
        if len(quote) > MAX_QUOTE:
            quote = quote[:MAX_QUOTE].rstrip() + " …"
        rows.append(
            Row(
                label=label,
                claim_id=cv.claim_id,
                facet=cv.facet,
                name=cv.value.name,
                subject=cv.value.subject,
                unit=cv.value.unit,
                value=cv.value.printed(),
                quote=quote,
                same_text=first.get(key),
            )
        )
        first.setdefault(key, label)
    return tuple(rows)


def read_accepted(workspace: Path) -> list[Accepted]:
    return handoffs.read_answers(workspace, STEP, Accepted)


def _accepted_for(workspace: Path, rows: tuple[Row, ...]) -> Accepted | None:
    """The accepted answer given these values, if there is one."""
    return next((a for a in read_accepted(workspace) if a.rows == rows), None)


def _needed(items: list[_Item]) -> bool:
    """Whether there is anything to group: values from two claims or more."""
    return len({it.value.claim_id for it in items}) > 1


def plan_handoffs(workspace: Path, record: AuditRecord) -> list[Handoff]:
    """The handoff still needed: none if no two claims print values, or once
    an answer for these values is accepted."""
    items, of_finding = _items(record)
    rows = _rows(items)
    if not _needed(items) or _accepted_for(workspace, rows):
        return []
    edges = _edges(record, items, of_finding)
    candidates = tuple(
        Candidate(
            label=f"C{n}",
            values=tuple(rows[i].label for i in ids),
            rules=_rules(ids, edges),
        )
        for n, ids in enumerate(_groups(len(items), edges), start=1)
    )
    in_rows = {r.claim_id for r in rows}
    claims = tuple(
        ClaimRow(id=c.id, section=c.anchor.section, quote=c.anchor.quote)
        for c in record.claims
        if c.id in in_rows
    )
    return [
        Handoff(
            name=NAME,
            instructions=instructions.load(STEP).label,
            claims=claims,
            rows=rows,
            candidates=candidates,
        )
    ]


RULE_WORDS = {
    Rule.RESTATES: "restates",
    Rule.SAME_PLACE: "same place",
    Rule.SAME_LABEL: "same label",
}


def render_handoff(h: Handoff) -> str:
    """The text to paste: the instructions, the candidate groups, then every
    value, claim by claim."""
    body = ["", "## Candidate groups, from the rules", ""]
    for c in h.candidates:
        rules = ", ".join(RULE_WORDS[r] for r in c.rules)
        body.append(f"- {c.label} ({rules}): {', '.join(c.values)}")
    if not h.candidates:
        body.append("(none)")
    body += ["", "## The values, claim by claim"]
    by_claim: dict[str, list[Row]] = defaultdict(list)
    for r in h.rows:
        by_claim[r.claim_id].append(r)
    for c in h.claims:
        body += ["", f"### {c.id} ({c.section})", "", f"> {c.quote}", ""]
        for r in by_claim[c.id]:
            label = r.name + "".join(
                f"; {what} {text}"
                for what, text in (("subject", r.subject), ("unit", r.unit))
                if text
            )
            same = f" (the same words as {r.same_text})" if r.same_text else ""
            facet = f" · {r.facet}" if r.facet else ""
            body.append(f"- {r.label}{facet} · {label}: {r.value}{same} — “{r.quote}”")
    what = (
        f"the {plural(len(h.rows), 'value')} from {plural(len(h.claims), 'claim')} "
        f"and the {plural(len(h.candidates), 'candidate group')} below"
    )
    return handoffs.render(STEP, h.name, h.instructions, what, body)


def write_handoffs(workspace: Path, record: AuditRecord) -> list[Path]:
    """Write the handoff if one is needed; return the file to paste."""
    planned = plan_handoffs(workspace, record)
    return handoffs.write_handoffs(
        workspace,
        STEP,
        ((h.name, h, render_handoff(h)) for h in planned),
        answered=() if planned else {a.handoff for a in read_accepted(workspace)},
    )


def pending_handoffs(workspace: Path) -> list[Handoff]:
    """Handoffs written whose values have no accepted answer."""
    done = [a.rows for a in read_accepted(workspace)]
    return [
        h
        for h in handoffs.read_pending(workspace, STEP, Handoff, ())
        if h.rows not in done
    ]


# --- The answer --------------------------------------------------------------


def parse_answer(text: str) -> CrossAnswer:
    """Read an answer: bare JSON, or the first fenced block in a reply."""
    return handoffs.parse_reply(text, CrossAnswer, NOUNS)


def check_answer(answer: CrossAnswer, h: Handoff) -> Problems:
    """Everything wrong with an answer: unknown labels, a group with nothing
    to compare, a value in two groups, a candidate neither used nor set
    aside."""
    problems = handoffs.version_problem(STEP, answer.instructions)
    rows = {r.label: r for r in h.rows}
    candidates = {c.label: c for c in h.candidates}
    used: dict[str, int] = {}
    for n, g in enumerate(answer.groups, start=1):
        unknown = [x for x in g.values if x not in rows]
        for x in unknown:
            problems.add("unknown-value", f"Group {n} names {x}, which is not a value.")
        known = [rows[x] for x in g.values if x in rows]
        texts = {(r.claim_id, r.same_text or r.label) for r in known}
        if not unknown and (
            len({c for c, _ in texts}) < 2 or len({t for _, t in texts}) < 2
        ):
            problems.add(
                "nothing-to-compare",
                f"Group {n} needs values from two claims or more, printed in "
                "different words; leave it out if it has none.",
            )
        for x in dict.fromkeys(g.values):
            if x in used:
                problems.add(
                    "value-twice",
                    f"{x} is in group {used[x]} and group {n}; a value belongs "
                    "to one group at most.",
                )
            used.setdefault(x, n)
    set_aside = [s.candidate for s in answer.set_aside]
    for c in dict.fromkeys(set_aside):
        if c not in candidates:
            problems.add("unknown-candidate", f"{c} is not a candidate group.")
        elif set_aside.count(c) > 1:
            problems.add("candidate-twice", f"{c} is set aside more than once.")
    for c in candidates.values():
        if c.label not in set_aside and not set(c.values) & set(used):
            problems.add(
                "candidate-unanswered",
                f"{c.label} is in no group and not set aside; confirm its "
                "values in a group, or set it aside with the reason.",
            )
    return problems


def import_answer(
    workspace: Path,
    reply: str,
    drafted_by: str,
    handoff: str | None = None,
    today: datetime.date | None = None,
) -> tuple[Path | None, list[Problem]]:
    """Check a reply and, if it has no problems, save it.

    Returns the saved answer, or ``None`` and the problems to give back to the
    assistant.
    """
    try:
        answer = parse_answer(reply)
    except AnswerError as e:
        return None, e.problems
    pending = [h for h in pending_handoffs(workspace) if handoff in (None, h.name)]
    if not pending:
        return None, [
            Problem(
                "no-handoff-waiting",
                "No handoff is waiting for an answer; run rigoraudit handoff "
                "crosscheck.",
            )
        ]
    chosen = pending[0]
    if problems := check_answer(answer, chosen):
        return None, problems
    accepted = Accepted(
        handoff=chosen.name,
        drafted_by=drafted_by,
        imported=(today or datetime.date.today()).isoformat(),
        rows=chosen.rows,
        answer=answer,
    )
    return handoffs.save_answer(workspace, STEP, chosen.name, accepted), []


# --- The findings ------------------------------------------------------------


def quotes(x: CrossFinding) -> list[tuple[str, ManuscriptAnchor]]:
    """Each place a finding's values are quoted from, once: (claim ID,
    anchor), in the finding's order. One sentence may give several values."""
    return list(dict.fromkeys((v.claim_id, v.anchor) for v in x.values))


def _and(words: list[str]) -> str:
    return words[0] if len(words) == 1 else f"{', '.join(words[:-1])} and {words[-1]}"


def _summary(values: list[CrossValue]) -> str:
    claims = list(dict.fromkeys(v.claim_id for v in values))
    first = values[0].value
    subjects = {_norm(v.value.subject) for v in values}
    what = first.name
    if len(subjects) == 1 and first.subject:
        what += f" ({first.subject})"
    if len(values) == len(claims):
        return f"{_and(claims)} give {what} as {_and([v.value.printed() for v in values])}."
    each = [
        f"{c} gives "
        + _and(
            list(dict.fromkeys(v.value.printed() for v in values if v.claim_id == c))
        )
        for c in claims
    ]
    return f"{what[0].upper()}{what[1:]}: {'; '.join(each)}."


def find(record: AuditRecord, answer: CrossAnswer) -> tuple[CrossFinding, ...]:
    """The findings of the groups an answer confirms, in the order of the
    claims."""
    items, of_finding = _items(record)
    edges = _edges(record, items, of_finding)
    index = {f"V{k + 1}": k for k in range(len(items))}
    found = []
    for g in answer.groups:
        ids = sorted(index[x] for x in dict.fromkeys(g.values))
        values = [items[k].value for k in ids]
        pairs = [
            (a, b)
            for n, a in enumerate(values)
            for b in values[n + 1 :]
            if _comparable(a, b)
        ]
        differs = any(not agree(a.value, b.value) for a, b in pairs)
        found.append(
            (ids[0], values, differs, _rules(ids, edges) or (Rule.SAME_MEANING,), g)
        )
    out, used = [], set()
    for _, values, differs, rules, g in sorted(found, key=lambda x: x[0]):
        claims = tuple(dict.fromkeys(v.claim_id for v in values))
        slug = (
            re.sub(r"[^A-Za-z0-9.]+", "-", values[0].value.name).strip("-") or "value"
        )
        fid = f"x/{'/'.join(claims)}/{slug}"
        n = 2
        while fid in used:
            fid, n = f"x/{'/'.join(claims)}/{slug}-{n}", n + 1
        used.add(fid)
        out.append(
            CrossFinding(
                id=fid,
                claim_ids=claims,
                rules=rules,
                status=Status.DIFFERS if differs else Status.CONSISTENT,
                values=tuple(values),
                summary=_summary(values),
                reason=g.reason,
            )
        )
    return tuple(out)


def current(workspace: Path, record: AuditRecord) -> tuple[CrossFinding, ...] | None:
    """The record's cross-claim findings, or ``None`` while the step waits
    for an answer given its values."""
    items, _ = _items(record)
    if not _needed(items):
        return ()
    accepted = _accepted_for(workspace, _rows(items))
    return None if accepted is None else find(record, accepted.answer)


def record_for(workspace: Path, settings: Settings) -> AuditRecord | None:
    """The reviewed record the step works on: built from the accepted answers,
    or read from ``record/record.json`` for an audit with its own
    ``record/record.py`` (``None`` until that script has run)."""
    draft = compare.draft_record(workspace, settings)
    return None if draft is None else review.reviewed(draft, workspace)


def write(workspace: Path, record: AuditRecord) -> tuple[CrossFinding, ...] | None:
    """Write the record's cross-claim findings to :data:`FINDINGS`, or remove
    that file while the step waits for an answer."""
    found = current(workspace, record)
    path = workspace / FINDINGS
    if found is None:
        path.unlink(missing_ok=True)
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        CrossCheck(findings=found).model_dump_json(indent=1) + "\n", encoding="utf-8"
    )
    return found


def describe(found: tuple[CrossFinding, ...] | None) -> str:
    """The findings in a line, for people."""
    if found is None:
        return (
            "Cross-claim checks: not done; the crosscheck step waits for an "
            "answer for this record (rigoraudit handoff crosscheck)."
        )
    differ = sum(1 for x in found if x.status is Status.DIFFERS)
    return (
        f"Cross-claim checks: {plural(len(found), 'value')} printed in more than "
        f"one claim, compared; {differ} {'differs' if differ == 1 else 'differ'} "
        f"(listed in the report and in {FINDINGS.as_posix()})."
    )
