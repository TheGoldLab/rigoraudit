# Copyright (c) 2026, Joshua I. Gold
# SPDX-License-Identifier: BSD-2-Clause
"""The extract step: the manuscript's paragraphs, from its files.

``rigoraudit extract`` writes, in ``work/extract/``:

- ``published.txt``: the PDF's text layer, each page after a line
  ``=== PAGE n ===``. Quotes are checked against it, since the PDF is the
  manuscript of record. A supplement the manifest names (a separate PDF
  with what the article's leaves out) follows, its pages numbered on and
  marked with its file's name (``=== PAGE n (figures.pdf) ===``). Symbols
  in typesetters' maths fonts are given as printed (``"p = 0.03"``, not
  ``"p ¼ 0.03"``; :data:`MATH_FONTS`).
- ``outline.json``: the PDF's outline (bookmarks), the section headings.
- ``paragraphs.json``: the paragraphs, in the form :mod:`rigoraudit.paragraphs`
  reads, each with the PDF pages it is on.
- ``equations.json``: the display equations, from the publisher's XML
  (:func:`jats_equations`, matched to the PDF's by :func:`match_equations`)
  or the PDF (:func:`display_equations`), each with its number, the
  paragraph it is set in, and its page and place on the page. In the
  paragraphs' text a mark stands for each (``"[Equation 3]"``).
- ``equations/``: a picture of each equation as printed
  (:mod:`rigoraudit.pictures`), ``001.png`` for the first.

There are two ways to find the paragraphs:

1. **Publisher's XML.** Journals that publish the article as XML (the JATS
   format) mark every section, paragraph, figure legend, and table. When
   there is one ``.xml`` file beside the manuscript, the paragraphs come
   from it, and each sentence is looked up in the PDF text layer for its
   pages; sentences not found there are listed under ``not_in_pdf``.
2. **PDF only.** Paragraphs are cut from the printed lines, using where
   and how each is printed: running headers and footers are removed,
   sections come from :class:`~rigoraudit.sections.Sections`, a paragraph
   starts at an indented line or after extra space, and legends are told
   from the body by their type size, even where the PDF mixes the two.
   These breaks are a best guess, so the paragraphs are marked
   ``approximate``; the reference list and text in other type sizes (labels
   in figures, table cells) are left out (and counted).
3. **GROBID**, if the manifest names a GROBID server
   (:mod:`rigoraudit.grobid`): it reads the PDF instead of route 2, and its
   paragraphs are looked up in the PDF text layer as in route 1. They are
   still a best guess, so they are marked ``approximate``. If the server
   does not answer, route 2 is used, and the result says why.

Paragraphs get the tool's own labels (no ``key``), so claim IDs follow the
manuscript's sections whatever the journal.
"""

from __future__ import annotations

import json
import logging
import re
import statistics
import unicodedata
import xml.etree.ElementTree as ET
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from itertools import pairwise
from pathlib import Path, PurePosixPath

from pypdf import PdfReader
from pypdf.errors import PyPdfError

from rigoraudit import grobid, numbering, pictures
from rigoraudit.numbering import NUMBER
from rigoraudit.paragraphs import (
    EQUATION_MARK,
    PARAGRAPHS,
    equation_mark,
    split_page_starts,
)
from rigoraudit.sections import (
    SEPARATOR,
    Heading,
    Place,
    Sections,
    compact,
    figure_number,
    heading_key,
    standard_kind,
)
from rigoraudit.verify import ManuscriptText
from rigoraudit.words import plural

FOLDER = PurePosixPath("work/extract")
TEXT = FOLDER / "published.txt"
OUTLINE = FOLDER / "outline.json"
EQUATIONS_FILE = FOLDER / "equations.json"
PICTURES = FOLDER / "equations"
PAGE = re.compile(r"\n=== PAGE \d+(?: \(([^\n)]*)\))? ===\n")
"""A page's first line; a supplement's pages name their file in brackets."""
SENTENCE = re.compile(r"(?<=[.!?])\s+(?=[A-Z(\u0391-\u03a9\u03b1-\u03c9])")
FRONT = "Front matter"
RUN_IN = re.compile(r"(abstract|summary)\b[.:]?\s+", re.IGNORECASE)
"""A heading printed at the start of the abstract's first line."""
READ_ERRORS = (OSError, ValueError, ET.ParseError, PyPdfError)
"""What reading a damaged or wrong file can raise."""


# --- The PDF -----------------------------------------------------------------

_SYMBOLS = {str(i): s for i, s in enumerate("−·×∗÷⋄±∓⊕⊖⊗⊘⊙○°∙≍≡⊆⊇≤≥⪯⪰∼≈⊂⊃≪≫≺≻←→↑↓↔")}
"""A TeX symbol font's first characters, by number (``/C0`` is a minus
sign). Number 14 is a small circle, nearly always a degree sign."""
_DELIMITERS = {"0": "(", "1": ")", "2": "[", "3": "]", "8": "{", "9": "}", "14": "/"}
_DELIMITERS |= {"16": "(", "17": ")", "18": "(", "19": ")", "20": "[", "21": "]"}
_DELIMITERS |= {"26": "{", "27": "}", "32": "(", "33": ")"}
"""A TeX large-delimiter font's brackets, by number."""
_MATH_PI = {"ð": "(", "Þ": ")", "¼": "=", "þ": "+", "½": "["}
_GREEK = {"d": "δ", "m": "μ", "s": "σ", "t": "τ", "w": "ω", "O": "Ω"}
_PIECES = {"0": "(", "1": ")", "2": "[", "3": "]", "8": "{", "9": "}"}
"""Top pieces of brackets built up from parts; the other parts print as
nothing."""
MATH_FONTS: dict[str, dict[str, str]] = {
    "AdvP4C4E74": _MATH_PI
    | {f"/C{n}": s for n, s in _SYMBOLS.items()}
    | {"/C138": "]", "j": "|", "f": "{", "g": "}", "p": "√", "0": "′"},
    "AdvP4C4E46": {f"/C{n}": s for n, s in _DELIMITERS.items()}
    | _PIECES
    | dict.fromkeys("<>:@ABCﬃ", "")
    | {"P": "∑", "X": "∑", "r": "√", "ð": "∫", "Ð": "∫"},
    "AdvP4C4E51": {";": ",", ":": ".", "=": "/"},
    "AdvP80675": {f"/C{n}": s for n, s in _SYMBOLS.items()}
    | {";": "∼", ",": "<", ".": ">", "1": "+"},
    "AdvP40798": {"~": "=", "{": "−", "z": "+"},
    "AdvPSSym": {"ª": "©", "˛": "∈"},
    "AdvEls-ent4": {"o": "<"},
    "AdvPi1": _GREEK | {"4": ">"},
    "AdvPi2": _GREEK,
    "AdvMacMthSyN": _MATH_PI,
    "TeX_CM_Maths_Symbols": _MATH_PI,
}
"""Fonts that typesetters use for mathematics, whose characters the PDF's
text gives as other characters (``"p ¼ 0.03"`` for ``"p = 0.03"``) or as
character numbers (``"/C0"``), and what each stands for."""
_CHARACTER = re.compile(r"/C\d+|.", re.DOTALL)


def _font_name(font) -> str:
    """A PDF font's name, without its subset tag (``"ABCDEF+"``)."""
    return str(font.get("/BaseFont", "")).split("+")[-1].lstrip("/") if font else ""


def _symbols(text: str, font: str) -> str:
    """Text drawn in ``font``, with a maths font's characters as printed
    (:data:`MATH_FONTS`)."""
    table = MATH_FONTS.get(font)
    if not table:
        return text
    return _CHARACTER.sub(lambda m: table.get(m[0], m[0]), text)


def _page_text(page) -> str:
    """A page's text: the pieces pypdf reads from it, joined (as its own
    ``extract_text`` joins them), with maths fonts' characters as printed."""
    pieces: list[str] = []

    def visit(text, cm, tm, font, size) -> None:
        pieces.append(_symbols(text, _font_name(font)))

    page.extract_text(visitor_text=visit)
    return "".join(pieces)


def _visible(title: str) -> str:
    """An outline title without the invisible characters some PDFs put in it
    (a byte-order mark, a zero-width joiner, an object placeholder)."""
    kept = (c for c in title if unicodedata.category(c) != "Cf" and c != "\ufffc")
    return " ".join("".join(kept).split())


def read_pdf(path: Path) -> tuple[list[str], tuple[Heading, ...]]:
    """The PDF's text, page by page (:func:`_page_text`), and its outline."""
    logging.getLogger("pypdf").setLevel(logging.ERROR)  # font notes, not errors
    reader = PdfReader(path)
    pages = [_page_text(p) for p in reader.pages]
    headings: list[Heading] = []

    def walk(items: list, level: int) -> None:
        for item in items:
            if isinstance(item, list):
                walk(item, level + 1)
            else:
                page = reader.get_destination_page_number(item)
                if page is None:  # points at no page of this file
                    continue
                headings.append(Heading(_visible(str(item.title)), level, page + 1))

    walk(reader.outline, 0)
    return pages, tuple(headings)


def write_text_layer(
    folder: Path,
    pages: Sequence[str],
    outline: Sequence[Heading],
    source: str,
    supplement: tuple[str, Sequence[str]] | None = None,
) -> None:
    """Write ``published.txt`` and ``outline.json`` into ``folder``.

    A ``supplement`` (its file name and pages) follows the article's pages,
    numbered on from them, each marked with the file's name.
    """
    folder.mkdir(parents=True, exist_ok=True)
    name, more = supplement or ("", ())
    marks = [""] * len(pages) + [f" ({name})"] * len(more)
    (folder / TEXT.name).write_text(
        "".join(
            f"\n=== PAGE {i}{m} ===\n{p}"
            for i, (m, p) in enumerate(zip(marks, [*pages, *more]), 1)
        ),
        encoding="utf-8",
    )
    data = {"source": source, "headings": [h.__dict__ for h in outline]}
    (folder / OUTLINE.name).write_text(
        json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def _read_layer(path: Path) -> tuple[list[str], list[str]]:
    """The pages of a ``published.txt`` file, and the file each is in (``""``
    for the article)."""
    parts = PAGE.split(path.read_text(encoding="utf-8"))[1:]
    return parts[1::2], [f or "" for f in parts[::2]]


def read_pages(path: Path) -> list[str]:
    """The article's pages in a ``published.txt`` file; ``[0]`` is page 1."""
    pages, files = _read_layer(path)
    return [p for p, f in zip(pages, files) if not f]


def read_text(path: Path) -> ManuscriptText:
    """A ``published.txt`` file's pages, a supplement's included, to search."""
    return ManuscriptText(*_read_layer(path))


# --- Route 1: publisher's XML (JATS) ----------------------------------------

MATH = "math"
INVISIBLE = dict.fromkeys(range(0x2061, 0x2065))
"""MathML's invisible operators (function application, times, separator,
plus), which print as nothing."""
OUT_OF_LINE = {
    "fig", "fig-group", "table-wrap", "table-wrap-group", "boxed-text",
    "supplementary-material", "media", "fn", "disp-formula",
}  # fmt: skip
"""Elements whose text is not printed where they sit in a paragraph; figure
and table captions get their own sections, display equations their own
list."""
REFERENCES = {"ref-list"}
ATTACHED = {"sub-article", "response"}
"""Documents published with the article, such as peer reviews and the
authors' replies; they are not part of the manuscript."""
ATTACHED_SECTIONS = {"synthesis-author-response"}
"""Section types that hold such a document inside the article (eNeuro's
reviewers' "Synthesis" and the authors' reply)."""


def _local(tag: object) -> str:
    """An element's name without its namespace ("" for comments)."""
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


def _chars(e: ET.Element) -> str:
    name = _local(e.tag)
    if name == "alternatives":
        # the same formula several ways: keep the MathML, else the first
        kids = list(e)
        chosen = next(
            (c for c in kids if _local(c.tag) == MATH), kids[0] if kids else None
        )
        return _chars(chosen) if chosen is not None else ""
    if name == "msubsup" and len(e) == 3:
        # PDFs print the superscript before the subscript
        base, sub, sup = (_chars(c) for c in e)
        return base + sup + sub
    inner = e.text or ""
    for c in e:
        if _local(c.tag) not in OUT_OF_LINE:
            inner += _chars(c)
        elif _local(c.tag) == "disp-formula":
            inner += f" {equation_mark(_number(c))} "
        inner += c.tail or ""
    if name == "inline-formula" and not inner.strip():
        return FORMULA_PICTURE
    return inner


FORMULA_PICTURE = "\ufffc"
"""Stands, while the XML is read, for a formula given only as a picture."""


def _number(formula: ET.Element) -> str | None:
    """A display formula's number, from its label, without brackets; with no
    label, from an id such as ``"eqnA1"`` (bioRxiv's XML gives numbered
    equations only that, and unnumbered ones ``"ueqn1"``)."""
    found = re.search(NUMBER, text_of(_child(formula, "label")))
    if found is None:
        found = re.fullmatch(rf"eqn({NUMBER})", formula.get("id", ""))
        return found.group(1) if found else None
    return found.group()


def text_of(e: ET.Element | None) -> str:
    """An element's printed text, with whitespace collapsed."""
    return _text_and_formulas(e)[0]


def _text_and_formulas(e: ET.Element | None) -> tuple[str, list[int]]:
    """An element's printed text, with whitespace collapsed, and the places
    in it of formulas given only as pictures (which it leaves out)."""
    if e is None:
        return "", []
    text, formulas = "", []
    for n, part in enumerate(_chars(e).translate(INVISIBLE).split(FORMULA_PICTURE)):
        part = " ".join(part.split())
        if n:
            formulas.append(len(text) + (1 if text and part else 0))
        text = " ".join(t for t in (text, part) if t)
    return text, formulas


def _article(root: ET.Element):
    """Every element of the article itself, in document order."""
    yield root
    for c in root:
        if _local(c.tag) not in ATTACHED and c.get("sec-type") not in ATTACHED_SECTIONS:
            yield from _article(c)


def _child(e: ET.Element, name: str) -> ET.Element | None:
    return next((c for c in e if _local(c.tag) == name), None)


class _Collector:
    """Paragraphs in reading order, numbered within each section, and the
    display equations set in or after them."""

    def __init__(self) -> None:
        self.out: list[dict] = []
        self.count: Counter[str] = Counter()
        self.equations: list[dict] = []

    def paragraph(self, section: str, e: ET.Element) -> None:
        """A paragraph and the equations in it, or an equation set between
        paragraphs, whose mark goes at the end of the one before."""
        last = self.out[-1] if self.out and self.count[section] else None
        if _local(e.tag) != "disp-formula":
            self.add(section, *_text_and_formulas(e))
            last = self.out[-1] if self.count[section] else None
        elif last is not None:
            last["text"] += " " + equation_mark(_number(e))
        formulas = [f for f in e.iter() if _local(f.tag) == "disp-formula"]
        # the formulas' marks are the last in the paragraph's text
        marks: list[re.Match | None] = (
            list(EQUATION_MARK.finditer(last["text"])) if last else []
        )
        marks = marks[len(marks) - len(formulas) :] if formulas else []
        marks += [None] * (len(formulas) - len(marks))
        for f, mark in zip(formulas, marks, strict=True):
            inner = (f.text or "") + "".join(
                (_chars(c) if _local(c.tag) != "label" else "") + (c.tail or "")
                for c in f
            )
            self.equations.append(
                {
                    "number": _number(f),
                    "section": section,
                    "paragraph": last["paragraph"] if last else None,
                    "at": mark.start() if mark else None,
                    "text": " ".join(inner.translate(INVISIBLE).split()),
                }
            )

    def add(self, section: str, text: str, formulas: list[int] | None = None) -> None:
        if text:
            self.count[section] += 1
            self.out.append(
                {"section": section, "paragraph": self.count[section], "text": text}
            )
            if formulas:
                self.out[-1]["formulas"] = formulas

    def section(self, e: ET.Element, path: list[str]) -> None:
        """A section and its subsections; an untitled one stays in ``path``."""
        if e.get("sec-type") in ATTACHED_SECTIONS:
            return
        title = text_of(_child(e, "title"))
        here = [*path, title] if title else path
        for c in e:
            name = _local(c.tag)
            if name in ("p", "list", "disp-quote", "def-list", "disp-formula"):
                self.paragraph(SEPARATOR.join(here) or "Main text", c)
            elif name in ("sec", "ack", "app", "app-group", "glossary"):
                self.section(c, here)

    def caption(self, e: ET.Element, label: str, kind: str) -> None:
        cap = _child(e, "caption")
        if cap is None:
            return
        self.add(f"{label} {kind}", text_of(_child(cap, "title")))
        for p in cap:
            if _local(p.tag) == "p":
                self.add(f"{label} {kind}", *_text_and_formulas(p))


def jats_paragraphs(root: ET.Element) -> list[dict]:
    """The article's paragraphs, from its JATS XML.

    Abstracts first, then the body and back matter (but not the reference
    list), then figure legends, table captions, and table rows. Sections are
    named by their titles, levels joined by ``" › "``. Peer reviews and
    replies published with the article are left out, and so are display
    equations (:func:`jats_equations`). Formulas given only as pictures are
    left out too; a paragraph with any lists their places in its text under
    ``formulas``, for :func:`fill_in`.
    """
    return _collect(root).out


def jats_equations(root: ET.Element) -> list[dict]:
    """The article's display equations, from its JATS XML: each one's
    number (without brackets), text (from its MathML, if it has any), and
    the paragraph it is set in or after."""
    return _collect(root).equations


def _collect(root: ET.Element) -> _Collector:
    elements = list(_article(root))
    c = _Collector()
    for e in elements:
        if _local(e.tag) == "abstract":
            kind = (e.get("abstract-type") or "").replace("-", " ")
            name = text_of(_child(e, "title")) or (kind.capitalize() or "Abstract")
            c.section(e, [name])
    for part in ("body", "back"):
        for e in elements:
            if _local(e.tag) == part:
                for sec in e:
                    if _local(sec.tag) in REFERENCES:
                        continue
                    if _local(sec.tag) in ("p", "list", "disp-formula"):
                        c.paragraph("Main text", sec)
                    elif _local(sec.tag) not in OUT_OF_LINE:
                        c.section(sec, [])
    for n, e in enumerate((e for e in elements if _local(e.tag) == "fig"), 1):
        c.caption(
            e, text_of(_child(e, "label")).rstrip(".:") or f"Figure ({n})", "legend"
        )
    tables = (e for e in elements if _local(e.tag) == "table-wrap")
    for n, e in enumerate(tables, 1):
        label = text_of(_child(e, "label")).rstrip(".:") or f"Table ({n})"
        c.caption(e, label, "caption")
        for tr in e.iter():
            if _local(tr.tag) == "tr":
                c.add(f"{label} rows", " ".join(t for x in tr if (t := text_of(x))))
    return c


def fill_in(
    paragraphs: list[dict], manuscript: ManuscriptText, equations: list[dict]
) -> int:
    """Put back the few characters the XML leaves out of a sentence that the
    PDF prints (``"∼50"`` for ``"50"``), and return how many sentences
    changed.

    Where the XML has a formula only as a picture (a paragraph's
    ``formulas``), the formula's text is put in from the PDF as well. A
    sentence with display equations' marks is filled in part by part. Each
    changed sentence or part is listed under ``from_pdf`` as the XML had it,
    and the places of later equations' marks in the paragraph move with the
    text. ``formulas`` is removed.
    """
    changed = 0
    for p in paragraphs:
        text, offset, was = p["text"], 0, []
        formulas, end = p.pop("formulas", []), 0
        for sentence in SENTENCE.split(p["text"]):
            found = manuscript.find(sentence, loose=True) or manuscript.find_split(
                sentence
            )
            # else the parts between display equations' marks, one by one
            pieces = (
                [sentence]
                if found
                else [x.strip() for x in EQUATION_MARK.sub("\0", sentence).split("\0")]
            )
            for s in pieces:
                if not s:
                    continue
                at = text.index(s, offset)
                offset = at + len(s)
                start = p["text"].index(s, end)
                end = start + len(s)
                if found or manuscript.find(s, loose=True):
                    continue
                here = [f - start for f in formulas if start <= f <= start + len(s)]
                new = manuscript.filled(s, here)
                if new is None:
                    continue
                grown = len(new) - len(s)
                for e in equations:
                    here = (e["section"], e["paragraph"]) == (
                        p["section"],
                        p["paragraph"],
                    )
                    if here and e["at"] is not None and e["at"] >= offset:
                        e["at"] += grown
                text = text[:at] + new + text[offset:]
                offset += grown
                was.append(s)
        if was:
            p["text"], p["from_pdf"] = text, was
            changed += len(was)
    return changed


def locate(paragraphs: list[dict], manuscript: ManuscriptText) -> None:
    """Add each paragraph's PDF pages, where in its text each page starts,
    and the sentences not found there.

    The pages are the ones the paragraph runs over, from its first; a
    sentence also printed elsewhere (a legend's sentence repeated in
    another legend) does not add that page.
    """
    for p in paragraphs:
        starts: list[list[int]] = []
        missing = []
        offset = 0
        for s in SENTENCE.split(p["text"]):
            at, offset = p["text"].index(s, offset), offset + len(s)
            found = manuscript.find(s, loose=True) or manuscript.find_split(s)
            if found:
                pieces = [(at, s, found)]
            else:  # place it by its runs of words the PDF has
                missing.append(s)
                pieces = [(at + i, run, f) for i, run, f in _runs(s, manuscript)]
            for at_piece, piece, found in pieces:
                # the piece's page: the one it is on from the last one on, at
                # most two on (past a page holding only a figure)
                later = [n for n in found if not starts or 0 <= n - starts[-1][1] <= 2]
                if later and (not starts or min(later) != starts[-1][1]):
                    starts.append([0 if not starts else at_piece, min(later)])
                turn = (
                    _next_page_starts(piece, starts[-1][1], manuscript)
                    if starts
                    else None
                )
                if turn is not None:
                    starts.append([at_piece + turn[0], turn[1]])
        p["pages"] = sorted({page for _, page in starts})
        if len(starts) > 1:
            p["page_starts"] = starts
        p["not_in_pdf"] = missing


def _runs(
    sentence: str, manuscript: ManuscriptText
) -> list[tuple[int, str, list[int]]]:
    """Runs of whole words, of at least :data:`RUN` characters, that make up
    ``sentence``, each with where it starts and the pages the PDF has it
    on; runs the PDF writes differently (a symbol, a formula) are left out."""
    out, start = [], None
    for m in re.finditer(r"\S+", sentence):
        start = m.start() if start is None else start
        if m.end() - start >= RUN or m.end() == len(sentence):
            run = sentence[start : m.end()]
            if found := manuscript.find(run, loose=True) or manuscript.find_split(run):
                out.append((start, run, found))
            start = None
    return out


RUN = 40
"""Characters in a run of words :func:`_runs` looks for."""


def _next_page_starts(
    sentence: str, page: int, manuscript: ManuscriptText
) -> tuple[int, int] | None:
    """Where in a sentence printed from ``page`` the next page starts, if it
    runs onto it, and that page: the earliest word from which the rest is on
    the next page, or the one after past a page holding only a figure."""
    words = [m.start() for m in re.finditer(r"\S+", sentence)]
    ending = next((i for i in reversed(words) if len(sentence) - i >= TAIL), None)
    if not ending:
        return None
    found = manuscript.find(sentence[ending:], loose=True)
    later = [n for n in found if page < n <= page + 2]
    if not later or page in found:
        return None
    to = min(later)
    cut = next(
        (i for i in words[1:] if to in manuscript.find(sentence[i:], loose=True)),
        ending,
    )
    return cut, to


TAIL = 15
"""Characters at a sentence's end looked for on the next page."""


# --- Route 2: the PDF only ---------------------------------------------------

EDGE = 3
"""Lines at the top and bottom of a page where running headers and footers
are looked for."""
LEGEND = re.compile(r"^(Figure|Fig\.|Table)\s+(\d+)\s*[.:|](?!\s*[a-z]{3,}\b)\s*")
"""A legend's label; not if a sentence goes on after it (``Figure 2. shows``)."""
SUPPLEMENT = re.compile(r"^Figure supplement\s+(\d+)\s*[.:|]\s*")
"""A figure supplement's title, listed under the figure's legend."""
ONLINE = re.compile(r"^The online version of this article\b")
"""The note before that list, which says where the supplements are."""
CONTINUED = re.compile(
    r"^(?:Figure|Fig\.|Table)\s+\d+\s+continued\b(.*)", re.IGNORECASE
)
"""A marker where a legend breaks across pages: ``"Figure 2 continued on next
page"`` under its first part, ``"Figure 2 continued"`` over the rest."""
ENDS_SENTENCE = re.compile(r"[.!?:][\"'”’)\]]*$")
STARTS_SENTENCE = re.compile(r"^[\"'“‘(\[]?[A-Z0-9]")
SPACED_HYPHEN = re.compile(r"(?<=\w)- +(?!(?:and|or|nor|to) )(?=\w)")
"""A hyphen inside a word that the PDF's text has a space after, as in
``"made- up"``; not one left hanging, as in ``"pre- and post-"``."""
SHORT = 0.85
"""Without indents or spacing to go by: a line shorter than this share of a
full line can end a paragraph."""
LEFT_OUT = {"references", "bibliography", "literaturecited"}
CITED = re.compile(r"[\d,–\-]+(?:, ?[\d–\-]+)*")
"""Citation numbers, as printed raised after a word: ``"12"``, ``"3–5, 9"``."""
GLYPHS = re.compile(r"(?:/gid\d+){3}")
"""Text in figure panels that the PDF stores as glyph numbers, not letters."""
UNREADABLE = "text in figures, stored as glyph numbers"
OTHER = "text in other type sizes (labels in figures, table cells, footnotes)"
NOTE = "notes under legends that say a figure has supplements online"
MARKER = "lines that say a legend is continued on another page"
WORDS = re.compile(r"^[A-Z0-9](?=.*[A-Za-z]{3})(?:[^=<>+]|< ?[A-Z][a-z][^=<>+]*>)*$")
"""Text that can be a heading: words, not a formula; words may be grouped in
angle brackets (``< Stimulus; Response >``)."""
OWN_SIZE = 2000
"""Characters a major section needs in one type size to have it as its own
body size."""
OWN_WIDTH = 0.3
"""A major section whose full lines are longer or shorter than the body's by
this share is set in its own width."""
REFERENCES = {"references", "bibliography", "literaturecited"}
SAME_SIZE = 0.4
"""Type sizes (points) this close count as the same; half a point apart
they differ, as Methods text and legends set in 8.5 and 8 points do."""
ALIGNED = 1.5
"""Left edges (points) this close count as the same."""
DROP_CAP = 2.5
"""A single letter this many times the next line's type size, beside it,
is a drop cap: the large first letter of a paragraph."""
HANGS = 100
"""How far (points) left of a column's edge a heading can hang."""
HEADING = 1.0
"""A heading in the body's type size is shorter than this share of a full
line."""
SPACED = 1.2
"""A gap between lines this many times the usual one starts a paragraph."""
MIRRORED = 30
"""How far (points) facing pages' margins can differ."""


@dataclass
class Line:
    """A printed line, with where and how it is printed."""

    text: str
    x: float
    """Left edge, in points from the left of the page."""
    y: float
    """Baseline, in points from the bottom of the page."""
    size: float
    """Type size of most of its characters."""
    hyphen: bool = False
    """Ends in a hyphen that belongs to the word, which the PDF's text
    marks with a space after it (``"made- "``), not one put in to break a
    word across lines."""
    font: str = ""
    """Font of most of its characters, without the PDF's subset tag."""
    lead: str = ""
    """Text at its start in one font, if another follows (as in a heading
    run in at the start of a paragraph); ``""`` if it is all in one font."""
    lead_font: str = ""
    rest_size: float = 0.0
    """Type size of most of the text after ``lead``; 0 if there is no lead."""
    cap: bool = False
    """Starts with a drop cap, the large first letter of a paragraph."""


def _page_lines(page) -> list[Line]:
    """A page's lines, in the order the PDF draws them.

    Pieces of text drawn one after another go on one line while their
    baselines are within half a type size, so subscripts and superscripts
    stay on their line. Figure text stored as glyph numbers goes on lines
    of its own. The space some PDFs put after a hyphen inside a word is
    taken out.
    """
    groups: list[list[tuple[str, float, float, float, str]]] = []

    def visit(text, cm, tm, font, size) -> None:
        text = text.replace("\n", "")
        if not text:
            return
        c = tm[2] * cm[0] + tm[3] * cm[2]
        d = tm[2] * cm[1] + tm[3] * cm[3]
        x = tm[4] * cm[0] + tm[5] * cm[2] + cm[4]
        y = tm[4] * cm[1] + tm[5] * cm[3] + cm[5]
        size = abs(size) * (c * c + d * d) ** 0.5
        name = _font_name(font)
        text = _symbols(text, name)
        last = groups[-1] if groups else None
        if (
            last
            and abs(last[0][2] - y) <= 0.5 * max(size, last[0][3])
            and ("/gid" in text) == ("/gid" in last[0][0])
        ):
            last.append((text, x, y, size, name))
        elif text.strip():
            groups.append([(text, x, y, size, name)])
        elif last:
            last.append((text, *last[-1][1:]))

    page.extract_text(visitor_text=visit)
    lines = []
    for pieces in groups:
        weight: Counter[float] = Counter()
        fonts: Counter[str] = Counter()
        for k, (text, _, y, size, name) in enumerate(pieces):
            n = len(text.strip())
            fonts[name] += n
            # pypdf runs text on in the same font into one piece, reported
            # at the first character's size and baseline: a subscript
            # followed by more of the sentence comes as one small piece.
            # Only its first word is in the small size.
            before = next(
                (
                    q
                    for q in reversed(pieces[:k])
                    if q[3] > size + SAME_SIZE and q[0].strip()
                ),
                None,
            )
            if before and abs(y - before[2]) > 0.1 * before[3] and " " in text.strip():
                small = len(text.strip().split()[0])
                weight[round(size, 1)] += small
                weight[round(before[3], 1)] += n - small
            else:
                weight[round(size, 1)] += n
        size = weight.most_common(1)[0][0]
        font = fonts.most_common(1)[0][0]
        main = max(pieces, key=lambda q: len(q[0].strip()) * (abs(q[3] - size) < 0.1))
        text = "".join(q[0] for q in pieces)
        hyphen = bool(re.search(r"\w- +$", text))
        text = SPACED_HYPHEN.sub("-", text.strip())
        x = min(q[1] for q in pieces if q[0].strip())
        first = next(q[4] for q in pieces if q[0].strip())
        lead, rest = "", None
        for k, q in enumerate(pieces):
            if q[4] != first and q[0].strip():
                rest = k
                break
            lead += q[0]
        rest_size = 0.0
        if rest is not None:
            after: Counter[float] = Counter()
            for q in pieces[rest:]:
                after[round(q[3], 1)] += len(q[0].strip())
            rest_size = after.most_common(1)[0][0]
        lead = SPACED_HYPHEN.sub("-", lead.strip()) if rest is not None else ""
        lines.append(Line(text, x, main[2], size, hyphen, font, lead, first, rest_size))
    return _drop_caps(lines)


def _drop_caps(lines: list[Line]) -> list[Line]:
    """Lines with each drop cap put back at the start of its paragraph.

    The large letter's baseline is level with the last line beside it, and
    the first line beside it is drawn next. The lines beside it are moved
    back to the letter's left edge, as the rest of the paragraph is.
    """
    out = list(lines)
    i = 0
    while i + 1 < len(out):
        cap, first = out[i], out[i + 1]
        if (
            len(cap.text) == 1
            and cap.text.isalpha()
            and cap.size > DROP_CAP * first.size
            and first.x > cap.x
            and cap.y < first.y < cap.y + cap.size
        ):
            out[i : i + 2] = [
                replace(first, text=cap.text + first.text, x=cap.x, cap=True)
            ]
            k = i + 1
            while k < len(out) and out[k].y >= cap.y - ALIGNED and out[k].x > cap.x:
                out[k] = replace(out[k], x=cap.x)
                k += 1
        i += 1
    return out


def read_lines(path: Path) -> list[list[Line]]:
    """The PDF's printed lines, page by page."""
    logging.getLogger("pypdf").setLevel(logging.ERROR)
    return [_page_lines(p) for p in PdfReader(path).pages]


@dataclass
class Layout:
    """How the body text is set: type size, columns, indent, line spacing."""

    size: float
    starts: list[float]
    """Left edges of the columns."""
    indent: float | None
    """How far a paragraph's first line is indented, if paragraphs are."""
    spacing: dict[float, float]
    """Usual gap between lines, by type size."""
    full: float
    """Characters in a full line of body text."""
    font: str = ""
    """The body text's font."""

    def aligned(self, x: float, also: float | None = None) -> str:
        """``"start"`` or ``"indent"`` if ``x`` is a column's left edge (or
        ``also``) or indented from one; otherwise ``""``."""
        starts = [*self.starts, *([also] if also is not None else [])]
        for s in starts:
            if abs(x - s) <= ALIGNED:
                return "start"
        if self.indent is not None:
            for s in starts:
                if abs(x - s - self.indent) <= ALIGNED:
                    return "indent"
        return ""

    def at_edge(self, x: float) -> bool:
        """Whether ``x`` is at a column's left edge, its indent, or out to
        the left of it, where a heading can start."""
        reach = (self.indent or 0) + ALIGNED
        return any(s - HANGS < x <= s + reach for s in self.starts)

    def heading(self, line: Line) -> bool:
        """Whether a line of body-sized text is a heading below the
        outline's levels: all in another font than the body's, at a
        column's edge, short, and not ending a sentence."""
        return bool(
            self.font
            and line.font != self.font
            and not line.lead
            and self.at_edge(line.x)
            and len(line.text) < HEADING * self.full
            and not ENDS_SENTENCE.search(line.text)
            and WORDS.match(line.text)
        )

    def raised(self, line: Line) -> bool:
        """Whether a line is a heading set in larger type than the body,
        in any font: at a column's edge, short, and not ending a sentence."""
        return bool(
            self.size + SAME_SIZE < line.size < 2 * self.size
            and self.at_edge(line.x)
            and len(line.text) < HEADING * self.full
            and not ENDS_SENTENCE.search(line.text)
            and WORDS.match(line.text)
        )

    def run_in(self, line: Line, before: str = "") -> str:
        """A heading run in at the start of a paragraph's first line: a few
        words in another font than the body's, ending in a full stop or
        colon, which may be in the body's font, and followed by the start of
        a sentence (``""`` if there is none); or ending in a dash, run
        straight into the sentence. ``before`` is the heading's first line,
        if it started on the line above."""
        lead = line.lead
        stop = re.match(r" ?[.:]", line.text[len(lead) :])
        if stop and line.text.startswith(lead) and lead[-1:].isalnum():
            lead += stop.group()
        if (
            self.font
            and lead
            and line.lead_font != self.font
            and self.at_edge(line.x)
            and len(f"{before} {lead}".split()) <= 10
            and re.search(r"\w ?[.:]$|\w—$", lead)
            and WORDS.match(f"{before} {lead}".strip())
            and line.text.startswith(lead)
            and STARTS_SENTENCE.match(line.text[len(lead) :].lstrip() or "A")
        ):
            return lead
        return ""

    def spaced(self, above: Line, line: Line, below: Line | None = None) -> bool:
        """Whether there is more space than usual between the two lines.

        Not if the line after makes up for it: then a raised exponent or a
        tall formula only moved the line's baseline.
        """
        usual = self.spacing.get(round(line.size))
        if usual is None:
            return False
        gap = above.y - line.y
        if below is not None and abs(above.y - below.y - 2 * usual) < 0.15 * usual:
            return False
        return SPACED * usual < gap < 4 * usual


def facing(pages: Sequence[Sequence[Line]]) -> list[list[Line]]:
    """The pages, with the odd pages' lines moved sideways to line up with
    the even pages', where facing pages have mirrored margins.

    The shift is the one that best lines up the left edges of the body-sized
    lines on the two sets of pages, if it lines up clearly more of them than
    no shift does.
    """
    weight: Counter[float] = Counter()
    for page in pages:
        for line in page:
            weight[round(line.size * 2) / 2] += len(line.text)
    size = weight.most_common(1)[0][0] if weight else 10.0
    edges: tuple[Counter[int], Counter[int]] = (Counter(), Counter())
    for p, page in enumerate(pages):
        for line in page:
            if abs(line.size - size) <= SAME_SIZE:
                edges[p % 2][round(line.x)] += 1

    def overlap(d: int) -> int:
        return sum(min(n, edges[1][x + d]) for x, n in edges[0].items())

    shift = max(range(-MIRRORED, MIRRORED + 1), key=lambda d: (overlap(d), -abs(d)))
    if not shift or overlap(shift) < 1.5 * overlap(0):
        return [list(page) for page in pages]
    return [
        [replace(ln, x=ln.x - shift) for ln in page] if p % 2 else list(page)
        for p, page in enumerate(pages)
    ]


def layout(pages: Sequence[Sequence[Line]], size: float | None = None) -> Layout:
    """How the body text is set, from what is most common; in type
    ``size``, if given, else the most common size."""
    if size is None:
        weight: Counter[float] = Counter()
        for page in pages:
            for line in page:
                weight[round(line.size * 2) / 2] += len(line.text)
        size = weight.most_common(1)[0][0] if weight else 10.0
    body = [ln for page in pages for ln in page if abs(ln.size - size) <= SAME_SIZE]
    edges = Counter(round(ln.x) for ln in body)
    enough = max(3, 0.03 * len(body))
    starts: list[float] = []
    for x, n in sorted(edges.items(), key=lambda e: -e[1]):
        if n >= enough and all(abs(x - s) > 40 for s in starts):
            starts.append(x)
    starts.sort()
    # indents, pooled over the columns and over neighbouring positions
    offsets: Counter[int] = Counter()
    for x, n in edges.items():
        below = [x - s for s in starts if 2 < x - s < 40]
        if below:
            offsets[min(below)] += n
    pooled = {o: offsets[o - 1] + offsets[o] + offsets[o + 1] for o in offsets}
    best = max(pooled, key=pooled.__getitem__, default=None)
    indent = None
    if best is not None and pooled[best] >= max(3, 0.02 * len(body)):
        near = {o: offsets[o] for o in (best - 1, best, best + 1)}
        indent = sum(o * n for o, n in near.items()) / pooled[best]
    gaps: dict[float, Counter[float]] = {}
    for page in pages:
        for above, line in pairwise(page):
            if (
                abs(above.size - line.size) <= SAME_SIZE
                and abs(above.x - line.x) <= ALIGNED
                and above.y > line.y
            ):
                gaps.setdefault(round(line.size), Counter())[
                    round(above.y - line.y, 1)
                ] += 1
    spacing = {s: c.most_common(1)[0][0] for s, c in gaps.items() if c}
    widths = [len(ln.text) for ln in body if len(ln.text) > 40]
    full = statistics.median(widths) if widths else 80
    fonts: Counter[str] = Counter()
    for ln in body:
        fonts[ln.font] += len(ln.text)
    font = fonts.most_common(1)[0][0] if fonts else ""
    return Layout(size, [float(s) for s in starts], indent, spacing, full, font)


def running_lines(pages: Sequence[str]) -> set[tuple[int, int]]:
    """(page index, line) of running headers, footers, and page numbers.

    A line near the top or bottom of a page counts if, with its digits and
    spaces ignored, it appears near the edge of at least half the pages (and
    at least three), or if it is only a number. A page number at either end
    is ignored too, since it moves from side to side on facing pages, and
    so are spaces, which some PDFs leave out on every other page
    (``"OPEN ACCESSArticle"``).
    """
    edges: dict[tuple[int, int], str] = {}
    for p, page in enumerate(pages):
        lines = page.splitlines()
        kept = [i for i, line in enumerate(lines) if line.strip()]
        for i in kept[:EDGE] + kept[-EDGE:]:
            key = re.sub(r"\s+", "", re.sub(r"\d+", "#", lines[i]))
            edges[(p, i)] = re.sub(r"^#(?=.)|(?<=.)#$", "", key)
    seen = Counter(key for _, key in {(p, key) for (p, _), key in edges.items()})
    common = max(3, (len(pages) + 1) // 2)
    return {at for at, key in edges.items() if seen[key] >= common or key == "#"}


# --- Display equations -------------------------------------------------------

EQUATION_NUMBER = re.compile(
    r"[(\[]\s*(?:Equation|Eq\.?)?\s*([A-Z]?\d{1,3}[a-z]?)\s*[)\]]\s*$"
)
"""An equation's number at the end of a line: ``"(3)"``, ``"[3]"``,
``"(A12)"``, ``"(Equation 3)"``. Narrower than
:data:`~rigoraudit.numbering.NUMBER`: read as numbers, values such as
``"(0.4)"`` at the end of a formula would cut it in two. What it reads is
checked for order (:mod:`rigoraudit.numbering`): ``"p(K4)"`` at the end of a
formula reads as a number too."""
MATHS = re.compile(r"[=<>≤≥≈∼±∑∫∏√∂∇]|\b(?:exp|log|ln|max|min|arg)\b|/C\d+")
"""A sign of a formula. ``"/C24"`` is a symbol the PDF stores as a glyph
number; what it stands for differs from font to font."""
TWO_WORDS = re.compile(r"[A-Za-z]{2,}\W+[A-Za-z]{2,}")
WORD = re.compile(r"[A-Za-z][a-z]+[.,:;]?")
"""A line of one word, such as the end of a sentence before an equation."""
OPERATOR = re.compile(r"[-+−=<>≤≥≈∼±×/]")
"""A sign that, in a short line, makes it part of a formula."""
GOES_ON = re.compile(r"\s*[-+−=<>≤≥≈×·]")
"""A row of an equation that goes on from the row above."""
ENDS_TEXT = re.compile(r"[A-Za-z].*[.?:][\"'”’)\]]*$")
"""A short line of text that ends a sentence (not ``"!"``, which in a
formula is often a symbol the PDF gives wrongly), or leads into a display
with ``":"``, even if it has maths in it (``"(0 < x < 1):"``)."""
LIST_ITEM = re.compile(
    r"(?:\d{1,2}[.)]|\(?[a-z ivx]{1,4}\)|[•–-])\s+[A-Za-z]{2,}\W+[A-Za-z]{2,}"
)
"""The start of an item in a list: a marker, then words (``"2. the line
is"``, ``"(b) the dot"``, ``"• the dot"``)."""
PROSE = re.compile(r"\b(?!(?:exp|log|max|min|arg|sin|cos|tan)\b)[A-Za-z]{3,}")
PROSE_WORDS = 8
"""Words a line at least a full line long needs to be text wherever it
starts (a legend set in from the column, say): no display is so wordy."""
LIST_INDENT = 3
"""How far (in ems of the body text) an item in a list can be set in from
a column's edge."""
EQUATIONS = "display equations (listed in equations.json)"
ROW_GAP = 0.5
"""Space (a share of the usual gap between lines) between two rows of a
display: less, and they are one row."""
ASIDE = 0.3
"""Extra space (a share of the usual gap between lines) that sets an
equation without a number apart from the text around it."""
ROOM = 1.6
"""Space (in the usual gaps between lines of their size) two lines of text
need between them for a display: bits between two closer lines are maths
in the text (a root sign set high in a legend, say)."""
CHAR = 0.5
"""A character's width, roughly, in ems: for where a line ends."""
BIT = 5
"""Characters in a bit of maths (a root sign, a subscript) the PDF draws
as a line of its own, in the middle of a line of text."""
TEXT_SIZE = 2000
"""Characters a type size needs at a column's edge to count as a size
body text is set in."""


@dataclass
class Equation:
    """A display equation: lines set apart from the text, between its
    lines, with a formula or a number."""

    page: int
    lines: list[int]
    """Its lines' indices on the page."""
    number: str | None
    """As printed, without brackets (``"A12"``), if it has one (see
    :mod:`rigoraudit.numbering`)."""
    text: str
    """Its lines' text, in the order the PDF draws them: a rough guide only,
    since a formula's layout is lost (and an equation set as a picture has
    no text but its number)."""
    box: tuple[float, float, float, float]
    """Where it is: left, bottom, right, top, in points from the page's
    bottom left; the space between the lines of text above and below it, in
    its column."""
    section: str = ""
    paragraph: int | None = None
    """The paragraph it is set in (or after), if the paragraphs are cut
    from the PDF."""
    at: int | None = None
    """Where in that paragraph's text it is."""
    read: str | None = None
    """The number read from the PDF's text, before it is checked."""
    key: str = ""
    """Its number, or for one without, a key such as ``"p22@233"``
    (:mod:`rigoraudit.numbering`)."""
    note: str = ""
    """Why its number is not the one read, if it is not."""
    size: float = 0.0
    """The type size most of its characters are set in, in points."""
    down: float | None = None
    """How far its top is below the top of its page, in points: where it is,
    for a key that stays put when equations above it are found or lost."""


def _whole_lines(page: Sequence[Line], columns: Sequence[float] = ()) -> list[str]:
    """Each line's text with the pieces drawn next to it on its baseline
    (and close to it, in its column: not past the next of ``columns``), over
    any bits of maths (:data:`BIT`) between: a line of text a formula cuts
    in two, whole."""
    out = []
    for i, ln in enumerate(page):

        def same(k: int, ln: Line = ln) -> bool:
            return abs(page[k].y - ln.y) < 1

        lo = i
        while lo > 0 and (same(lo - 1) or len(page[lo - 1].text) <= BIT):
            lo -= 1
        hi = i
        while hi + 1 < len(page) and (same(hi + 1) or len(page[hi + 1].text) <= BIT):
            hi += 1
        pieces = sorted(
            (page[k] for k in range(lo, hi + 1) if same(k)), key=lambda p: p.x
        )
        # from the line's own piece out, while the gaps are small
        at = pieces.index(ln)
        start, end = at, at
        while start > 0 and _near(pieces[start - 1 : start + 1], columns):
            start -= 1
        while end + 1 < len(pieces) and _near(pieces[start : end + 2], columns):
            end += 1
        out.append(" ".join(p.text for p in pieces[start : end + 1]))
    return out


def _near(pieces: Sequence[Line], columns: Sequence[float]) -> bool:
    """Whether the last of ``pieces`` (left to right) starts within a few
    ems of where the others (roughly) reach, in the same column."""
    *left, right = pieces
    reach = max(p.x + CHAR * p.size * len(p.text) for p in left)
    return right.x - reach < 3 * max(p.size for p in pieces) and not any(
        left[0].x + ALIGNED < c <= right.x + ALIGNED for c in columns
    )


def display_equations(
    pages: Sequence[Sequence[Line]],
    style: Layout,
    skip: set[tuple[int, int]] = frozenset(),
    width: float = 612,
    height: float = 792,
) -> list[Equation]:
    """Display equations: runs of lines between lines of text that hold a
    formula or an equation's number.

    A line of text is at a column's edge (or indented, or starts an item
    in a list a little in from it: :data:`LIST_ITEM`, :data:`LIST_INDENT`,
    or is long and wordy, with the rest of its line if a formula cuts it
    in two: :data:`PROSE_WORDS`, :func:`_whole_lines`; or ends a sentence where a
    wordy line just above it starts), has two words (and
    no maths sign, if short), is one word, or ends a sentence, and is in a type size text is set in or nearly a full
    line long; a number at its end makes it an equation's unless it is
    nearly a full line long (as in ``"…and (2)"``). The lines in ``skip``
    (running heads, headings) are neither. Bits of a run on the baseline of
    the text just above or below it are a formula in the line, not a
    display; so are bits between two lines of text too close for a display
    (:data:`ROOM`). A run is cut into equations by its rows (:func:`rows`,
    :func:`_equations`); a run with no number is kept only if it has a
    formula and some extra space between it and the text. ``width`` is the
    page's, for the box of an equation in the last column; ``height`` too,
    for how far down the page each is.
    """
    chars: Counter[float] = Counter()
    for page in pages:
        for ln in page:
            if style.aligned(ln.x) == "start":
                chars[round(ln.size, 1)] += len(ln.text)
    sizes = [style.size, *(s for s, n in chars.items() if n >= TEXT_SIZE)]
    usual = style.spacing.get(round(style.size), 1.2 * style.size)

    def page_columns(page: Sequence[Line]) -> list[float]:
        # edges three full lines of text start at
        full = Counter(
            s
            for ln in page
            for s in style.starts
            if abs(ln.x - s) <= ALIGNED and len(ln.text) >= 0.5 * style.full
        )
        return [s for s in style.starts if full[s] >= 3]

    on_page = [page_columns(page) for page in pages]
    whole = {
        id(ln): t
        for page, columns in zip(pages, on_page, strict=True)
        for ln, t in zip(page, _whole_lines(page, columns), strict=True)
    }

    def wordy(ln: Line) -> bool:
        t = whole.get(id(ln), ln.text)
        return len(t) >= style.full and len(PROSE.findall(t)) >= PROSE_WORDS

    def text(ln: Line) -> bool:
        item = bool(LIST_ITEM.match(ln.text)) and any(
            s - ALIGNED <= ln.x <= s + LIST_INDENT * style.size for s in style.starts
        )
        return (
            (style.aligned(ln.x) != "" or item or wordy(ln))
            and "/gid" not in ln.text
            and (
                not EQUATION_NUMBER.search(ln.text) or len(ln.text) >= 0.6 * style.full
            )
            and (
                any(abs(ln.size - s) <= SAME_SIZE for s in sizes)
                or len(ln.text) >= 0.5 * style.full
            )
            and bool(
                TWO_WORDS.search(ln.text)
                and (len(ln.text) >= 0.5 * style.full or not OPERATOR.search(ln.text))
                or ENDS_TEXT.search(ln.text)
                or WORD.fullmatch(ln.text)
                or item
            )
        )

    def column(columns: list[float], xs: list[float]) -> tuple[float, float]:
        left = max((s for s in columns if s <= min(xs) + ALIGNED), default=0)
        right = min((s for s in columns if s > max(xs) + ALIGNED), default=width)
        return left, right

    out: list[Equation] = []
    for p, page in enumerate(pages):
        free = [(p, i) not in skip and not text(ln) for i, ln in enumerate(page)]
        # the short last line of a wordy run (a legend set in from the
        # column), where that line starts, ending its sentence
        for i in range(1, len(page)):
            ln, prev = page[i], page[i - 1]
            if (
                free[i]
                and not free[i - 1]
                and wordy(prev)
                and abs(ln.x - prev.x) <= ALIGNED
                and abs(ln.size - prev.size) <= SAME_SIZE
                and ENDS_TEXT.search(ln.text)
            ):
                free[i] = False
        columns = on_page[p]
        # each line of text on the page: its baseline, where it starts and
        # (roughly) ends, short of the next column, and its size
        spans = [
            (
                ln.y,
                ln.x,
                min(
                    ln.x + CHAR * ln.size * len(ln.text),
                    min((c for c in columns if c > ln.x + ALIGNED), default=width),
                ),
                ln.size,
            )
            for i, ln in enumerate(page)
            if not free[i] and (p, i) not in skip
        ]

        def tucked(ln: Line, spans: list = spans) -> bool:
            over = [
                (y, size)
                for y, left, right, size in spans
                if left - ln.size <= ln.x <= right + ln.size
            ]
            above = min((o for o in over if o[0] > ln.y + 1), default=None)
            below = max((o for o in over if o[0] <= ln.y + 1), default=None)
            return (
                above is not None
                and below is not None
                and above[0] - below[0]
                < ROOM * style.spacing.get(round(above[1]), 1.2 * above[1])
            )

        i = 0
        while i < len(page):
            if not free[i]:
                i += 1
                continue
            j = i
            while j + 1 < len(page) and free[j + 1]:
                j += 1
            above = page[i - 1] if i > 0 and text(page[i - 1]) else None
            below = page[j + 1] if j + 1 < len(page) and text(page[j + 1]) else None
            run = [
                k
                for k in range(i, j + 1)
                if "/gid" not in page[k].text
                and not any(
                    n is not None and abs(page[k].y - n.y) < 0.6 * n.size
                    for n in (above, below)
                )
            ]
            i = j + 1
            if (
                not run
                or (above is None and below is None)
                or all(tucked(page[k]) for k in run)
            ):
                continue
            if not any(EQUATION_NUMBER.search(page[k].text) for k in run):
                top = max(page[k].y + page[k].size for k in run)
                bottom = min(page[k].y for k in run)
                apart = (above is not None and above.y - top > ASIDE * usual) or (
                    below is not None and bottom - below.y - below.size > ASIDE * usual
                )
                if not apart or not any(MATHS.search(page[k].text) for k in run):
                    continue
            groups = _equations(page, rows(page, run, usual))
            # each fills the space between the text above and below it,
            # split halfway between its neighbours
            tops = [max(page[k].y + page[k].size for k in g) for _, g in groups]
            bottoms = [
                min(page[k].y - 0.25 * page[k].size for k in g) for _, g in groups
            ]
            for n, (number, lines) in enumerate(groups):
                top = (
                    (bottoms[n - 1] + tops[n]) / 2
                    if n
                    else above.y - 0.25 * above.size
                    if above is not None
                    else tops[0] + usual
                )
                bottom = (
                    (bottoms[n] + tops[n + 1]) / 2
                    if n + 1 < len(groups)
                    else below.y + 0.8 * below.size
                    if below is not None
                    else bottoms[n] - usual
                )
                # the text drawn before or after it may not be printed above
                # or below it
                top, bottom = max(top, tops[n]), min(bottom, bottoms[n])
                left, right = column(columns, [page[k].x for k in lines])
                sizes: Counter[float] = Counter()
                for k in lines:
                    sizes[page[k].size] += len(page[k].text)
                out.append(
                    Equation(
                        p + 1,
                        lines,
                        number,
                        " ".join(page[k].text for k in lines),
                        (left, bottom, right, top),
                        size=sizes.most_common(1)[0][0],
                        down=height - tops[n],
                    )
                )
    return out


def rows(page: Sequence[Line], run: list[int], usual: float) -> list[list[int]]:
    """A run's lines in rows, top to bottom: lines whose height overlaps,
    or nearly (as the parts of a fraction do)."""
    out: list[list[int]] = []
    low = 0.0
    for k in sorted(run, key=lambda k: -(page[k].y + page[k].size)):
        line = page[k]
        if not out or line.y + line.size < low - ROW_GAP * usual:
            out.append([])
            low = line.y
        out[-1].append(k)
        low = min(low, line.y - 0.25 * line.size)
    return out


def _equations(
    page: Sequence[Line], rows: list[list[int]]
) -> list[tuple[str | None, list[int]]]:
    """Rows made into equations, top to bottom, each with its number.

    A row with several numbers is first split, each line going with the
    nearest. A row goes with the equation above it if it goes on from it (it starts
    with ``"+"`` or ``"="``, say) and they do not both have a number, if it
    has neither a formula nor a number, or if it is only a number and the
    equation above has none. Equations with neither are left out.
    """
    split: list[list[int]] = []
    for row in rows:
        # equations set close together, one row: each line goes with the
        # nearest number
        numbers = {
            page[k].y: m.group(1)
            for k in row
            if (m := EQUATION_NUMBER.search(page[k].text))
        }
        if len(set(numbers.values())) < 2:
            split.append(row)
            continue
        parts: dict[float, list[int]] = {y: [] for y in sorted(numbers, reverse=True)}
        for k in row:
            parts[min(parts, key=lambda y: abs(y - page[k].y))].append(k)
        split.extend(part for part in parts.values() if part)
    out: list[tuple[str | None, list[int]]] = []
    for row in split:
        texts = [page[k].text for k in row]
        number = next(
            (m.group(1) for t in texts if (m := EQUATION_NUMBER.search(t))), None
        )
        first = page[min(row, key=lambda k: page[k].x)].text
        only_number = all(EQUATION_NUMBER.match(t.strip()) for t in texts)
        if out and (
            (GOES_ON.match(first) and not (number and out[-1][0]))
            or not (number or any(MATHS.search(t) for t in texts))
            or (only_number and out[-1][0] is None)
        ):
            above, lines = out[-1]
            out[-1] = (above or number, lines + row)
        else:
            out.append((number, list(row)))
    return [
        (n, lines)
        for n, lines in out
        if n or any(MATHS.search(page[k].text) for k in lines)
    ]


def find_equations(
    printed: Sequence[Sequence[Line]], width: float, height: float = 792
) -> list[Equation]:
    """A PDF's display equations (:func:`display_equations`), from its
    printed lines (:func:`read_lines`) and its pages' width and height,
    numbered (:func:`number_equations`)."""
    pages = facing(printed)
    texts = ["\n".join(ln.text for ln in page) for page in pages]
    found = display_equations(pages, layout(pages), running_lines(texts), width, height)
    for e in found:
        e.read = e.number
    number_equations(found)
    return found


def number_equations(
    equations: Sequence[Equation],
    corrections: Mapping[str, str | None] = {},
) -> None:
    """Give each equation its number and key from the number read for it,
    checked for order, and the auditor's ``corrections``
    (:func:`rigoraudit.numbering.settle`)."""
    items = [numbering.Item(e.page, e.read, down=e.down) for e in equations]
    for e, n in zip(equations, numbering.settle(items, corrections), strict=True):
        e.number, e.key, e.note = n.number, n.key, n.note


def number_records(
    records: Sequence[dict],
    corrections: Mapping[str, str | None] = {},
) -> None:
    """:func:`number_equations` for equations as ``equations.json`` lists
    them; a number from the publisher's XML (``"trusted"``) is not checked
    for order."""
    items = [
        numbering.Item(
            r["page"],
            r.get("read", r["number"]),
            bool(r.get("trusted")),
            r.get("down"),
        )
        for r in records
    ]
    for r, n in zip(records, numbering.settle(items, corrections), strict=True):
        r["number"], r["key"], r["note"] = n.number, n.key, n.note


def record(e: Equation) -> dict:
    """An equation as ``equations.json`` lists it."""
    return {
        "page": e.page,
        "number": e.number,
        "key": e.key,
        "read": e.read,
        "note": e.note,
        "section": e.section,
        "paragraph": e.paragraph,
        "at": e.at,
        "text": e.text,
        "box": [round(v, 1) for v in e.box],
        "size": round(e.size, 1),
        "down": round(e.down) if e.down is not None else None,
        "picture": None,
    }


ALIKE = 0.6
"""How alike (:func:`_alike`) an equation in the XML and one found in the
PDF must be to be paired by their text."""


def _alike(a: str, b: str) -> float:
    """How alike two equations' texts are, 0 to 1: the letters and digits
    they share, in any order (a formula's layout in a PDF's text is lost)."""
    ca, cb = Counter(c for c in a if c.isalnum()), Counter(c for c in b if c.isalnum())
    total = sum(ca.values()) + sum(cb.values())
    return 2 * sum((ca & cb).values()) / total if total else 0.0


def _align(listed: Sequence[dict], found: Sequence[Equation]) -> list[tuple]:
    """Pairs of the XML's and the PDF's equations, in order, that are most
    alike in all (each at least :data:`ALIKE`), skipping those in either
    with no partner."""
    n, m = len(listed), len(found)
    alike = [[_alike(r.get("text", ""), e.text) for e in found] for r in listed]
    best = [[0.0] * (m + 1) for _ in range(n + 1)]
    for i in range(n - 1, -1, -1):
        for j in range(m - 1, -1, -1):
            best[i][j] = max(best[i + 1][j], best[i][j + 1])
            if alike[i][j] >= ALIKE:
                best[i][j] = max(best[i][j], alike[i][j] + best[i + 1][j + 1])
    out, i, j = [], 0, 0
    while i < n and j < m:
        if alike[i][j] >= ALIKE and best[i][j] == alike[i][j] + best[i + 1][j + 1]:
            out.append((listed[i], found[j]))
            i, j = i + 1, j + 1
        elif best[i][j] == best[i + 1][j]:
            i += 1
        else:
            j += 1
    return out


def match_equations(listed: Sequence[dict], found: Sequence[Equation]) -> list[dict]:
    """The publisher's equations (:func:`jats_equations`), each with the page
    and box of the one found in the PDF with its number.

    Equations without a number are paired in order, between the same two
    numbered ones, where the XML and the PDF have as many; if the XML
    numbers none, all are paired in order, if there are as many. Where the
    counts differ (an equation not found, or something found that is not
    one), they are paired by their text (:func:`_align`). A row the XML sets
    apart that goes on from the one above (it starts with ``"+"``, say) is
    given that one's place. The rest have no page or box.
    """

    def between(items: Sequence, number) -> dict:
        out: dict[str | None, list] = {}
        last = None
        for item in items:
            if number(item):
                last = number(item)
            else:
                out.setdefault(last, []).append(item)
        return out

    numbered: dict[str, Equation] = {}
    for e in found:
        if e.number:
            numbered.setdefault(e.number, e)
    # an XML that numbers no equation is paired with the PDF in order
    uses_numbers = any(r["number"] for r in listed)
    printed = between(found, lambda e: e.number if uses_numbers else None)
    paired: dict[int, Equation] = {}
    for last, items in between(listed, lambda r: r["number"]).items():
        here = printed.get(last, [])
        pairs = (
            zip(items, here, strict=True)
            if len(here) == len(items)
            else _align(items, here)
        )
        paired.update((id(r), e) for r, e in pairs)
    out = []
    e = None
    for r in listed:
        # a row the XML sets apart that goes on from the equation above
        # ("+ b") is printed as part of it
        goes_on = e if not r["number"] and GOES_ON.match(r.get("text", "")) else None
        e = numbered.get(r["number"]) if r["number"] else paired.get(id(r))
        e = e or goes_on
        out.append(
            {
                "page": e.page if e else None,
                **r,
                "box": record(e)["box"] if e else None,
                "size": record(e)["size"] if e else None,
                "down": record(e)["down"] if e else None,
                "picture": None,
            }
        )
    return out


def draw_equations(folder: Path, pdf: Path, records: Sequence[dict]) -> None:
    """Write a picture of each equation with a box, as printed, into
    ``folder``'s ``equations/`` folder (``001.png`` for the first listed),
    replacing any there, and give each its picture's path (or ``None``)."""
    out = folder / PICTURES.name
    out.mkdir(parents=True, exist_ok=True)
    for old in out.glob("*.png"):
        old.unlink()
    placed = [r for r in records if r["box"]]
    drawn = pictures.draw(pdf, [(r["page"], tuple(r["box"])) for r in placed])
    images = dict(zip(map(id, placed), drawn, strict=True))
    for n, r in enumerate(records, 1):
        r["picture"] = None
        if id(r) in images:
            (out / f"{n:03d}.png").write_bytes(images[id(r)])
            r["picture"] = f"{PICTURES.name}/{n:03d}.png"


def numbering_note(records: Sequence[dict], corrections: numbering.Corrections) -> str:
    """What to check in the listed equations' numbers: numbers read but out
    of order, gaps in the sequence, and corrections that name no equation;
    ``""`` if none."""
    out = []
    rejected = sum(r.get("note", "").startswith("Read ") for r in records)
    if rejected:
        out.append(
            f"{plural(rejected, 'number')} read from the PDF "
            f"{'were' if rejected != 1 else 'was'} out of order and not used "
            "(each says so in its note)."
        )
    gaps = numbering.gaps([r["number"] for r in records])
    if gaps:
        out.append(f"Missing from the sequence: {'; '.join(gaps)}.")
    items = [
        numbering.Item(r["page"], r.get("read"), down=r.get("down")) for r in records
    ]
    if unused := numbering.unused(items, corrections):
        out.append(
            f"{numbering.CORRECTIONS} names equations not listed: {'; '.join(unused)}."
        )
    if out:
        out.append(
            f"Where a number is wrong, give the printed one in {numbering.CORRECTIONS}."
        )
    return " ".join(out)


def write_equations(folder: Path, records: Sequence[dict]) -> None:
    """Write ``equations.json`` into ``folder``."""
    (folder / EQUATIONS_FILE.name).write_text(
        json.dumps(list(records), indent=1, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _heading_lines(
    sections: Sections, lines: list[list[str]]
) -> tuple[dict, dict[tuple[int, int], int]]:
    """(page index, line) of each heading's lines, mapped to its place; and
    of a run-in heading's last line, mapped to where the paragraph's text
    starts in it."""
    out, cuts = {}, {}
    for page, start, place in sections.headings:
        title = sections.majors[place.major]
        if place.sub:
            title = sections.subsections[place.major][place.sub - 1]
        target, joined, p = heading_key(title), "", page - 1
        for i in range(start, min(start + 4, len(lines[p]))):
            line = lines[p][i]
            # letters the heading's numbering takes, on its first line
            skip = len(compact(line)) - len(heading_key(line)) if not joined else 0
            joined += heading_key(line) if not joined else compact(line)
            if joined and joined.startswith(target) and joined != target:
                need, k = skip + len(compact(line)) - (len(joined) - len(target)), 0
                while need > 0 and k < len(line):
                    need -= len(compact(line[k]))
                    k += 1
                cuts[(p, i)] = len(line) - len(line[k:].lstrip(" .:—"))
                break
            if not joined or not target.startswith(joined):
                break
            out[(p, i)] = place
            if joined == target:
                break
    return out, cuts


def _section_name(sections: Sections, place: Place) -> str:
    name = sections.title(place)
    if place.sub:
        name += SEPARATOR + sections.subsections[place.major][place.sub - 1]
    return name


def _join(para: dict, line: Line, page: int, text: str | None = None) -> None:
    """Add a line's text (or ``text``, part of it) to a paragraph, joining
    a word hyphenated across lines: the hyphen stays if it belongs to the
    word (:attr:`Line.hyphen`), and goes if it only breaks the word."""
    text = line.text if text is None else text
    if para["text"]:
        hyphenated = re.search(r"[A-Za-z]-$", para["text"])
        if hyphenated and para["hyphen"]:
            pass
        elif hyphenated and text[:1].islower():
            para["text"] = para["text"][:-1]
        else:
            para["text"] += " "
    if para["pages"] and page > max(para["pages"]):
        para.setdefault("page_starts", [[0, min(para["pages"])]])
        para["page_starts"].append([len(para["text"]), page])
    para["text"] += text
    para["hyphen"] = line.hyphen
    para["pages"].add(page)


def pdf_paragraphs(
    pages: Sequence[Sequence[Line]],
    outline: Sequence[Heading],
    equations: Sequence[Equation] = (),
) -> tuple[list[dict], Counter[str]]:
    """Paragraphs cut from the PDF's printed lines, and lines left out.

    The body text is in the type size most major sections are mostly set
    in (the most common size if no one size wins), or, in a major section
    set mostly in another size (Methods, in some journals), that size, with
    that section's own indent and line length. A body paragraph starts at
    an indented line, or after more space than usual between lines; in a
    PDF with neither, it starts after a line that ends a sentence and is
    clearly shorter than a full line. A paragraph cut off by a figure goes
    on after it.

    A legend (a line starting ``"Figure 3."`` or ``"Table 1:"``) is its own
    section, ``"Figure 3 legend"``, and takes the lines in its own type size
    and left edge, wherever they fall among the body's; its first sentence,
    the title, is its first paragraph. A ``"Figure supplement 1."`` line
    under it starts ``"Figure 3—figure supplement 1 legend"``, as in the
    publisher's XML; the note before such a list ("The online version of
    this article includes…") is left out. A legend that breaks across pages
    goes on in the same paragraph on the next page, and the lines that say so
    ("Figure 2 continued on next page") are left out. Lines in other type sizes are left
    out (and counted), and so is text before the first heading only if it
    is not body text either. Text before the first heading is in
    ``"Front matter"``, up to a paragraph that opens with a drop cap, which
    starts the ``"Main text"``; there, a note in another type size (an
    affiliation at a page's foot) between a paragraph and the rest of it
    does not end the paragraph.

    A heading the outline does not list is found by its font: a short line
    in the body's type size but all in another font (:meth:`Layout.heading`),
    or a few words in another font that start a paragraph and end in a full
    stop (:meth:`Layout.run_in`), or a short line in larger type, in any
    font (:meth:`Layout.raised`), with body text at a column's edge below
    it, or below its second line; a line on three or more pages (a label in
    the margin) is not one. It names a section below the outline's,
    ``"Results › Accuracy › Experiment 2"``, or, if it names a different
    main section (``"Discussion"``), a major section.

    Where a new sentence starts after a short line, or after a figure or
    page break, without the layout's sign of a new paragraph, the
    paragraph's ``doubts`` lists the sentence's offset in its text: a
    break the layout may hide (:mod:`rigoraudit.breaks`).

    The lines of ``equations`` (:func:`display_equations`) are left out
    too: a mark (``"[Equation 3]"``) stands in the paragraph where each is
    set, and each equation is given that paragraph.
    """
    pages = facing(pages)
    in_equation = {(e.page - 1, i): e for e in equations for i in e.lines}
    set_in: dict[int, dict] = {}  # id of an equation: the paragraph it is in
    texts = ["\n".join(ln.text for ln in page) for page in pages]
    sections = Sections(outline, texts)
    skip = running_lines(texts)
    headings, cuts = _heading_lines(sections, [t.splitlines() for t in texts])
    first = min(((p - 1, i) for p, i, _ in sections.headings), default=None)
    weight: dict[int, Counter[float]] = {}
    for p, page in enumerate(pages):
        for i, line in enumerate(page):
            if first is not None and (p, i) >= first:
                major = sections.at(p + 1, i).major
                weight.setdefault(major, Counter())[round(line.size, 1)] += len(
                    line.text
                )
    # the body size is the one most major sections are mostly set in, if
    # one size wins that vote: a long Methods section in smaller type, with
    # the legends, can outweigh the rest of the body
    votes = Counter(
        round(c.most_common(1)[0][0] * 2) / 2
        for c in weight.values()
        if c.most_common(1)[0][1] >= OWN_SIZE
    ).most_common(2)
    voted = (
        votes[0][0]
        if votes and (len(votes) == 1 or votes[0][1] > votes[1][1])
        else None
    )
    style = layout(pages, voted)
    by_layout = style.indent is not None or any(
        style.spaced(a, b)
        for page in pages
        for a, b in pairwise(page)
        if abs(a.size - style.size) <= SAME_SIZE
        and abs(b.size - style.size) <= SAME_SIZE
    )

    # a major section set in another type size (Methods, often) has its
    # own body size: the size of most of its text; so does a short piece of
    # back matter (a data availability statement, say) in smaller type
    own_size = {}
    for m, c in weight.items():
        size, n = c.most_common(1)[0]
        main = sum(k for s, k in c.items() if abs(s - style.size) <= SAME_SIZE)
        title = sections.title(Place(m, 0))
        back = standard_kind(title) == "Other" and compact(title) not in REFERENCES
        if (n >= OWN_SIZE or back) and main < 0.25 * c.total():
            own_size[m] = size

    # and is set its own way, as its lines show: its paragraphs may be
    # indented less, say
    def lines_of(m: int) -> list[list[Line]]:
        return [
            [
                ln
                for i, ln in enumerate(page)
                if (p, i) >= first and sections.at(p + 1, i).major == m
            ]
            for p, page in enumerate(pages)
        ]

    own_style = {m: layout(lines_of(m), size) for m, size in own_size.items()}
    # so is one in the body's size but set in its own width: Methods in one
    # wide column where the rest has two, say, so a heading there can be
    # longer than a full line of the rest
    for m, c in weight.items():
        main = sum(k for s, k in c.items() if abs(s - style.size) <= SAME_SIZE)
        if m in own_size or main < OWN_SIZE:
            continue
        own = layout(lines_of(m), style.size)
        if abs(own.full - style.full) > OWN_WIDTH * style.full:
            own_size[m], own_style[m] = style.size, own

    def body_sized(size: float, place: Place | None) -> bool:
        local = own_size.get(place.major) if place is not None else None
        return any(
            abs(size - s) <= SAME_SIZE for s in (style.size, local) if s is not None
        )

    # a heading in larger type: not a line on many pages (a label in the
    # margin), and followed, below it, by body text at a column's edge,
    # perhaps after its own second line (not by labels in a figure)
    repeated = {
        t
        for t, n in Counter(
            t for page in pages for t in {compact(ln.text) for ln in page}
        ).items()
        if n >= 3
    }

    def opens(page: Sequence[Line], i: int, place: Place | None) -> bool:
        for j in (i + 1, i + 2):
            if j >= len(page) or page[j].y >= page[j - 1].y:
                return False
            if body_sized(page[j].size, place) and style.aligned(page[j].x):
                return True
            if abs(page[j].size - page[i].size) > SAME_SIZE or not style.aligned(
                page[j].x
            ):
                return False
        return False

    out: list[dict] = []
    left_out: Counter[str] = Counter()
    body: dict | None = None  # the open body paragraph
    legend: dict | None = None  # the open legend paragraph
    above: dict[str, Line] = {}  # the line before, in the body and the legend
    previous: Line | None = None  # the line before on the page, whatever it was

    def start(section: str, where: str, **extra) -> dict:
        para = {"section": section, "body": where, "text": "", "pages": set(), **extra}
        out.append(para)
        return para

    # headings not in the outline, each with the section it was found in: a
    # major section the outline leaves out, and one below the outline's levels
    major, major_where = "", ""
    minor, minor_where = "", ""
    minor_line: Line | None = None  # the last line of a heading
    opening: Line | None = None  # a run-in heading's first line, on its own

    def named(where: str) -> str:
        name = major if major and major_where == where else where
        return name + SEPARATOR + minor if minor and minor_where == where else name

    carried: dict | None = None  # a legend said to go on over the page
    # a front-matter paragraph a change of type size cut off mid-sentence,
    # with its last line
    cut_short: tuple[dict, Line] | None = None
    row_chars = 0  # characters in the body's last row, over all its pieces
    for p, page in enumerate(pages):
        previous = None
        resumed, carried = carried, None
        for i, line in enumerate(page):
            text = line.text
            if (p, i) in headings:
                body = legend = None
                previous = line
                continue
            if (p, i) in skip or not text:
                continue
            cut = cuts.get((p, i))  # a run-in heading from the outline ends here
            if cut is not None:
                body = legend = None
                text = text[cut:]
            equation = in_equation.get((p, i))
            if equation is not None:
                if id(equation) not in set_in and body is not None:
                    set_in[id(equation)] = body
                    mark = equation_mark(equation.number)
                    _join(body, line, p + 1, mark)
                    body["hyphen"] = False
                    equation.at = len(body["text"]) - len(mark)
                left_out[EQUATIONS] += 1
                previous = line
                continue
            if GLYPHS.search(text):
                left_out[UNREADABLE] += 1
                continue
            front = first is None or (p, i) < first
            place = None if front else sections.at(p + 1, i)
            where = FRONT if place is None else _section_name(sections, place)
            if line.cap and front:  # the main text starts here, without a heading
                major, major_where, minor = "Main text", where, ""
            if compact(where.split(SEPARATOR)[0]) in LEFT_OUT:
                body = legend = None
                left_out[where] += 1
                continue
            before = opening.text if opening is not None and previous is opening else ""
            is_body = body_sized(line.size, place) or bool(
                # a run-in heading in smaller type, longer than the text after
                body_sized(line.rest_size, place)
                and (cut is not None or style.run_in(line, before))
            )
            below = page[i + 1] if i + 1 < len(page) else None
            marker = CONTINUED.match(text)
            if marker:
                if legend is not None and marker.group(1).strip():
                    carried = legend
                left_out[MARKER] += 1
                continue
            if (  # the rest of a legend from the page before
                legend is None
                and resumed is not None
                and abs(line.size - resumed["size"]) <= SAME_SIZE
                and style.aligned(line.x, resumed["x"])
            ):
                legend, resumed = resumed, None
                above["legend"] = previous = line
                _join(legend, line, p + 1)
                continue
            label = LEGEND.match(text)
            if label:
                table = label.group(1) == "Table"
                section = f"{'Table' if table else 'Figure'} {label.group(2)} "
                section += "caption" if table else "legend"
                legend = start(section, where, x=line.x, size=line.size, title=True)
                _join(legend, line, p + 1, text[label.end() :])
                above["legend"] = previous = line
                continue
            figure = legend and re.fullmatch(
                r"Figure (\d+)(?:—figure supplement \d+)? legend", legend["section"]
            )
            supplement = figure and SUPPLEMENT.match(text)
            if supplement:
                section = f"Figure {figure.group(1)}—figure supplement "
                section += f"{supplement.group(1)} legend"
                legend = start(section, where, x=line.x, size=line.size, title=True)
                _join(legend, line, p + 1, text[supplement.end() :])
                above["legend"] = previous = line
                continue
            if legend is not None and ONLINE.match(text):
                legend = start(
                    legend["section"],
                    where,
                    x=legend["x"],
                    size=legend["size"],
                    note=True,
                )  # never given text
                left_out[NOTE] += 1
                above["legend"] = previous = line
                continue
            if (  # set like the body: it ends where its lines stop running on
                legend is not None
                and body_sized(legend["size"], place)
                and not (
                    previous is above["legend"]
                    and style.aligned(line.x, legend["x"]) == "start"
                    and not style.spaced(previous, line, below)
                )
            ):
                legend = None
            if (
                legend is not None
                and abs(line.size - legend["size"]) <= SAME_SIZE
                and style.aligned(line.x, legend["x"])
            ):
                breaks = bool(
                    previous is above["legend"]
                    and style.spaced(previous, line, below)
                    and STARTS_SENTENCE.match(text)
                )
                if breaks:
                    legend = start(
                        legend["section"], where, x=legend["x"], size=legend["size"]
                    )
                if legend.get("note"):
                    left_out[NOTE] += 1
                else:
                    _join(legend, line, p + 1)
                above["legend"] = previous = line
                continue
            raised = (
                not is_body
                and not front
                and compact(text) not in repeated
                and (
                    style.raised(line)
                    and opens(page, i, place)
                    or (  # its second line
                        minor_line is not None
                        and previous is minor_line
                        and abs(line.size - minor_line.size) <= SAME_SIZE
                        and style.aligned(line.x) != ""
                    )
                )
            )
            if (  # citation numbers raised after the line before
                not is_body
                and body is not None
                and previous is not None
                and previous is above.get("body")
                and line.size < previous.size - SAME_SIZE
                and previous.y < line.y < previous.y + 0.8 * previous.size
                and line.x > previous.x
                and CITED.fullmatch(text.strip())
            ):
                body["text"] += text.strip()
                continue
            if (  # a run-in heading's first line, the rest starting the next
                not is_body
                and not front
                and below is not None
                and line.font != style.font
                and below.lead_font == line.font
                and body_sized(below.rest_size, place)
                and style.run_in(below, before=text)
            ):
                opening = previous = line
                continue
            if not is_body and not front and not raised:
                left_out[OTHER] += 1
                previous = line
                continue
            local = own_size.get(place.major) if place is not None else None
            here = style
            if local is not None and abs(line.size - local) <= SAME_SIZE:
                here = own_style[place.major]
            if not front and (raised or here.heading(line)):
                kind = standard_kind(text)
                if minor_line is not None and previous is minor_line:
                    minor += " " + text  # a heading on two lines
                elif kind and kind != standard_kind(named(where).split(SEPARATOR)[0]):
                    major, major_where, minor = text, where, ""
                else:
                    minor, minor_where = text, where
                body, minor_line, previous = None, line, line
                continue
            run_in = here.run_in(line, before) if not front and cut is None else ""
            if run_in:
                minor, minor_where = f"{before} {run_in[:-1]}".strip(), where
                body, text = None, text[len(run_in) :].lstrip()
            last = above.get("body")
            if body is None or body["body"] != where or line.cap:
                new = True
            elif by_layout:
                kind = here.aligned(line.x)
                # a symbol drawn above its line, such as a root sign, only
                # looks like a line of its own; the top of the next column
                # rises much further
                rises = (
                    previous is not None
                    and previous.y - 0.5 * line.size
                    < line.y
                    < previous.y + 2 * line.size
                )
                # a formula in the line can push it down, but a paragraph
                # does not end on a full line in the middle of a sentence,
                # even one read in pieces around the formula
                spaced = (
                    kind == "start"
                    and previous is last
                    and here.spaced(last, line, below)
                    and (
                        ENDS_SENTENCE.search(last.text) or row_chars < SHORT * here.full
                    )
                )
                # paragraphs set apart only by space show no gap at the top
                # of a page or column: there, a short line ending a sentence
                # ended one
                turned = (
                    here.indent is None
                    and kind == "start"
                    and line.y > last.y
                    and ENDS_SENTENCE.search(last.text)
                    and len(last.text) < SHORT * here.full
                    and STARTS_SENTENCE.match(text)
                )
                # rows that started at the same place, off the column's
                # edge, were a block set apart (an abstract, say)
                block_ends = (
                    spaced and here.aligned(above["row"].x) == "" and above["block"]
                )
                new = (
                    not rises
                    and kind == "indent"
                    or spaced
                    and here.aligned(above["row"].x) != ""
                    or turned
                    or block_ends
                )
                if block_ends and standard_kind(where) == "Abstract":
                    major, major_where, minor = "Main text", where, ""
                if front and abs(line.size - last.size) > SAME_SIZE:
                    new = True
            else:
                new = bool(
                    ENDS_SENTENCE.search(last.text)
                    and len(last.text) < SHORT * here.full
                    and STARTS_SENTENCE.match(text)
                )
            # a sentence that ends a short line, or the last line before a
            # figure or page break, may end a paragraph the layout hides
            if (
                not new
                and ENDS_SENTENCE.search(last.text)
                and STARTS_SENTENCE.match(text)
                and (previous is not last or len(last.text) < SHORT * here.full)
            ):
                body.setdefault("doubts", []).append(len(body["text"]) + 1)
            # in the front matter, a note in another type size (an
            # affiliation at the page's foot) can come between a paragraph
            # and the rest of it: a line in its size, at the column's edge,
            # going on with its sentence
            if (
                new
                and front
                and cut_short is not None
                and abs(line.size - cut_short[1].size) <= SAME_SIZE
                and here.aligned(line.x) == "start"
                and not STARTS_SENTENCE.match(text)
            ):
                new, body = False, cut_short[0]
            if new:
                if (
                    front
                    and body is not None
                    and last is not None
                    and body_sized(last.size, place)
                    and abs(line.size - last.size) > SAME_SIZE
                    and not ENDS_SENTENCE.search(last.text)
                ):
                    cut_short = (body, last)
                elif (
                    cut_short is not None
                    and abs(line.size - cut_short[1].size) <= SAME_SIZE
                ):
                    cut_short = None  # a new paragraph in its size: it ended
                body = start(named(where), where)
                run_in = RUN_IN.match(text) if front else None
                if run_in:
                    body["section"] = run_in.group(1).capitalize()
                    text = text[run_in.end() :]
            _join(body, line, p + 1, text)
            # the row's first line: text after a raised citation number is
            # a line of its own, on the same baseline
            if new or last is None or abs(last.y - line.y) > 0.5 * line.size:
                row = above.get("row")
                above["block"] = row is not None and abs(line.x - row.x) <= ALIGNED
                above["row"] = line
                row_chars = 0
            row_chars += len(line.text)
            above["body"] = previous = line
    for n in range(len(out) - 1, -1, -1):
        para = out[n]
        parts = SENTENCE.split(para["text"], maxsplit=1)
        if para.get("title") and len(parts) == 2:
            rest = {**para, "text": parts[1]}
            if "page_starts" in para:
                at = para["text"].index(parts[1], len(parts[0]))
                para["page_starts"], rest["page_starts"] = split_page_starts(
                    para["page_starts"], at
                )
            out.insert(n + 1, rest)
            para["text"] = parts[0]
    count: Counter[str] = Counter()
    kept = []
    for para in out:
        if not para["text"]:
            continue
        count[para["section"]] += 1
        para["paragraph"] = count[para["section"]]
        kept.append(
            {
                "section": para["section"],
                "paragraph": count[para["section"]],
                "text": para["text"],
                "pages": sorted(para["pages"]),
                **(
                    {"page_starts": para["page_starts"]}
                    if len(para.get("page_starts", ())) > 1
                    else {}
                ),
                "approximate": True,
                **({"doubts": para["doubts"]} if para.get("doubts") else {}),
            }
        )
    for e in equations:
        para = set_in.get(id(e))
        if para is not None:
            e.section, e.paragraph = para["section"], para.get("paragraph")
    return kept, left_out


# --- The step ----------------------------------------------------------------


@dataclass
class Result:
    route: str
    """``"xml"``, ``"pdf"``, or ``"grobid"``."""
    paragraphs: int
    not_found: int = 0
    """XML and GROBID routes: sentences not found in the PDF text layer."""
    filled: int = 0
    """XML route: sentences given characters the XML leaves out, from the
    PDF (:func:`fill_in`)."""
    legends_not_found: int = 0
    """XML route, with no supplement named: those sentences in figure
    legends."""
    left_out: dict[str, int] = field(default_factory=dict)
    """PDF route: lines left out, by section (the reference list) or
    :data:`UNREADABLE`."""
    xml: str | None = None
    grobid: str | None = None
    """The GROBID server asked."""
    grobid_failed: str | None = None
    """Why GROBID's paragraphs were not used, if it was asked."""
    unplaced: int = 0
    """GROBID route: paragraphs in :data:`~rigoraudit.grobid.UNPLACED`."""
    equations: int = 0
    """Display equations listed."""
    pictured: int = 0
    """Equations with a picture."""
    pictures_failed: str | None = None
    """Why the equations have no pictures, if they have none."""
    numbering: str = ""
    sections: list[str] = field(default_factory=list)
    """The paragraphs' major sections, in reading order, for the manifest's
    ``settings: scope``; figure legends are counted as one entry."""
    """What to check in the equations' numbers (:func:`numbering_note`)."""


def find_xml(manuscript: Path) -> Path | None:
    """The publisher's XML: the manuscript itself, or the one beside it."""
    if manuscript.suffix.lower() == ".xml":
        return manuscript
    found = sorted(manuscript.parent.glob("*.xml"))
    return found[0] if len(found) == 1 else None


def extract(
    workspace: Path,
    manuscript: str,
    server: str | None = None,
    supplement: str | None = None,
) -> Result:
    """Write the text layer, outline, and paragraphs for the workspace.

    ``manuscript`` is the manuscript's path in ``materials/``, as the
    manifest gives it; ``server`` is a GROBID server to read the PDF with
    when there is no publisher's XML; ``supplement`` is a separate PDF
    printing what the article's PDF leaves out (often the figure
    supplements), whose text is added to the text layer.
    """
    path = workspace / "materials" / manuscript
    xml = find_xml(path)
    pdf = path if path.suffix.lower() == ".pdf" else None
    folder = workspace / FOLDER
    fixes = numbering.read_corrections(workspace / numbering.CORRECTIONS)
    pages: list[str] = []
    outline: tuple[Heading, ...] = ()
    equations: list[Equation] = []
    if pdf is not None:
        pages, outline = read_pdf(pdf)
        more = None
        if supplement is not None:
            other = workspace / "materials" / supplement
            more = (other.name, read_pdf(other)[0])
        write_text_layer(folder, pages, outline, pdf.name, more)
        printed = read_lines(pdf)
        boxes = [p.mediabox for p in PdfReader(pdf).pages]
        width = max((float(b.width) for b in boxes), default=612)
        height = max((float(b.height) for b in boxes), default=792)
        equations = find_equations(printed, width, height)
        if xml is None:
            number_equations(equations, fixes)
    records = [record(e) for e in equations]
    if xml is not None:
        root = ET.parse(xml).getroot()
        paragraphs = jats_paragraphs(root)
        records = match_equations(jats_equations(root), equations)
        for r in records:
            r["read"], r["trusted"] = r["number"], True
        number_records(records, fixes)
        filled = 0
        if pages:
            text = read_text(workspace / TEXT)
            filled = fill_in(paragraphs, text, records)
            locate(paragraphs, text)
        for p in paragraphs:
            p.pop("formulas", None)
        result = Result(
            "xml",
            len(paragraphs),
            sum(len(p.get("not_in_pdf", [])) for p in paragraphs),
            legends_not_found=0
            if supplement
            else sum(
                len(p.get("not_in_pdf", []))
                for p in paragraphs
                if figure_number(p["section"]) is not None
            ),
            xml=xml.name,
            filled=filled,
        )
    elif pdf is None:
        raise ValueError(
            f"materials/{manuscript} is neither a PDF nor a publisher's XML file"
        )
    else:
        failed = None
        if server is not None:
            try:
                tei = grobid.request(pdf, server)
                root = ET.fromstring(tei)
            except READ_ERRORS as e:
                failed = f"{type(e).__name__}: {e}"
            else:
                folder.mkdir(parents=True, exist_ok=True)
                (folder / "grobid.tei.xml").write_bytes(tei)
                majors = tuple(Sections(outline, pages).majors)
                paragraphs = grobid.tei_paragraphs(root, majors)
                locate(paragraphs, read_text(workspace / TEXT))
                for p in paragraphs:
                    p["approximate"] = True
                result = Result(
                    "grobid",
                    len(paragraphs),
                    sum(len(p["not_in_pdf"]) for p in paragraphs),
                    grobid=server,
                    unplaced=sum(p["section"] == grobid.UNPLACED for p in paragraphs),
                )
        if server is None or failed is not None:
            paragraphs, left_out = pdf_paragraphs(printed, outline, equations)
            records = [record(e) for e in equations]
            result = Result(
                "pdf",
                len(paragraphs),
                left_out=dict(left_out),
                grobid=server,
                grobid_failed=failed,
            )
    folder.mkdir(parents=True, exist_ok=True)
    (workspace / PARAGRAPHS).write_text(
        json.dumps(paragraphs, indent=1, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    if pdf is not None and any(r["box"] for r in records):
        try:
            draw_equations(folder, pdf, records)
        except pictures.pdfium.PdfiumError as e:
            result.pictures_failed = str(e)
    write_equations(folder, records)
    result.numbering = numbering_note(records, fixes)
    result.sections = section_names(paragraphs)
    result.equations = len(records)
    result.pictured = sum(bool(r.get("picture")) for r in records)
    return result


def section_names(paragraphs: Sequence[Mapping]) -> list[str]:
    """The major sections of ``paragraphs`` in reading order (a subsection
    counts as its section), with all figure legends as one entry and all
    table parts as another."""
    names: list[str] = []
    counts: Counter[str] = Counter()
    for p in paragraphs:
        name = p["section"].split(SEPARATOR)[0].strip()
        kind = re.match(r"(Figure|Table) (?:[A-Z]\.)?\d", name)
        if kind:
            name = f"{kind.group(1)} …"
            counts[name] += 1
        if name not in names:
            names.append(name)
    return [
        f"{n} ({plural(counts[n], 'paragraph')})" if counts[n] else n for n in names
    ]


def describe(result: Result) -> str:
    """What the extract step did, for the user."""
    return _describe(result) + (
        " Sections, as settings › scope in the manifest names them: "
        + "; ".join(result.sections)
        + "."
        if result.sections
        else ""
    )


def _describe(result: Result) -> str:
    if result.route == "xml":
        text = (
            f"Wrote {result.paragraphs} paragraphs to {PARAGRAPHS}, taken from the "
            f"publisher's XML file ({result.xml})."
        )
        if result.filled:
            text += (
                f" {result.filled} sentences left out a few characters the PDF "
                "prints (such as a '∼' before a number, or a formula the XML has "
                "only as a picture); they were put in from the PDF, and each "
                "sentence as the XML had it is listed under from_pdf."
            )
        if result.not_found:
            text += (
                f" {result.not_found} sentences were not found in the PDF; they "
                "are listed under not_in_pdf. Usually that is a formula or "
                "symbol the two files write differently, but check them: quotes "
                "are checked against the PDF."
            )
        if result.legends_not_found:
            text += (
                f" {result.legends_not_found} of them are in figure legends. If "
                "the journal prints some legends (often the figure supplements') "
                "in a separate PDF, name it in the manifest (materials › "
                "manuscript › supplement) and run rigoraudit extract --replace."
            )
        return text + _equations_note(result)
    if result.route == "grobid":
        text = (
            f"Wrote {result.paragraphs} paragraphs to {PARAGRAPHS}, read from the "
            f"PDF by GROBID ({result.grobid})."
        )
        if result.not_found:
            text += (
                f" {result.not_found} sentences were not found in the PDF text; "
                "they are listed under not_in_pdf. Usually that is a formula or "
                "symbol GROBID wrote differently, or text it took from a figure."
            )
        if result.unplaced:
            text += (
                f" GROBID could not place {result.unplaced} paragraphs; they are "
                f'at the end, in "{grobid.UNPLACED}". Move any that belong in '
                "the paper's text (most are), and delete the rest."
            )
    else:
        text = f"Wrote {result.paragraphs} paragraphs to {PARAGRAPHS}, cut from the PDF text."
        if result.grobid_failed:
            text = (
                f"The GROBID server ({result.grobid}) did not answer "
                f"({result.grobid_failed}), so the tool read the PDF itself. " + text
            )
    text += (
        " There was no publisher's XML file beside the PDF, so where one "
        "paragraph ends and the next begins is a best guess. Open the "
        "file and fix any paragraph that was split or run together before the "
        "next step: claim IDs are built from paragraph numbers. Better still, "
        "look for the article's XML file (PubMed Central, PLOS, and bioRxiv "
        "have one for many papers; the user guide, docs/guide.md, says where): put it beside the PDF and run rigoraudit extract "
        "--replace, and the paragraphs will be exact."
    )
    for what, n in sorted(result.left_out.items()):
        what = (
            what
            if what in (UNREADABLE, OTHER, NOTE, MARKER, EQUATIONS)
            else f"the {what} section"
        )
        text += f" Left out {n} lines of {what}."
    return text + _equations_note(result)


def _equations_note(result: Result) -> str:
    if not result.equations:
        return ""
    source = "the publisher's XML" if result.route == "xml" else "the PDF"
    text = (
        f" Listed {result.equations} display equations from {source} in "
        f"{EQUATIONS_FILE}, each with its number and the paragraph it is set "
        'in, where a mark such as "[Equation 3]" stands for it. '
    )
    if result.pictured == result.equations:
        text += f"{PICTURES}/ has a picture of each as printed."
    elif result.pictured:
        text += (
            f"{PICTURES}/ has a picture of {result.pictured} of them as "
            "printed; the others were not found in the PDF."
        )
    elif result.pictures_failed:
        text += (
            f"Their pictures could not be drawn ({result.pictures_failed}); "
            "check equations against the printed pages."
        )
    else:
        text += "None was found in the PDF, so none has a picture."
    text += (
        " An equation's text in the list is a rough guide: check it against "
        "its picture."
    )
    return text + (f" {result.numbering}" if result.numbering else "")
