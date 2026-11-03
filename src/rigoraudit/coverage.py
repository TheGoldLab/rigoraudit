# Copyright (c) 2026, Joshua I. Gold
# SPDX-License-Identifier: BSD-2-Clause
"""Coverage: does every checkable statement in the audited text have a claim?

The other checks in :mod:`rigoraudit.verify` test what the record says. This
one looks for what it leaves out. In each audited paragraph it finds the
*checkable items*: numbers (with ranges and percentages), comparison words
("higher", "increased", "differed", "no modulation"), and names of
statistical tests and fits ("Wilcoxon signed-rank test", "linear fit"), which
state a procedure without needing a number. An item is covered if
it lies inside a claim's span, inside a manuscript quote used as evidence in
some finding (text in figure panels is usually covered this way), or inside
an exclusion: a quote the audit has decided holds no checkable claim, with
the reason.

Uncovered items are reported by sentence, the unit a claim is made in.
References to figures, tables, equations, appendices, and citations ("Figure 2—figure
supplement 1", "Smith et al., 2015") are not items. An exclusion whose quote
is no longer in its paragraph is reported, not silently ignored.

The word list is deliberately broad: a missed claim is worse than an
exclusion that takes a line to write.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import PurePosixPath

from pydantic import BaseModel, ConfigDict

from rigoraudit.schema import AuditRecord, ClaimId, NonEmptyStr

NUMBER = re.compile(
    r"(?<![\w.])[-−–]?\d+(?:[.,]\d+)*(?:\s?[–-]\s?\d+(?:\.\d+)?)?(?:\s?%)?"
)
COMPARISON = re.compile(
    r"\b(?:"
    r"(?:high|low|great|small|larg|strong|weak|fast|slow|steep|shallow)er"
    r"|more|less|fewer"
    r"|(?:increas|decreas|reduc|enhanc)(?:e|ed|es|ing)"
    r"|significant(?:ly)?|correlat(?:ed|es|ion)|predict(?:ed|s)"
    r"|differ(?:ed|s)?|similar(?:ly)?|comparable"
    r"|no (?:difference|effect|modulation|relationship)"
    r")\b",
    re.IGNORECASE,
)
TEST = re.compile(
    r"\b(?:t-tests?|Wilcoxon|rank-sum|signed-rank|sign test|Pearson|Spearman"
    r"|ANOVA|chi-square|Kolmogorov|bootstrap\w*|permutation|shuffl\w*"
    r"|regressions?|linear fit|logistic|ROC|CI|SEM|SD"
    r"|standard (?:error|deviation)s?|confidence intervals?)\b"
    r"|\bs\.[ed]\.(?:m\.)?"
)
REFERENCE = re.compile(
    r"(?:Equations|Eqs\.)\s*\d+(?:(?:,\s*|,? and\s+)\d+)*"
    r"|(?:Figure|Fig\.|Table|Equation|Eq\.|Appendix)\s*\d+[A-Z]?"
    r"(?:\s*[—–-]\s*figure supplement \d+[A-Z]?)?(?:[,–-]\s*\d*[A-Z](?![a-z]))*"
    r"|[A-Z][\w’'-]+(?: et al\.| and [A-Z][\w’'-]+)?,? \d{4}[a-z]?"
)
SENTENCE_END = re.compile(
    r"(?<!et al)(?<!\b[a-z]\.[a-z])(?<!\bvs)(?<!\bcf)[.!?](?=\s+[A-Z(‘“])"
)
"""A sentence ends at ., !, or ? before a capital or an opening bracket, but
not after "et al", "vs", "cf", or a dotted lowercase abbreviation ("i.e.",
"s.e.m."). A sentence that does end at one is merged with the next, which
only widens the sentence a gap is reported in."""


EXCLUSIONS = PurePosixPath("record/coverage_exclusions.json")
"""Where a workspace keeps its exclusions."""


class Exclusion(BaseModel):
    """A quote the audit judged to hold no checkable claim."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    paragraph: NonEmptyStr
    quote: NonEmptyStr
    """Verbatim text of the paragraph; it must contain the excluded items."""
    reason: NonEmptyStr
    restates: ClaimId | None = None
    """The claim this text repeats, when that is the reason."""


class Exclusions(BaseModel):
    """Contents of a workspace's coverage exclusions file."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    exclusions: tuple[Exclusion, ...] = ()


@dataclass(frozen=True)
class Item:
    """One number or comparison word, by character span in its paragraph."""

    start: int
    end: int
    text: str
    kind: str
    """``"number"``, ``"comparison"``, or ``"test"``."""


@dataclass(frozen=True)
class Gap:
    """A sentence with checkable items that nothing covers."""

    paragraph: str
    sentence: str
    items: tuple[Item, ...]


@dataclass(frozen=True)
class Report:
    n_items: int
    gaps: tuple[Gap, ...]
    unused: tuple[Exclusion, ...]
    """Exclusions whose quote is not in their paragraph."""

    @property
    def n_uncovered(self) -> int:
        return sum(len(g.items) for g in self.gaps)


def items(text: str) -> list[Item]:
    """The checkable items in ``text``, references left out."""
    refs = [(m.start(), m.end()) for m in REFERENCE.finditer(text)]
    found = [
        Item(m.start(), m.end(), m.group(), kind)
        for pattern, kind in (
            (NUMBER, "number"),
            (COMPARISON, "comparison"),
            (TEST, "test"),
        )
        for m in pattern.finditer(text)
        if not any(a <= m.start() < b for a, b in refs)
    ]
    return sorted(found, key=lambda i: i.start)


def sentences(text: str) -> list[tuple[int, int]]:
    """Character spans of the sentences in ``text``."""
    bounds, start = [], 0
    for m in SENTENCE_END.finditer(text):
        bounds.append((start, m.end()))
        start = m.end()
    if start < len(text):
        bounds.append((start, len(text)))
    return bounds


def _occurrences(text: str, quote: str) -> list[tuple[int, int]]:
    spans, i = [], text.find(quote)
    while i >= 0:
        spans.append((i, i + len(quote)))
        i = text.find(quote, i + 1)
    return spans


def check(
    paragraphs: Mapping[str, str],
    claim_spans: Mapping[str, Sequence[tuple[int, int]]],
    evidence_quotes: Sequence[str],
    exclusions: Sequence[Exclusion] = (),
) -> Report:
    """Find checkable items in ``paragraphs`` that no claim, evidence, or exclusion covers.

    ``claim_spans`` maps a paragraph key to the character spans of its claims;
    ``evidence_quotes`` are the manuscript quotes cited as evidence anywhere in
    the record.
    """
    excluded: dict[str, list[tuple[int, int]]] = {}
    unused = []
    for e in exclusions:
        spans = _occurrences(paragraphs.get(e.paragraph, ""), e.quote)
        if spans:
            excluded.setdefault(e.paragraph, []).extend(spans)
        else:
            unused.append(e)

    n_items, gaps = 0, []
    for key, text in paragraphs.items():
        covered = [
            *claim_spans.get(key, ()),
            *excluded.get(key, ()),
            *(s for q in evidence_quotes for s in _occurrences(text, q)),
        ]
        found = items(text)
        n_items += len(found)
        loose = [
            i for i in found if not any(a <= i.start and i.end <= b for a, b in covered)
        ]
        for start, end in sentences(text):
            inside = tuple(i for i in loose if start <= i.start < end)
            if inside:
                gaps.append(Gap(key, text[start:end].strip(), inside))
    return Report(n_items, tuple(gaps), tuple(unused))


def record_coverage(
    record: AuditRecord,
    paragraphs: Mapping[str, str],
    claim_paragraph: Mapping[str, str],
    exclusions: Sequence[Exclusion] = (),
) -> Report:
    """:func:`check` for a record whose claims are located by paragraph key.

    ``claim_paragraph`` maps each claim ID to the key of the paragraph its
    anchor's character span refers to. An exclusion that restates a claim
    not in the record is an error.
    """
    ids = {c.id for c in record.claims}
    if missing := sorted({e.restates for e in exclusions if e.restates} - ids):
        raise ValueError(f"exclusions restate claims not in the record: {missing}")
    spans: dict[str, list[tuple[int, int]]] = {}
    for c in record.claims:
        key = claim_paragraph.get(c.id)
        if key is not None:
            spans.setdefault(key, []).append((c.anchor.char_start, c.anchor.char_end))
    quotes = [
        o.anchor.quote
        for f in record.findings
        for o in f.observations
        if o.anchor.kind == "manuscript"
    ]
    return check(paragraphs, spans, quotes, exclusions)
