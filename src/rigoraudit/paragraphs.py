# Copyright (c) 2026, Joshua I. Gold
# SPDX-License-Identifier: BSD-2-Clause
"""The manuscript's extracted paragraphs, each under a short label.

The extract step writes ``work/extract/paragraphs.json``: a list of
paragraphs in reading order, each with its section (levels joined by
``" › "``), its number within the section, and its text::

    [{"section": "Results › Learning", "paragraph": 2, "text": "...",
      "key": "R1.2", "page": 4}, ...]

``key`` and ``page`` are optional; ``pages``, a list, may stand for
``page`` (its first entry is where the paragraph starts). A paragraph that
runs onto another page has ``page_starts``: the character offset in its
text where each of its pages starts, ``[[0, 4], [812, 5]]``, so a quote
from it can name the page it is printed on. ``transcribed``,
true for text typed in from a figure's image rather than taken from the
PDF's text, means its quotes cannot be checked against the text layer.
Without a ``key``, a paragraph's label is the first letter of its section,
the section's place among sections starting with that letter, and the
paragraph number: the second paragraph of the first Results subsection is
``R1.2``. Claim IDs are built from labels (decision 0002), so labels must
be unique and stay the same between runs.

A display equation is not in the text: a mark stands where it is set,
``"[Equation 3]"`` (``"[Equation]"`` if it has no number), and the
equation is listed in ``work/extract/equations.json`` with a picture.
Quotes may include the mark (:mod:`rigoraudit.verify`).
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path, PurePosixPath

from rigoraudit.numbering import NUMBER

PARAGRAPHS = PurePosixPath("work/extract/paragraphs.json")
SEPARATOR = " › "
LABEL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
EQUATION_MARK = re.compile(rf"\[Equation(?: ({NUMBER}))?\]")
"""The mark that stands for a display equation in a paragraph's text."""


def equation_mark(number: str | None) -> str:
    """The mark for a display equation with this number (or none)."""
    return f"[Equation {number}]" if number else "[Equation]"


@dataclass(frozen=True)
class Paragraph:
    label: str
    section: str
    number: int
    text: str
    page: int | None = None
    transcribed: bool = False
    """Typed in from a figure's image, so not in the PDF's text layer."""
    page_starts: tuple[tuple[int, int], ...] = ()
    """(offset in ``text``, page) where each of its pages starts."""

    def page_at(self, offset: int) -> int | None:
        """The page the character at ``offset`` is printed on."""
        page = self.page
        for start, p in self.page_starts:
            if start > offset:
                break
            page = p
        return page

    def locate(self, quote: str) -> tuple[int, str]:
        """Where ``quote`` starts in the text, and the quote as the text has it.

        A quote accepted before the paragraphs were extracted again may lack
        a few characters the new text puts in from the PDF (a "∼" before a
        number, an item's "2."). Such a quote is still found if the text
        differs from it only by insertions of at most :data:`PUT_IN`
        characters each, with no two letters A–Z or a–z in a row (a symbol
        such as "x̄" may be put in, a word such as "no" may not), and only
        one place in the text fits; the text's version is returned. Otherwise
        a :class:`ValueError` says which quote is missing and what to do.
        """
        at = self.text.find(quote)
        if at >= 0:
            return at, quote
        found = _put_in(self.text, quote)
        if len(found) == 1:
            return found.pop()
        n = next(n for n in range(len(quote), -1, -1) if quote[:n] in self.text)
        at = self.text.find(quote[:n]) + n
        where = (
            f"; it matches through …{quote[max(0, n - 30) : n]!r}, then the "
            f"quote has {quote[n : n + 30]!r} and the paragraph "
            f"{self.text[at : at + 30]!r}"
            if n >= _ENDS
            else ""
        )
        raise ValueError(
            f"Paragraph {self.label} does not have this quote word for word: "
            f"{quote!r}{where}. If the paragraphs were extracted again since the "
            "answer was accepted, fix the paragraph to read as before, or "
            "delete the answer that quotes it and hand that step off again."
        )

    @property
    def top(self) -> str:
        """The top-level section, e.g. ``"Results"``."""
        return self.section.split(SEPARATOR)[0]

    @property
    def place(self) -> str:
        """Where the paragraph is, for people: ``"Results › Learning ¶2"``."""
        return f"{self.section} ¶{self.number}"


PUT_IN = 3
"""Most characters :meth:`Paragraph.locate` lets the text put into a quote
at one place."""
_ENDS = 15
"""Characters at a quote's start or end :meth:`Paragraph.locate` finds it by."""


def _put_in(text: str, quote: str) -> set[tuple[int, str]]:
    """Every (start, span) of ``text`` that is ``quote`` with a few
    characters put in (see :meth:`Paragraph.locate`)."""
    if len(quote) < 2 * _ENDS:
        return set()
    room = len(quote) + 4 * PUT_IN
    windows = [(i, i + room, True) for i in _starts(text, quote[:_ENDS])] + [
        (max(0, i + _ENDS - room), i + _ENDS, False)
        for i in _starts(text, quote[-_ENDS:])
    ]
    found = set()
    for start, end, from_head in windows:
        window = text[start:end]
        ops = SequenceMatcher(None, quote, window, autojunk=False).get_opcodes()
        # the window runs past the quote at one end
        if ops and ops[-1 if from_head else 0][0] == "insert":
            ops = ops[:-1] if from_head else ops[1:]
        if not ops or ops[0][0] != "equal" or ops[-1][0] != "equal":
            continue
        extras = [window[j:k] for op, _, _, j, k in ops if op == "insert"]
        if any(op not in ("equal", "insert") for op, *_ in ops) or not extras:
            continue
        if any(len(x) > PUT_IN or re.search("[A-Za-z]{2}", x) for x in extras):
            continue
        a, b = ops[0][3], ops[-1][4]
        found.add((start + a, window[a:b]))
    return found


def _starts(text: str, part: str) -> list[int]:
    """Every place ``part`` starts in ``text``."""
    out, at = [], text.find(part)
    while at >= 0:
        out.append(at)
        at = text.find(part, at + 1)
    return out


def read_paragraphs(path: Path) -> list[Paragraph]:
    """Read an extracted-paragraphs file, giving every paragraph a label."""
    entries = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(entries, list):
        raise TypeError(f"{path}: expected a list of paragraphs")
    order: dict[str, list[str]] = {}
    for e in entries:
        sections = order.setdefault(e["section"][:1].upper(), [])
        if e["section"] not in sections:
            sections.append(e["section"])
    out = []
    for e in entries:
        label = e.get("key")
        if label is None:
            letter = e["section"][:1].upper()
            label = f"{letter}{order[letter].index(e['section']) + 1}.{e['paragraph']}"
        if not LABEL.match(label):
            raise ValueError(f"{path}: paragraph label {label!r} is not a valid label")
        page = e.get("page", (e.get("pages") or [None])[0])
        out.append(
            Paragraph(
                label,
                e["section"],
                e["paragraph"],
                e["text"],
                page,
                bool(e.get("transcribed")),
                tuple((int(a), int(b)) for a, b in e.get("page_starts", ())),
            )
        )
    seen: set[str] = set()
    for p in out:
        if p.label in seen:
            raise ValueError(f"{path}: paragraph label {p.label} is used twice")
        seen.add(p.label)
    return out


def in_scope(section: str, scope: Sequence[str]) -> bool:
    """Whether a paragraph's section is audited: some pattern in ``scope``
    (a regular expression) matches at its start, so ``"Results"`` takes
    every Results subsection."""
    return any(re.match(pattern, section) for pattern in scope)


def split_page_starts(
    starts: Sequence[Sequence[int]], offset: int
) -> tuple[list[list[int]], list[list[int]]]:
    """``page_starts`` of a paragraph's text before and after ``offset``,
    the second counted from ``offset``."""
    head = [[a, b] for a, b in starts if a < offset]
    tail = [[a - offset, b] for a, b in starts if a >= offset]
    if head and (not tail or tail[0][0] > 0):
        tail.insert(0, [0, head[-1][1]])
    return head, tail


def join_page_starts(
    first: Sequence[Sequence[int]], second: Sequence[Sequence[int]], at: int
) -> list[list[int]]:
    """``page_starts`` of two paragraphs' texts joined, the second starting
    at ``at``; a page the first already ends on is not repeated."""
    out = [list(x) for x in first]
    for a, b in second:
        if not out or out[-1][1] != b:
            out.append([a + at, b])
    return out
