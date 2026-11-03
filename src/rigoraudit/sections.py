# Copyright (c) 2026, Joshua I. Gold
# SPDX-License-Identifier: BSD-2-Clause
"""The manuscript's major sections, in order, for organizing the report.

The headings come from the PDF's outline (bookmarks), which publishers
generate from the manuscript's own section structure, so the names and their
order are the authors'. Major sections are the outline's top level, below
the paper's title when the outline has a single root (the usual case).
Subsections are the level below that; deeper levels are ignored. A
subsection named as a different main section ("Results" under "Methods")
is taken as a major section, and entries for figures and tables are left
out.

Anchors name their section as ``"Major › Subsection"`` and are placed by
name. Figure legends and text in panels (``"Figure 5 legend"``,
``"Figure 5D (text in panel)"``) are not in the outline; they are placed
with the subsection whose text cites the figure most often (the earliest,
on a tie), found in the PDF text layer. An Introduction that previews
Figure 2 once does not take it from the Results subsection built on it, and
when Results cites a figure at all, only Results subsections count, so
Methods describing how the figure was made do not take it either.
Anything that cannot be placed by name falls back to the section in which
its page starts.

A PDF without an outline falls back to :data:`STANDARD` headings found as
lines of their own in the text layer (:func:`headings_from_text`). Each is
shown as the manuscript writes it ("Materials and Methods"), and anchors are
matched to it by kind as well as by name, so an anchor in "Methods › ..."
finds it. The fallback finds major sections only, not subsections.
"""

from __future__ import annotations

import json
import re
import unicodedata
from bisect import bisect_right
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

SEPARATOR = " › "
FIGURE = re.compile(r"^Figure\s+(\d+)")
CITATION = re.compile(r"\bFig(?:ure)?s?\.?\s*(\d+)(?!\d)")
MAX_HEADING_LINES = 4

STANDARD: dict[str, tuple[str, ...]] = {
    "Abstract": ("Abstract", "Summary", "Synopsis"),
    "Introduction": ("Introduction", "Background"),
    "Results": ("Results", "Results and Discussion", "Findings"),
    "Discussion": (
        "Discussion", "General Discussion", "Conclusion", "Conclusions",
        "Discussion and Conclusions", "Concluding Remarks",
    ),
    "Methods": (
        "Methods", "Method", "Materials and Methods", "Material and Methods",
        "Methods and Materials", "Experimental Procedures", "Experimental Methods",
        "Experimental Model and Subject Details", "Methodology", "STAR Methods",
        "STAR★Methods", "Online Methods", "Method Details", "Methods Summary",
        "Patients and Methods", "Subjects and Methods", "Participants and Methods",
    ),
    "Appendices": (
        "Appendix", "Appendices", "Supplementary Information",
        "Supplementary Material", "Supplementary Materials",
        "Supporting Information", "Supplemental Information",
    ),
    "Other": (
        "Acknowledgements", "Acknowledgments", "References", "Bibliography",
        "Literature Cited", "Funding", "Author Contributions", "Competing Interests",
        "Conflict of Interest", "Conflicts of Interest", "Declaration of Interests",
        "Data Availability", "Code Availability", "Data and Code Availability",
        "Ethics", "Abbreviations", "Additional Information", "Additional Files",
    ),
}  # fmt: skip
"""Standard major sections, each with the names it goes by. *Other* covers
back matter, so that references and acknowledgements do not run on as part
of the Discussion or Methods."""

_KIND = {compact_name: kind for kind, names in STANDARD.items()
         for compact_name in (re.sub(r"[^0-9a-z]", "", n.lower()) for n in names)}  # fmt: skip
_NUMBERING = re.compile(r"^\s*(?:\d+(?:\.\d+)*\.?|[IVX]+\.|[A-Z]\.)\s+")
_APPENDIX = re.compile(r"^appendix[0-9a-z]{0,2}$")
_MAIN = {"Abstract", "Introduction", "Results", "Discussion", "Methods"}
_FIGURE_ENTRY = re.compile(r"^(?:Figure|Fig\.?|Table)\W*\d", re.IGNORECASE)
"""An outline entry for a figure or table, which some publishers add."""
LONGEST = 150
"""Characters in the longest outline entry taken for a heading. Some
publishers' outlines have entries holding a passage of text instead."""
_YEAR = re.compile(r"(?:19|20)\d\d")


def _headings_only(outline: Sequence[Heading]) -> list[Heading]:
    """The outline without entries for figures and tables, or passages of
    text. A passage that cites several years is the reference list, and is
    named so; other passages are left out."""
    kept = []
    for h in outline:
        if _FIGURE_ENTRY.match(h.title):
            continue
        if len(h.title) > LONGEST:
            if len(_YEAR.findall(h.title)) < 3:
                continue
            h = Heading("References", h.level, h.page)
        kept.append(h)
    return kept


@dataclass(frozen=True)
class Heading:
    """One outline entry. ``level`` 0 is the outline's top level."""

    title: str
    level: int
    page: int


@dataclass(frozen=True, order=True)
class Place:
    """Where a piece of text sits: its major section and subsection.

    ``major`` and ``sub`` are indices in reading order; ``sub`` is 0 for text
    before the first subsection.
    """

    major: int
    sub: int


def load_outline(path: Path) -> tuple[Heading, ...]:
    """Read headings written as ``{"headings": [{title, level, page}, ...]}``."""
    data = json.loads(path.read_text())
    return tuple(Heading(**h) for h in data["headings"])


def compact(text: str) -> str:
    """Lowercase letters and digits only, for matching headings across layouts."""
    text = unicodedata.normalize("NFKC", text).lower()
    return re.sub(r"[^0-9a-z]", "", text)


def heading_key(text: str) -> str:
    """A heading's title or printed line without its numbering, compacted, so
    "2.2 Model fits" and "2.2 | Model fits" match."""
    return compact(_NUMBERING.sub("", unicodedata.normalize("NFKC", text)))


def standard_kind(title: str) -> str | None:
    """Which :data:`STANDARD` section a heading names, if any.

    Section numbering ("2.", "II.", "B.") is ignored, and "Appendix A" or
    "Appendix 1" count as appendices.
    """
    key = compact(_NUMBERING.sub("", unicodedata.normalize("NFKC", title)))
    if _APPENDIX.match(key):
        return "Appendices"
    return _KIND.get(key)


def headings_from_text(pages: Sequence[str]) -> tuple[Heading, ...]:
    """Standard major-section headings found as lines of their own.

    A heading may wrap onto a second line. Only the first heading of each
    name counts, so a running header repeating "Results" on every page adds
    nothing; *Other* sections keep each distinct name ("References",
    "Funding").
    """
    found, seen = [], set()
    for p, page in enumerate(pages):
        lines = [line.strip() for line in page.splitlines()]
        for i, line in enumerate(lines):
            for title in (line, f"{line} {lines[i + 1]}" if i + 1 < len(lines) else ""):
                kind = standard_kind(title) if title else None
                if kind is None:
                    continue
                key = compact(title) if kind == "Other" else kind
                if key not in seen:
                    seen.add(key)
                    found.append(Heading(_NUMBERING.sub("", title), 0, p + 1))
                break
    return tuple(found)


def figure_number(section: str) -> int | None:
    """The figure a legend or panel section belongs to, if it is one."""
    m = FIGURE.match(section)
    return int(m.group(1)) if m else None


def _levels(outline: Sequence[Heading]) -> tuple[int, int]:
    """Outline levels of the major sections and their subsections."""
    top = min((h.level for h in outline), default=0)
    major = top + 1 if sum(h.level == top for h in outline) == 1 else top
    return major, major + 1


class Sections:
    """A manuscript's major sections and subsections, located in its text.

    ``pages[0]`` is page 1 of the PDF text layer. ``source`` says where the
    headings came from: ``"outline"`` or, without one, ``"text"``.
    """

    def __init__(self, outline: Sequence[Heading], pages: Sequence[str]) -> None:
        outline = _headings_only(outline)
        self.source = "outline"
        if not any(h.level == _levels(outline)[0] for h in outline):
            outline, self.source = headings_from_text(pages), "text"
        major, sub = _levels(outline) if self.source == "outline" else (0, 1)
        self.majors: list[str] = []
        self.subsections: list[list[str]] = []
        self._lines = [p.splitlines() for p in pages]
        starts: list[tuple[int, int]] = []
        places: list[Place] = []
        after = (0, 0)
        for h in outline:
            kind = standard_kind(h.title)
            if h.level == major or (
                h.level == sub
                and kind in _MAIN
                and self.majors
                and kind != standard_kind(self.majors[-1])
            ):  # a main section the outline puts one level down
                self.majors.append(h.title)
                self.subsections.append([])
                place = Place(len(self.majors) - 1, 0)
            elif h.level == sub and self.majors:
                self.subsections[-1].append(h.title)
                place = Place(len(self.majors) - 1, len(self.subsections[-1]))
            else:
                continue
            after = self._locate(h, after)
            starts.append(after)
            places.append(place)
        self._starts, self._places = starts, places

    def _locate(self, h: Heading, after: tuple[int, int]) -> tuple[int, int]:
        """(page index, line) where a heading's title begins as its own line(s).

        Failing that, where it begins a paragraph, the text running on after
        it on its last line (a run-in heading). Falls back to the top of its
        page if the title is not found there.
        """
        target, page = heading_key(h.title), h.page - 1
        if not 0 <= page < len(self._lines):
            return max(after, (max(page, 0), 0))
        lines = self._lines[page]
        first = after[1] + 1 if after[0] == page else 0
        run_in = None
        for i in range(first, len(lines)):
            joined = heading_key(lines[i])
            if not joined:
                continue
            for more in lines[i + 1 : i + MAX_HEADING_LINES]:
                if joined == target or not target.startswith(joined):
                    break
                joined += compact(more)
            if joined == target:
                return page, i
            if run_in is None and joined.startswith(target):
                run_in = i
        return (page, run_in) if run_in is not None else max(after, (page, 0))

    @property
    def headings(self) -> list[tuple[int, int, Place]]:
        """(1-based page, line, place) where each heading starts, in order."""
        return [(p + 1, i, pl) for (p, i), pl in zip(self._starts, self._places)]

    def at(self, page: int, line: int = 0) -> Place:
        """The section containing (1-based page, line)."""
        i = bisect_right(self._starts, (page - 1, line)) - 1
        return self._places[max(i, 0)] if self._places else Place(0, 0)

    def citations(self, figure: int) -> list[tuple[int, int]]:
        """(1-based page, line) of each text line that cites ``figure``.

        A legend's own title line (``"Figure 5. ..."``) is not a citation.
        """
        legend = re.compile(rf"^\s*Figure\s+{figure}\.\s")
        return [
            (p + 1, i)
            for p, lines in enumerate(self._lines)
            for i, line in enumerate(lines)
            if not legend.match(line)
            and any(int(n) == figure for n in CITATION.findall(line))
        ]

    def figure_place(self, figure: int) -> Place | None:
        """The subsection that cites ``figure`` most often; the earliest on a tie.

        Only Results subsections count when any of them cites the figure, so
        Methods that describe how a figure was made do not take it from them.
        """
        counts: dict[Place, int] = {}
        for cited in self.citations(figure):
            place = self.at(*cited)
            counts[place] = counts.get(place, 0) + 1
        results = {
            pl: n
            for pl, n in counts.items()
            if pl.major < len(self.majors)
            and standard_kind(self.majors[pl.major]) == "Results"
        }
        counts = results or counts
        return max(
            counts, key=lambda pl: (counts[pl], -pl.major, -pl.sub), default=None
        )

    def place(self, section: str, page: int | None = None) -> Place:
        """Where text in anchor section ``section`` (starting on ``page``) sits."""
        fig = figure_number(section)
        if fig is not None and (home := self.figure_place(fig)) is not None:
            return home
        head, _, rest = section.partition(SEPARATOR)
        names = [compact(m) for m in self.majors]
        kinds = [standard_kind(m) for m in self.majors]
        m = None
        if compact(head) in names:
            m = names.index(compact(head))
        elif (kind := standard_kind(head)) is not None and kinds.count(kind) == 1:
            m = kinds.index(kind)
        if m is not None:
            subs = [compact(s) for s in self.subsections[m]]
            sub = rest.split(SEPARATOR)[0]
            return Place(m, subs.index(compact(sub)) + 1 if compact(sub) in subs else 0)
        return self.at(page) if page else Place(len(self.majors), 0)

    def title(self, place: Place) -> str:
        """The major section's name, or "Other" for text placed after them all."""
        return self.majors[place.major] if place.major < len(self.majors) else "Other"
