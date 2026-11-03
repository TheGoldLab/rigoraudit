# Copyright (c) 2026, Joshua I. Gold
# SPDX-License-Identifier: BSD-2-Clause
"""Independent checks of an audit record's quoted evidence against the materials.

The record builder takes quotes from its own working copies of the sources, so
a check at build time can only confirm the builder agrees with itself. These
checks go back to the materials instead:

- Manuscript quotes are searched for in the manuscript's text layer (one string
  per page), and the page each anchor states is confirmed.
- Code quotes are compared with the cited lines at the anchor's commit, read
  from git rather than the working tree, and must show the values they give.
- Data anchors are checked for file presence and, where known, checksum.
  The observation's statement may not cite a number its quote does not show.
  Values from a derivation are read back from its output by key, the output
  is checked against the current checksums of its inputs, and each value must
  appear in the quote the reader sees.
"""

from __future__ import annotations

import re
import unicodedata
from bisect import bisect_right
from collections.abc import Collection, Iterator, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from difflib import SequenceMatcher
from enum import StrEnum
from functools import cache
from itertools import pairwise
from pathlib import Path

from rigoraudit import codeindex
from rigoraudit import values as derivation_values
from rigoraudit.paragraphs import EQUATION_MARK
from rigoraudit.schema import (
    Anchor,
    AuditRecord,
    CodeAnchor,
    DataAnchor,
    ManuscriptAnchor,
    Value,
    same_value,
)
from rigoraudit.words import plural


class Outcome(StrEnum):
    """Result of checking one anchor."""

    VERIFIED = "verified"
    """Found as quoted (ignoring whitespace), at the stated location."""
    VERIFIED_NORMALIZED = "verified_normalized"
    """Found only after normalizing Unicode forms, dashes, and quote marks, or
    only as two parts split across a page break."""
    WRONG_PAGE = "wrong_page"
    """Found, but not on the page the anchor states."""
    MISMATCH = "mismatch"
    """Not found as quoted, or the cited file is missing or changed."""
    STALE = "stale"
    """A derivation's inputs have changed since it wrote its output."""
    UNCHECKED = "unchecked"
    """Nothing in the materials to check the quote against automatically."""


@dataclass(frozen=True)
class AnchorCheck:
    """The outcome of checking one anchor, with where it sits in the record."""

    location: str
    """Where the anchor is used, e.g. ``finding R2.1.c/quantity/sem code``."""
    kind: str
    outcome: Outcome
    detail: str
    quote: str


# --- Manuscript ---------------------------------------------------------------

_WHITESPACE = re.compile(r"\s+")
_DASHES = re.compile(r"[‐‑‒–—−]")
_HYPHENATION = re.compile(r"(?<=[^\W\d_])\s*-(?:\s+|(?=[^\W\d_]))")
"""A hyphen after a letter that ends a line or joins another letter.

Extraction can put a space before it ("perfor -\\nmance")."""
_QUOTE_MARKS = str.maketrans({"’": "'", "‘": "'", "“": '"', "”": '"'})
_LETTER_TILDE = re.compile(r"(?<=[^\W\d_])[~˜]")
"""A tilde typed after a letter as its accent ("S~" for S with a tilde)."""


def _normalize(text: str, *, loose: bool) -> str:
    """Remove whitespace; if ``loose``, also unify Unicode forms and hyphenation.

    Loose matching absorbs hyphenation in extracted PDF text ("accumu-\\nlation",
    "rule- based" vs "rule-based") but keeps minus signs and range dashes,
    so "−0.08" never matches "0.08". All dashes and minus signs compare equal.
    It also drops accents, which a PDF can place before their letter rather
    than after, and a tilde typed after a letter in their place; a tilde
    before a number ("~100") is kept.
    """
    if loose:
        text = _LETTER_TILDE.sub("", text)
        text = unicodedata.normalize("NFKD", text).translate(_QUOTE_MARKS)
        text = "".join(c for c in text if unicodedata.category(c) != "Mn")
        text = _HYPHENATION.sub("", _DASHES.sub("-", text))
    return _WHITESPACE.sub("", text)


EQUATION_GAP = 3000
"""Characters (whitespace removed) an equation's text can take in the text
layer, between the parts of a quote around its mark."""
MAX_EXTRA = 3
"""Characters (whitespace removed) found in only one of the quote and the
page that a mismatch's detail names, or :meth:`ManuscriptText.filled`
puts back, such as a ``"∼"`` the quote leaves out."""
ANCHOR = 15
"""Characters (whitespace removed) at a quote's start or end that
:meth:`ManuscriptText.filled` finds it by."""


def _occurrences(text: str, part: str, limit: int = 20) -> list[int]:
    """Where ``part`` is in ``text``: the first ``limit`` places."""
    out, i = [], text.find(part)
    while i >= 0 and len(out) < limit:
        out.append(i)
        i = text.find(part, i + 1)
    return out


def _put_in(quote: str, inserts: Sequence[tuple[int, str]]) -> str | None:
    """``quote`` with each ``(at, extra)`` put in before the character that
    gives its normalized text's character ``at``; a space follows ``extra``
    when it starts a word (``"point ˆθ is"``). ``None`` if a place cannot
    be told."""
    lengths = [len(_normalize(quote[:i], loose=True)) for i in range(len(quote) + 1)]
    out, last = [], 0
    for at, extra in inserts:
        o = next((i - 1 for i, n in enumerate(lengths) if n > at), None)
        if o is None or o < last:
            return None
        before = quote[o - 1] if o else " "
        space = " " if before.isspace() and quote[o].isalpha() else ""
        out += [quote[last:o], extra + space]
        last = o
    return "".join([*out, quote[last:]])


class ManuscriptText:
    """A manuscript's text layer, searchable with page numbers.

    ``pages[0]`` is page 1. A supplement's pages follow the article's, and
    ``files`` names the file each page is in when it is not the article's
    (``""``), so a page can be named as people look it up (:meth:`name`).
    """

    def __init__(self, pages: Sequence[str], files: Sequence[str] = ()) -> None:
        self._levels = {loose: self._join(pages, loose) for loose in (False, True)}
        self._files = [*files, *[""] * (len(pages) - len(files))]

    def name(self, page: int) -> str:
        """``"page 3"``, or ``"page 1 of figures.pdf"`` in a supplement."""
        return self.names([page])

    def names(self, pages: Collection[int]) -> str:
        """``"page 3, 5"``, with a supplement's pages numbered as in its file
        (``"page 3; page 1, 2 of figures.pdf"``)."""
        by_file: dict[str, list[int]] = {}
        for page in sorted(pages):
            file = self._files[page - 1] if 0 < page <= len(self._files) else ""
            first = self._files.index(file) if file else 0
            by_file.setdefault(file, []).append(page - first)
        return "; ".join(
            f"page {', '.join(map(str, ns))}" + (f" of {file}" if file else "")
            for file, ns in by_file.items()
        )

    @staticmethod
    def _join(pages: Sequence[str], loose: bool) -> tuple[str, list[int]]:
        parts = [_normalize(p, loose=loose) for p in pages]
        starts, offset = [], 0
        for part in parts:
            starts.append(offset)
            offset += len(part)
        return "".join(parts), starts

    def find(self, quote: str, *, loose: bool) -> list[int]:
        """Return the page number of every occurrence of ``quote``.

        Where the quote has an equation's mark (``"[Equation 3]"``), the
        equation is not compared: the parts before and after it must follow
        one another, with at most :data:`EQUATION_GAP` characters between.
        """
        text, starts = self._levels[loose]
        parts = [
            n for part in EQUATION_MARK.split(quote)[::2]
            if (n := _normalize(part, loose=loose))
        ]  # fmt: skip
        if not parts:
            return []
        pages, i = [], text.find(parts[0])
        while i >= 0:
            end = i + len(parts[0])
            for part in parts[1:]:
                j = text.find(part, end, end + EQUATION_GAP + len(part))
                if j < 0:
                    break
                end = j + len(part)
            else:
                pages.append(bisect_right(starts, i))
            i = text.find(parts[0], i + 1)
        return pages

    def find_split(self, quote: str, *, min_part: int = 10) -> list[int]:
        """Return pages where ``quote`` starts and continues on a later page.

        Running headers, footers, or body text can interrupt a quote at a page
        break, and a page that holds only a figure can come between its two
        parts, so the rest may be on the next page or the one after. Matches
        loosely; both parts must be at least ``min_part`` characters
        (whitespace removed).
        """
        text, starts = self._levels[True]
        needle = _normalize(quote, loose=True)
        bounds = [*starts, len(text)]
        page_text = [text[a:b] for a, b in pairwise(bounds)]
        found = set()
        for cut in range(min_part, len(needle) - min_part + 1):
            head, tail = needle[:cut], needle[cut:]
            for p, this in enumerate(page_text, 1):
                if head not in this:
                    continue
                for q in (p + 1, p + 2):  # the next page, or past a figure page
                    if q > len(page_text) or self._files[q - 1] != self._files[p - 1]:
                        break  # no such page, or it is in another file
                    if tail in page_text[q - 1]:
                        found.add(p)
        return sorted(found)

    def filled(self, quote: str) -> str | None:
        """``quote`` with the few characters it leaves out put back, as the
        text has them, or ``None``.

        For text taken from elsewhere (the publisher's XML) that the text
        layer prints with a symbol more, such as ``"∼50"`` for ``"50"``: up
        to :data:`MAX_EXTRA` characters at a place, and nothing else
        different. Only a result the text layer has is returned.
        """
        needle = _normalize(quote, loose=True)
        if len(needle) < 2 * ANCHOR or EQUATION_MARK.search(quote):
            return None
        text, _ = self._levels[True]
        room = len(needle) + 4 * MAX_EXTRA
        windows = [
            (i, min(len(text), i + room), True)
            for i in _occurrences(text, needle[:ANCHOR])
        ] + [
            (max(0, i + ANCHOR - room), i + ANCHOR, False)
            for i in _occurrences(text, needle[-ANCHOR:])
        ]
        for start, end, from_head in windows:
            window = text[start:end]
            ops = SequenceMatcher(None, needle, window, autojunk=False).get_opcodes()
            # the window runs past the quote at one end
            if ops and ops[-1 if from_head else 0][0] == "insert":
                ops = ops[:-1] if from_head else ops[1:]
            inserts = [(i, window[j:k]) for op, i, _, j, k in ops if op == "insert"]
            if not inserts or any(op not in ("equal", "insert") for op, *_ in ops):
                continue
            if any(len(extra) > MAX_EXTRA for _, extra in inserts):
                continue
            out = _put_in(quote, inserts)
            if out is not None and self.find(out, loose=True):
                return out
        return None

    def divergence(self, quote: str) -> str:
        """Describe where ``quote`` stops matching the text (loose comparison)."""
        text, _ = self._levels[True]
        needle = _normalize(quote, loose=True)
        lo, hi = 0, len(needle)
        while lo < hi:  # longest prefix present in the text
            mid = (lo + hi + 1) // 2
            if needle[:mid] in text:
                lo = mid
            else:
                hi = mid - 1
        if lo == 0:
            return "no part of the quote was found"
        at = text.find(needle[:lo]) + lo
        detail = (
            f"matches through …{needle[max(0, lo - 25) : lo]!r}; quote continues "
            f"{needle[lo : lo + 25]!r}, text has {text[at : at + 25]!r} "
            "(whitespace removed)"
        )
        # a few characters in one and not the other, after which both go on alike
        rest = needle[lo : lo + 12]
        for n in range(1, MAX_EXTRA + 1):
            if len(rest) >= 4 and text.startswith(rest, at + n):
                extra = text[at : at + n]
                return (
                    f"{detail}; the page has {extra!r} here, which the quote leaves out"
                )
            after = needle[lo + n : lo + n + 12]
            if len(after) >= 4 and text.startswith(after, at):
                extra = needle[lo : lo + n]
                return (
                    f"{detail}; the quote has {extra!r} here, which the page does not"
                )
        return detail


def check_manuscript_anchor(
    anchor: ManuscriptAnchor,
    text: ManuscriptText,
    paragraphs: Mapping[tuple[str, int], str] | None = None,
    image_sections: Collection[str] = (),
) -> tuple[Outcome, str]:
    """Check a manuscript quote against the text layer and its stated page.

    If ``paragraphs`` maps (section, paragraph) to the paragraph text that
    offsets refer to, the character span is checked as well. Quotes from
    ``image_sections`` (text transcribed from figure images) that are not in
    the text layer are reported as unchecked rather than mismatched. A quote
    that is the paragraph's text but not the page's points at the paragraph
    (a heading or label run into it, a line from elsewhere, a line lost),
    and the detail says so.
    """
    notes = []
    para = None
    if paragraphs is not None:
        para = paragraphs.get((anchor.section, anchor.paragraph))
        if para is None:
            notes.append("paragraph not in the paragraph index")
        elif para[anchor.char_start : anchor.char_end] != anchor.quote:
            return Outcome.MISMATCH, (
                f"characters {anchor.char_start}–{anchor.char_end} of the paragraph "
                f"read {para[anchor.char_start : anchor.char_end]!r}"
            )

    # Try each match level in turn; a quote can occur more than once, so a
    # level only counts if it finds the quote on the stated page.
    levels = [
        (Outcome.VERIFIED, "found", lambda: text.find(anchor.quote, loose=False)),
        (
            Outcome.VERIFIED_NORMALIZED,
            "found after normalizing",
            lambda: text.find(anchor.quote, loose=True),
        ),
        (
            Outcome.VERIFIED_NORMALIZED,
            "found split across a page break starting",
            lambda: text.find_split(anchor.quote),
        ),
    ]
    elsewhere = set()
    for outcome, how, find in levels:
        pages = set(find())
        if pages and (anchor.page is None or anchor.page in pages):
            if anchor.page is None:
                notes.append("anchor states no page")
            where = f"{how} on {text.names(pages)}"
            if EQUATION_MARK.search(anchor.quote):
                notes.append("the equations it marks are not compared")
            return outcome, "; ".join([where, *notes])
        elsewhere |= pages
    if elsewhere:
        return Outcome.WRONG_PAGE, (
            f"anchor states {text.name(anchor.page)}; found on {text.names(elsewhere)}"
        )
    if anchor.section in image_sections:
        return Outcome.UNCHECKED, (
            "transcribed from a figure image; not in the text layer, check visually"
        )
    detail = text.divergence(anchor.quote)
    if para is not None:
        page = text.name(anchor.page) if anchor.page is not None else "the PDF"
        detail += (
            "; the quote is the paragraph's text, so the paragraph may differ "
            "from the printed page here (the publisher's XML worded differently "
            "from its PDF, or, read from the PDF, a heading or label run into "
            f"it, a line from elsewhere, a line lost): compare it with {page}, "
            "and fix the paragraph or the quote"
        )
    return Outcome.MISMATCH, detail


# --- Code ---------------------------------------------------------------------


def check_code_anchor(anchor: CodeAnchor, materials: Path) -> tuple[Outcome, str]:
    """Compare a code quote with the cited lines at the anchor's commit.

    Without a commit, the working tree is used and the detail says so.
    """
    path = materials / anchor.file
    if not path.is_file():
        return Outcome.MISMATCH, f"{anchor.file} not found"
    working = codeindex.read_lines(path)
    if anchor.commit is None:
        lines, source = working, "working tree (anchor states no commit)"
    else:
        lines = codeindex.file_at_commit(path, anchor.commit)
        if lines is None:
            return Outcome.MISMATCH, f"{anchor.file} is not in commit {anchor.commit}"
        source = f"commit {anchor.commit}"

    span = slice(anchor.line_start - 1, anchor.line_end)
    if anchor.line_end > len(lines):
        return Outcome.MISMATCH, f"{source} has only {len(lines)} lines"
    cited = "\n".join(lines[span]).rstrip()
    if cited != anchor.quote.rstrip():
        return Outcome.MISMATCH, f"{source} has {cited!r}"
    detail = f"matches {source}"
    if anchor.commit is not None and "\n".join(working[span]).rstrip() != cited:
        detail += "; the working tree differs at these lines"
    return Outcome.VERIFIED, detail


# --- Data ---------------------------------------------------------------------

sha256 = cache(derivation_values.sha256)
"""Hex SHA-256 of a file, computed once per path (materials do not change)."""

_NUMBER = re.compile(r"(?<![\d.])[+-]?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?")
_GROUPED = re.compile(r"(?<![\d.])[+-]?\d{1,3}(?:,\d{3})+(?:\.\d+)?")
"""Numbers with thousands separators, e.g. ``18,236``."""


def shown_in(value: Value, quote: str) -> bool:
    """Whether ``quote`` shows ``value``, rounded to the digits printed.

    A string must appear verbatim, and true or false as a word ("true" or
    "yes", "false" or "no", in any case). A number must match some number in the
    quote to within half a unit of that number's last digit, so 4.125 is
    shown by "4.13" and 1.5612e-10 by "1.56e-10".
    """
    if isinstance(value.value, bool):
        words = ("true", "yes") if value.value else ("false", "no")
        return any(re.search(rf"\b{w}\b", quote, re.IGNORECASE) for w in words)
    if isinstance(value.value, str):
        return value.value in quote
    x = Decimal(repr(value.value))
    text = quote.replace("−", "-")
    for pattern in (_NUMBER, _GROUPED):
        for m in pattern.finditer(text):
            try:
                shown = Decimal(m.group().replace(",", ""))
            except InvalidOperation:
                continue
            half = Decimal(5).scaleb(shown.as_tuple().exponent - 1)
            if abs(x - shown) <= half:
                return True
    return False


def _numbers(text: str) -> list[str]:
    text = text.replace("−", "-")
    found = {
        m.group() for pattern in (_NUMBER, _GROUPED) for m in pattern.finditer(text)
    }
    return sorted(found)


def unsupported_numbers(statement: str, quote: str) -> list[str]:
    """Numbers in ``statement`` that ``quote`` does not show.

    Two numbers match when they agree to the precision of the coarser one, so
    a statement may round the quote ("0.42" for "0.418") but not change it.
    """
    shown = []
    for token in _numbers(quote):
        try:
            shown.append(Decimal(token.replace(",", "")))
        except InvalidOperation:
            continue
    missing = []
    for token in _numbers(statement):
        try:
            x = Decimal(token.replace(",", ""))
        except InvalidOperation:
            continue
        if not any(
            abs(x - s)
            <= Decimal(5).scaleb(max(x.as_tuple().exponent, s.as_tuple().exponent) - 1)
            for s in shown
        ):
            missing.append(token)
    return missing


def _check_values(
    anchor: DataAnchor,
    values: Sequence[Value],
    workspace: Path,
    outputs: dict[Path, dict],
    hashes: dict[Path, str],
) -> tuple[Outcome, str]:
    derivation = anchor.produced_by
    assert derivation is not None
    path = workspace / derivation.output
    if not (workspace / derivation.script).is_file():
        return Outcome.MISMATCH, f"{derivation.script} not found"
    if not path.is_file():
        return Outcome.MISMATCH, f"{derivation.output} not found"
    if path not in outputs:
        outputs[path] = derivation_values.read_values(path)
    doc = outputs[path]
    if doc["script"] != derivation.script:
        return Outcome.MISMATCH, (
            f"{derivation.output} was written by {doc['script']}, "
            f"not {derivation.script}"
        )
    changed = []
    sources = {doc["script"]: doc["script_sha256"], **doc["inputs"]}
    for name, digest in sources.items():
        p = workspace / name
        if p not in hashes:
            hashes[p] = derivation_values.sha256(p) if p.is_file() else ""
        if hashes[p] != digest:
            changed.append(name)
    if changed:
        return Outcome.STALE, (
            f"script or inputs changed since {derivation.output} was written: "
            f"{', '.join(changed)}; rerun {derivation.script}"
        )
    for v in values:
        if v.key not in doc["values"]:
            return Outcome.MISMATCH, f"{v.key} not in {derivation.output}"
        if not same_value(doc["values"][v.key], v.value):
            return Outcome.MISMATCH, (
                f"{v.key} is {doc['values'][v.key]!r} in {derivation.output}, "
                f"{v.value!r} in the record"
            )
        if not shown_in(v, anchor.quote):
            return Outcome.MISMATCH, f"{v.name} = {v.value!r} is not shown in the quote"
    return Outcome.VERIFIED, (
        f"{plural(len(values), 'value')} match {derivation.output}; inputs unchanged"
    )


def check_data_anchor(
    anchor: DataAnchor,
    materials: Path,
    checksums: Mapping[str, str],
    values: Sequence[Value] = (),
    workspace: Path | None = None,
    *,
    _outputs: dict[Path, dict] | None = None,
    _hashes: dict[Path, str] | None = None,
) -> tuple[Outcome, str]:
    """Check a data anchor's file, checksum, and values.

    ``checksums`` maps paths relative to ``materials`` to SHA-256 digests;
    for a folder, every file in it with a checksum is compared.
    When the anchor names the derivation that produced its values, each of
    ``values`` is read back from the derivation's output (paths relative to
    ``workspace``). Without one, the values are not checked and a passing
    anchor is ``UNCHECKED``.
    """
    path = materials / anchor.file
    if path.is_dir():
        inside = f"{anchor.file.rstrip('/')}/"
        known = {f: c for f, c in checksums.items() if f.startswith(inside)}
        what = "folder"
    elif path.is_file():
        known = {f: c for f, c in checksums.items() if f == anchor.file}
        what = "file"
    else:
        return Outcome.MISMATCH, f"{anchor.file} not found"
    for f, expected in sorted(known.items()):
        if not (materials / f).is_file():
            return Outcome.MISMATCH, f"{f} not found"
        if sha256(materials / f) != expected:
            return Outcome.MISMATCH, f"{f} checksum differs from the manifest"
    if not known:
        file_note = f"{what} present; no checksum recorded"
    elif what == "file":
        file_note = "file present, checksum matches"
    else:
        file_note = f"folder present, checksums match for {plural(len(known), 'file')}"
    if anchor.produced_by is None:
        return Outcome.UNCHECKED, f"{file_note}; no derivation named, value not checked"
    if workspace is None:
        return Outcome.UNCHECKED, f"{file_note}; values not checked (no workspace)"
    outcome, detail = _check_values(
        anchor,
        values,
        workspace,
        {} if _outputs is None else _outputs,
        {} if _hashes is None else _hashes,
    )
    return outcome, f"{detail}; {file_note}"


# --- Record -------------------------------------------------------------------


def _anchors(
    record: AuditRecord,
) -> Iterator[tuple[str, Anchor, tuple[Value, ...], str | None]]:
    for c in record.claims:
        yield f"claim {c.id}", c.anchor, (), None
    for f in record.findings:
        for o in f.observations:
            yield f"finding {f.id} {o.source}", o.anchor, o.values, o.statement


def check_record(
    record: AuditRecord,
    materials: Path,
    manuscript: ManuscriptText,
    *,
    workspace: Path | None = None,
    paragraphs: Mapping[tuple[str, int], str] | None = None,
    checksums: Mapping[str, str] | None = None,
    image_sections: Collection[str] = (),
    readings: Mapping[str, Collection[str]] | None = None,
) -> list[AnchorCheck]:
    """Check every anchor in a record (claims, then findings) against the materials.

    The record is assumed to have a single manuscript, whose text layer is
    ``manuscript``. Derivation outputs are read relative to ``workspace``.
    A code observation's values must be shown in its quote, except those
    stated in fixed words: ``readings`` maps a value name to those words
    (:data:`rigoraudit.stats.READINGS`).
    """
    readings = readings or {}
    outputs: dict[Path, dict] = {}
    hashes: dict[Path, str] = {}
    results = []
    for location, anchor, values, statement in _anchors(record):
        match anchor:
            case ManuscriptAnchor():
                outcome, detail = check_manuscript_anchor(
                    anchor, manuscript, paragraphs, image_sections
                )
            case CodeAnchor():
                outcome, detail = check_code_anchor(anchor, materials)
                hidden = [
                    v
                    for v in values
                    if v.value not in readings.get(v.name, ())
                    and not shown_in(v, anchor.quote)
                ]
                if hidden and outcome is not Outcome.MISMATCH:
                    v = hidden[0]
                    outcome, detail = (
                        Outcome.MISMATCH,
                        f"{v.name} = {v.value!r} is not shown in the quote; {detail}",
                    )
            case DataAnchor():
                outcome, detail = check_data_anchor(
                    anchor,
                    materials,
                    checksums or {},
                    values,
                    workspace,
                    _outputs=outputs,
                    _hashes=hashes,
                )
                # a derived value's statement says how it was computed, so its
                # numbers need not be in the quote; the value itself is checked
                missing = (
                    []
                    if anchor.produced_by
                    else unsupported_numbers(statement or "", anchor.quote)
                )
                if missing and outcome is not Outcome.MISMATCH:
                    outcome, detail = (
                        Outcome.MISMATCH,
                        (
                            f"the statement cites {', '.join(missing)}, which the quote "
                            f"does not show; {detail}"
                        ),
                    )
        results.append(
            AnchorCheck(location, anchor.kind, outcome, detail, anchor.quote)
        )
    return results
