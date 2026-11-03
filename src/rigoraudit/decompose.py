# Copyright (c) 2026, Joshua I. Gold
# SPDX-License-Identifier: BSD-2-Clause
"""Split new-result claims into facets (decisions 0002, 0009, 0011).

After segmenting, every new-result claim is handed to an assistant with its
paragraph (``rigoraudit/instructions/decompose.md``). For each facet the
paragraph states (quantity, population, analysis, condition, display), the
answer gives a verbatim quote, a one-sentence neutral statement, and the
numbers it states, each copied as printed. Each statistical test the claim
reports is also copied, part by part, as a :class:`ReportedTest`, which
:mod:`rigoraudit.stats` checks against itself (decision 0015). The tool reads every value from
its printed text (:func:`read_printed`); the assistant never supplies a
value itself (decision 0009, item 3).

:func:`check_answer` lists every problem in words that can be pasted back.
Accepted answers are kept in ``work/decompose/answers/``, and
:func:`results_observations` turns them into the record's Results
observations, one per facet, anchored to the manuscript.
"""

from __future__ import annotations

import datetime
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Literal

from pydantic import Field

from rigoraudit import handoffs, instructions, segment
from rigoraudit.coverage import items
from rigoraudit.handoffs import AnswerError, Problem, Problems
from rigoraudit.paragraphs import PARAGRAPHS, read_paragraphs
from rigoraudit.schema import (
    ClaimId,
    ClaimType,
    Facet,
    Frozen,
    ManuscriptAnchor,
    NonEmptyStr,
    Observation,
    Obtained,
    Relation,
    Source,
    Value,
)
from rigoraudit.words import plural

STEP = "decompose"
MAX_CHARS = 12_000
"""Paragraph text per handoff."""
NOUNS = {"claims": "claim", "facets": "facet", "values": "value", "tests": "test"}


class StatedValue(Frozen):
    name: NonEmptyStr
    printed: NonEmptyStr
    """The number as printed, with its unit or sign, e.g. ``"87%"``."""
    subject: str | None = None


class FacetAnswer(Frozen):
    facet: Facet
    quote: NonEmptyStr
    states: NonEmptyStr
    values: tuple[StatedValue, ...] = ()


class Statistic(StrEnum):
    """The test statistic, as printed."""

    T = "t"
    F = "F"
    CHI2 = "chi2"
    R = "r"
    Z = "z"
    U = "U"
    W = "W"
    OTHER = "other"


DF_COUNT = {
    Statistic.T: 1,
    Statistic.F: 2,
    Statistic.CHI2: 1,
    Statistic.R: 1,
    Statistic.Z: 0,
}
"""How many degrees of freedom each statistic prints with; others vary."""


class Design(StrEnum):
    """Whether a test compares independent groups, paired values, or one sample."""

    INDEPENDENT = "independent"
    PAIRED = "paired"
    ONE_SAMPLE = "one-sample"


class EffectName(StrEnum):
    D = "d"
    R = "r"
    PARTIAL_ETA_SQUARED = "partial_eta_squared"
    OTHER = "other"


class EffectSize(Frozen):
    name: EffectName
    printed: NonEmptyStr


class ReportedTest(Frozen):
    """One statistical test as the text prints it; every part copied, none
    worked out (decision 0015, item 1)."""

    quote: NonEmptyStr
    """The words that report the test, e.g. ``t(22) = 2.10, p = 0.047``."""
    named: str | None = None
    """The test as the paragraph names it, e.g. ``paired t test``."""
    statistic: Statistic
    value: NonEmptyStr
    """The statistic as printed, e.g. ``2.10``."""
    df: tuple[NonEmptyStr, ...] = Field(default=(), max_length=2)
    p: str | None = None
    """p as printed, with its relation, e.g. ``= 0.047`` or ``< 0.01``."""
    n: str | None = None
    n_quote: str | None = None
    """The words that state N, when they lie outside ``quote``."""
    tails: Literal[1, 2] | None = None
    """Only when the paragraph states it."""
    design: Design | None = None
    """Only when the paragraph states it."""
    effect: EffectSize | None = None


class ClaimFacets(Frozen):
    id: ClaimId
    facets: tuple[FacetAnswer, ...]
    tests: tuple[ReportedTest, ...] = ()


class DecomposeAnswer(Frozen):
    instructions: NonEmptyStr
    claims: tuple[ClaimFacets, ...] = ()


def parse_answer(text: str) -> DecomposeAnswer:
    """Read an answer: bare JSON, or the first fenced block in a reply."""
    return handoffs.parse_reply(text, DecomposeAnswer, NOUNS)


# --- Values from printed text ----------------------------------------------

WORDS = {
    w: i
    for i, w in enumerate(
        ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen", "twenty"]
    )
} | {"thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70,
     "eighty": 80, "ninety": 90, "hundred": 100}  # fmt: skip
RELATIONS = {
    "<": Relation.LT, "≤": Relation.LE, "<=": Relation.LE, ">": Relation.GT,
    "≥": Relation.GE, ">=": Relation.GE, "~": Relation.APPROX, "∼": Relation.APPROX, "≈": Relation.APPROX,
    "=": Relation.EQ,
}  # fmt: skip
RELATION = r"^\s*(?P<rel><=|>=|[<>≤≥~∼≈=])?\s*"
PRINTED = re.compile(
    RELATION
    + r"(?P<num>[-−–]?(?:(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?|\.\d+)|[A-Za-z]+)"
    r"\s*(?P<unit>\S.*?)?\s*$"
)
POWER = re.compile(
    RELATION + r"(?:(?P<mant>\d+(?:\.\d+)?)\s*(?:[×·]\s*10|[eE])|(?P<ten>10))"
    r"(?P<exp>(?<=[eE])[-−+]?\d+|\^\s*[-−]?\d+|−\d+|⁻?[⁰¹²³⁴⁵⁶⁷⁸⁹]+)"
    r"\s*(?P<unit>\S.*?)?\s*$"
)
"""A power of ten: ``10−5`` (a superscript flattened in the PDF's text, so
only with the minus sign −, not a hyphen), ``10⁻⁵``, ``10^-5``,
``2.3×10−5``, or ``2.3e-5``."""
FRACTION = re.compile(
    RELATION + r"(?P<top>\d+)\s*/\s*(?P<bottom>\d+)\s*(?P<unit>\S.*?)?\s*$"
)
"""A fraction as printed, e.g. ``13/16`` or ``13/16 mice``."""
SUPERSCRIPT = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹⁻", "0123456789-")


@dataclass(frozen=True)
class Printed:
    value: int | float
    unit: str | None
    relation: Relation
    decimals: int | None
    """``None`` for a fraction, which shows no decimal places."""


def read_printed(text: str) -> Printed | None:
    """The value of a number as printed (``"3,600"``, ``"87%"``, ``"< 0.01"``,
    ``"twelve"``, ``"13/16"``, ``"p<10−5"``'s ``"<10−5"``), or ``None`` if it
    is not one number. A power of ten too small to store is not one either."""
    if m := POWER.match(text):
        return _power(m)
    if m := FRACTION.match(text):
        return _fraction(m)
    m = PRINTED.match(text)
    if not m:
        return None
    num = m["num"]
    if num.isalpha():
        if num.lower() not in WORDS:
            return None
        value: int | float = WORDS[num.lower()]
        decimals = 0
    else:
        digits = num.replace(",", "").replace("−", "-").replace("–", "-")
        decimals = len(digits.split(".")[1]) if "." in digits else 0
        value = float(digits) if decimals else int(digits)
    unit = m["unit"]
    if unit and re.search(r"\d", unit):
        return None
    return Printed(
        value, unit or None, RELATIONS.get(m["rel"] or "=", Relation.EQ), decimals
    )


def _fraction(m: re.Match[str]) -> Printed | None:
    bottom = int(m["bottom"])
    unit = m["unit"]
    if bottom == 0 or (unit and re.search(r"\d", unit)):
        return None
    return Printed(
        int(m["top"]) / bottom,
        unit or None,
        RELATIONS.get(m["rel"] or "=", Relation.EQ),
        None,
    )


def _power(m: re.Match[str]) -> Printed | None:
    mant = m["mant"] or "1"
    exp = int(m["exp"].translate(SUPERSCRIPT).lstrip("^ ").replace("−", "-"))
    value = float(f"{mant}e{exp}")
    if value == 0.0 or not math.isfinite(value):
        return None
    unit = m["unit"]
    if unit and re.search(r"\d", unit):
        return None
    shown = len(mant.split(".")[1]) if "." in mant else 0
    return Printed(
        value,
        unit or None,
        RELATIONS.get(m["rel"] or "=", Relation.EQ),
        max(0, shown - exp),
    )


# --- Checking ---------------------------------------------------------------


def check_answer(
    answer: DecomposeAnswer,
    claims: Mapping[str, str],
    paragraph_of: Mapping[str, str],
    paragraphs: Mapping[str, str],
) -> Problems:
    """Everything wrong with ``answer``, as sentences; empty if nothing is.

    ``claims`` maps each claim handed off to its quote, ``paragraph_of`` to
    its paragraph's label, and ``paragraphs`` each label to its text.
    """
    problems = handoffs.version_problem(STEP, answer.instructions)
    answered = [c.id for c in answer.claims]
    for claim_id in sorted({i for i in answered if answered.count(i) > 1}):
        problems.add("claim-repeated", f"Claim {claim_id} is answered more than once.")
    for claim_id in sorted(set(answered) - set(claims)):
        problems.add(
            "claim-not-given",
            f"Claim {claim_id} was not given; answer only the claims given.",
        )
    for claim_id in [i for i in claims if i not in answered]:
        problems.add(
            "claim-missing", f"Claim {claim_id} has no answer; give its facets."
        )

    for c in answer.claims:
        if c.id not in claims:
            continue
        label = paragraph_of[c.id]
        text = paragraphs[label]
        if not c.facets:
            problems.add("no-facets", f"Claim {c.id} has no facets; give at least one.")
        names = [f.facet for f in c.facets]
        for facet in sorted({f for f in names if names.count(f) > 1}):
            problems.add(
                "facet-repeated",
                f"Claim {c.id} gives the {facet.value} facet more than once.",
            )
        covered = []
        for f in c.facets:
            n = text.count(f.quote)
            where = f"the {f.facet.value} quote for claim {c.id}"
            if n == 0:
                problems.add(
                    "quote-not-found",
                    f"{where[0].upper()}{where[1:]} is not in paragraph {label} "
                    f"word for word: {f.quote!r}",
                )
                continue
            if n > 1:
                problems.add(
                    "quote-not-unique",
                    f"{where[0].upper()}{where[1:]} appears {n} times in paragraph "
                    f"{label}; make it longer so it appears once: {f.quote!r}",
                )
                continue
            start = text.index(f.quote)
            covered.append((start, start + len(f.quote)))
            for v in f.values:
                if v.printed not in f.quote:
                    problems.add(
                        "value-not-in-quote",
                        f"The value {v.printed!r} ({v.name}) is not in {where} "
                        "word for word.",
                    )
                elif read_printed(v.printed) is None and POWER.match(v.printed):
                    problems.add(
                        "value-too-small",
                        f"The value {v.printed!r} ({v.name}) for claim {c.id} is too "
                        "small for the tool to store; leave it out of values (the "
                        "quote still covers it).",
                    )
                elif read_printed(v.printed) is None:
                    problems.add(
                        "value-not-a-number",
                        f"The value {v.printed!r} ({v.name}) for claim {c.id} is not "
                        "a single number as printed; copy just the number with its "
                        "unit or sign, e.g. '120 ms', '87%', '< 0.01'. For a range "
                        "such as '5–10%', give each end as its own value ('5' and "
                        "'10%').",
                    )
        for n, t in enumerate(c.tests, 1):
            problems.extend(_test_problems(t, f"Test {n} of claim {c.id}", label, text))
        claim_start = text.find(claims[c.id])
        if claim_start < 0:
            continue
        loose = [
            i.text
            for i in items(claims[c.id])
            if i.kind == "number"
            and not any(
                a <= claim_start + i.start and claim_start + i.end <= b
                for a, b in covered
            )
        ]
        if loose:
            problems.add(
                "number-outside-facets",
                f"Claim {c.id} states numbers that no facet's quote contains "
                f"({', '.join(loose)}); put each in the quote of the facet it belongs to.",
            )
    return problems


def _test_problems(t: ReportedTest, where: str, label: str, text: str) -> Problems:
    """Everything wrong with one copied test, ``where`` naming it."""
    problems = Problems()
    for name, quote in (("quote", t.quote), ("n_quote", t.n_quote)):
        if quote is None:
            continue
        n = text.count(quote)
        if n != 1:
            problems.add(
                "quote-not-found" if n == 0 else "quote-not-unique",
                f"{where}: its {name} must appear once in paragraph {label} word "
                f"for word; it appears {n} times: {quote!r}",
            )
            return problems
    if t.named is not None and t.named not in text:
        problems.add(
            "quote-not-found",
            f"{where}: the test's name is not in paragraph {label} word for word: "
            f"{t.named!r}",
        )
    if t.n_quote is not None and t.n is None:
        problems.add(
            "n-missing", f"{where} gives n_quote but not n; give both or neither."
        )
    parts = [("value", t.value, t.quote), *(("df", d, t.quote) for d in t.df)]
    parts += [("p", t.p, t.quote), ("n", t.n, t.n_quote or t.quote)]
    parts += [("effect", t.effect.printed, t.quote)] if t.effect else []
    for name, printed, quote in parts:
        if printed is None:
            continue
        if printed not in quote:
            problems.add(
                "value-not-in-quote",
                f"{where}: its {name} {printed!r} is not in "
                f"{'n_quote' if quote is t.n_quote else 'its quote'} word for word.",
            )
        elif read_printed(printed) is None:
            problems.add(
                "value-not-a-number",
                f"{where}: its {name} {printed!r} is not a single number as "
                "printed; copy just the number, with its relation for p ('< 0.01').",
            )
    expected = DF_COUNT.get(t.statistic)
    if expected is not None and t.df and len(t.df) != expected:
        problems.add(
            "df-count",
            f"{where}: a {t.statistic} statistic prints with {plural(expected, 'degree')} "
            f"of freedom, not {len(t.df)}.",
        )
    return problems


# --- Handoffs and import ----------------------------------------------------


class Handoff(Frozen):
    name: NonEmptyStr
    instructions: NonEmptyStr
    claims: dict[str, str]
    """Claim ID to quote, in reading order."""
    paragraph_of: dict[str, str]
    paragraphs: dict[str, str]
    places: dict[str, str]


class Accepted(Frozen):
    handoff: NonEmptyStr
    claims: tuple[str, ...]
    drafted_by: NonEmptyStr
    imported: NonEmptyStr
    answer: DecomposeAnswer


def read_accepted(workspace: Path) -> list[Accepted]:
    return handoffs.read_answers(workspace, STEP, Accepted)


def pending_handoffs(workspace: Path) -> list[Handoff]:
    answered = {a.handoff for a in read_accepted(workspace)}
    return handoffs.read_pending(workspace, STEP, Handoff, answered)


def to_decompose(workspace: Path) -> list[segment.SegmentClaim]:
    """New-result claims from accepted segment answers, in reading order."""
    return segment.claims_of(workspace, ClaimType.NEW_RESULT)


def plan_handoffs(workspace: Path, max_chars: int = MAX_CHARS) -> list[Handoff]:
    """Handoffs for the new-result claims no accepted answer covers yet."""
    done = {i for a in read_accepted(workspace) for i in a.claims}
    paragraphs = {p.label: p for p in read_paragraphs(workspace / PARAGRAPHS)}
    todo = [c for c in to_decompose(workspace) if c.id not in done]
    groups: list[list[segment.SegmentClaim]] = []
    for c in todo:
        labels = {x.paragraph for x in groups[-1]} if groups else set()
        size = sum(len(paragraphs[lab].text) for lab in labels | {c.paragraph})
        if groups and size <= max_chars:
            groups[-1].append(c)
        else:
            groups.append([c])
    version = instructions.load(STEP).label
    out = []
    for g in groups:
        labels = list(dict.fromkeys(c.paragraph for c in g))
        out.append(
            Handoff(
                name=f"decompose-{g[0].id}",
                instructions=version,
                claims={c.id: c.quote for c in g},
                paragraph_of={c.id: c.paragraph for c in g},
                paragraphs={lab: paragraphs[lab].text for lab in labels},
                places={lab: paragraphs[lab].place for lab in labels},
            )
        )
    return out


def render_handoff(h: Handoff) -> str:
    body = []
    for label, text in h.paragraphs.items():
        body += ["", f"### Paragraph `{label}` ({h.places[label]})", "", text, ""]
        body += ["Claims to split:", ""]
        body += [
            f"- `{i}`: {q}" for i, q in h.claims.items() if h.paragraph_of[i] == label
        ]
    what = f"the {plural(len(h.claims), 'claim')} below"
    return handoffs.render(STEP, h.name, h.instructions, what, body)


def write_handoffs(workspace: Path, max_chars: int = MAX_CHARS) -> list[Path]:
    """Write the handoffs still needed; return the files to paste."""
    answered = {a.handoff for a in read_accepted(workspace)}
    return handoffs.write_handoffs(
        workspace,
        STEP,
        ((h.name, h, render_handoff(h)) for h in plan_handoffs(workspace, max_chars)),
        answered,
    )


def _match(answer: DecomposeAnswer, pending: Sequence[Handoff]) -> Handoff | Problem:
    named = {c.id for c in answer.claims}
    fits = [h for h in pending if named and named <= set(h.claims)]
    if len(fits) == 1:
        return fits[0]
    if not pending:
        return Problem(
            "no-handoff-waiting",
            "No handoff is waiting for an answer; run rigoraudit handoff decompose.",
        )
    if not fits:
        return Problem(
            "which-handoff",
            "The answer's claims are not all in any one handoff waiting for an "
            "answer; say which handoff it answers with --handoff.",
        )
    return Problem(
        "which-handoff",
        "Say which handoff the answer is for with --handoff "
        f"({', '.join(h.name for h in fits)}).",
    )


def import_answer(
    workspace: Path,
    reply: str,
    drafted_by: str,
    handoff: str | None = None,
    today: datetime.date | None = None,
) -> tuple[Path | None, list[Problem]]:
    """Check a reply and, if it has no problems, save it as accepted."""
    try:
        answer = parse_answer(reply)
    except AnswerError as e:
        return None, e.problems
    pending = pending_handoffs(workspace)
    if handoff is not None:
        chosen = next((h for h in pending if h.name == handoff), None)
        if chosen is None:
            return None, [
                Problem(
                    "no-handoff-waiting",
                    f"No handoff named {handoff} is waiting for an answer.",
                )
            ]
    else:
        found = _match(answer, pending)
        if isinstance(found, Problem):
            return None, [found]
        chosen = found
    problems = check_answer(
        answer, chosen.claims, chosen.paragraph_of, chosen.paragraphs
    )
    if problems:
        return None, problems
    record = Accepted(
        handoff=chosen.name,
        claims=tuple(chosen.claims),
        drafted_by=drafted_by,
        imported=(today or datetime.date.today()).isoformat(),
        answer=answer,
    )
    return handoffs.save_answer(workspace, STEP, chosen.name, record), []


# --- Record observations ----------------------------------------------------


def results_observations(
    workspace: Path, manuscript: str
) -> dict[str, dict[Facet, Observation]]:
    """Each decomposed claim's Results observations, by claim ID and facet.

    ``manuscript`` is the manuscript file, relative to ``materials/``. Each
    observation quotes the facet's words, anchored in the claim's paragraph,
    and carries the values read from their printed text.
    """
    paragraphs = {p.label: p for p in read_paragraphs(workspace / PARAGRAPHS)}
    where = {c.id: c.paragraph for c in to_decompose(workspace)}
    out: dict[str, dict[Facet, Observation]] = {}
    for a in read_accepted(workspace):
        for c in a.answer.claims:
            p = paragraphs[where[c.id]]
            out[c.id] = {}
            for f in c.facets:
                start, quote = p.locate(f.quote)
                values = []
                for v in f.values:
                    printed = read_printed(v.printed)
                    if printed is None:
                        raise ValueError(f"{a.handoff}: {v.printed!r} is not a number")
                    values.append(
                        Value(
                            name=v.name,
                            value=printed.value,
                            unit=printed.unit,
                            subject=v.subject,
                            relation=printed.relation,
                            decimals=printed.decimals,
                        )
                    )
                out[c.id][f.facet] = Observation(
                    source=Source.RESULTS,
                    statement=f.states,
                    obtained=Obtained.QUOTED,
                    anchor=ManuscriptAnchor(
                        file=manuscript,
                        section=p.section,
                        paragraph=p.number,
                        char_start=start,
                        char_end=start + len(quote),
                        page=p.page_at(start),
                        quote=quote,
                    ),
                    values=tuple(values),
                )
    return out
