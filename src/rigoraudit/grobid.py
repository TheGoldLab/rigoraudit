# Copyright (c) 2026, Joshua I. Gold
# SPDX-License-Identifier: BSD-2-Clause
"""Paragraphs from GROBID, an optional engine for a paper with only a PDF.

GROBID (https://github.com/kermitt2/grobid) is a free program that reads a
scientific PDF and writes its structure as TEI XML: headings, paragraphs,
figure legends. It finds paragraph breaks better than the tool's own PDF
route, most of all in two-column layouts. It is not installed with the
tool; it runs as a server (a Docker image, or built from source), and the
tool sends it the PDF when the manifest names the server::

    settings:
      extract:
        grobid: http://localhost:8070

(or ``rigoraudit extract --grobid http://localhost:8070``). The PDF is sent
to whatever server is named, so name one you run yourself.

GROBID's headings are flat. Where the PDF's outline names them, a heading
in the outline's top level starts a major section, and so does a standard
section (:func:`~rigoraudit.sections.standard_kind`) of a kind the outline
leaves out; the other headings are subsections. Without such an outline, a
standard section starts a major section unless it is of the same kind as
the one it is in ("Method Details" under "STAR Methods"). A formula set
on its own line stays in its paragraph when the text after it does not
start a new sentence, as in the publisher's XML.
"""

from __future__ import annotations

import re
import urllib.request
import uuid
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

from rigoraudit.sections import SEPARATOR, compact, standard_kind

TEI = "{http://www.tei-c.org/ns/1.0}"
SERVICE = "/api/processFulltextDocument"
TIMEOUT = 600
"""Seconds to wait for GROBID; a long paper can take a minute or two."""
LABEL = re.compile(r"^(?:Figure|Fig\.|Table)?\s*(\d+)\s*[.:|]?\s*$", re.IGNORECASE)
PREFIX = re.compile(r"^(?:Figure|Fig\.|Table)\s+\d+\s*[.:|]\s*")
"""A legend's label, which GROBID sometimes leaves at the start of its text."""
FIRST = re.compile(r"(?<=[.!?])\s+(?=[A-Z(])")
MARKER = re.compile(
    r"^\(?(?:legend|(?:figure|fig\.|table)\s+\d+)\s+continued\b", re.IGNORECASE
)
STARTS_SENTENCE = re.compile(r"^[\"'“‘(\[]?[A-Z0-9]")
BACK = {
    "acknowledgement": "Acknowledgements",
    "funding": "Funding",
    "availability": "Data availability",
}
"""Names for back-matter parts GROBID marks by type, without a heading."""
UNPLACED = "Unplaced text"
"""The section for what GROBID sets aside as a figure without a label:
usually body text, an equation, or part of a legend it could not place."""


def request(pdf: Path, server: str, timeout: float = TIMEOUT) -> bytes:
    """The TEI XML GROBID writes for ``pdf``.

    Raises :class:`OSError` (``urllib.error.URLError``) if the server does
    not answer or refuses the file.
    """
    boundary = uuid.uuid4().hex
    fields = {"consolidateHeader": "0", "consolidateCitations": "0"}
    body = b"".join(
        f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n'
        f"{v}\r\n".encode()
        for k, v in fields.items()
    )
    body += (
        f"--{boundary}\r\nContent-Disposition: form-data; "
        'name="input"; filename="paper.pdf"\r\n'
        "Content-Type: application/pdf\r\n\r\n"
    ).encode()
    body += pdf.read_bytes() + f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(
        server.rstrip("/") + SERVICE,
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as answer:
        return answer.read()


def _text(e: ET.Element | None) -> str:
    return " ".join("".join(e.itertext()).split()) if e is not None else ""


def _heading(div: ET.Element) -> str:
    """A part's heading, or its name by type; not a line that says a legend
    goes on over the page, which GROBID can take for a heading."""
    head = _text(div.find(TEI + "head"))
    if MARKER.match(head):
        head = ""
    return head or BACK.get(div.get("type", ""), "")


def _is_references(div: ET.Element) -> bool:
    return div.get("type") == "references" or div.find(TEI + "listBibl") is not None


def tei_paragraphs(root: ET.Element, majors: tuple[str, ...] = ()) -> list[dict]:
    """The paragraphs in GROBID's TEI, numbered within each section.

    Abstract first, then the body and back matter (not the reference
    list), then figure legends and table captions, each split into its
    title (first sentence) and the rest, and then :data:`UNPLACED`.
    ``majors`` are the PDF outline's major section titles.
    """
    major_keys = {compact(m) for m in majors}
    out: list[dict] = []
    count: Counter[str] = Counter()

    def add(section: str, text: str) -> dict | None:
        if not text:
            return None
        count[section] += 1
        para = {"section": section, "paragraph": count[section], "text": text}
        out.append(para)
        return para

    for abstract in root.iter(TEI + "abstract"):
        for p in abstract.iter(TEI + "p"):
            add("Abstract", _text(p))

    divs = [
        (part, div)
        for part in ("body", "back")
        for el in root.iter(TEI + part)
        for div in el.iter(TEI + "div")
        if not _is_references(div)
    ]
    heads = [_heading(div) for _, div in divs]
    if sum(compact(h) in major_keys for h in heads if h) < 2:
        major_keys = set()  # the outline does not name GROBID's headings
    outline_kinds = {standard_kind(m) for m in majors}

    def is_major(head: str) -> bool:
        if not major:
            return True
        kind = standard_kind(head)
        if major_keys and compact(head) in major_keys:
            return True
        if major_keys and kind in outline_kinds:
            return False
        return kind is not None and kind != standard_kind(major)

    major = in_body = section = ""
    for (part, div), head in zip(divs, heads):
        if div.get("type") == "annex":
            major = section = in_body  # text GROBID could not place: it goes on
        if head and is_major(head):
            major = section = head
        elif head:
            section = major + SEPARATOR + head
        section = section or "Main text"  # without a heading, it goes on
        if part == "body":
            in_body = major
        para: dict | None = None
        after_formula = False
        for c in div:
            if c.tag == TEI + "formula" and para is not None:
                para["text"] += " " + _text(c)
                after_formula = True
            elif c.tag == TEI + "p":
                text = _text(c)
                if after_formula and text and not STARTS_SENTENCE.match(text):
                    para["text"] += " " + text
                else:
                    para = add(section, text) or para
                after_formula = False

    unplaced = []
    for fig in root.iter(TEI + "figure"):
        label = LABEL.match(
            _text(fig.find(TEI + "label")) or _text(fig.find(TEI + "head"))
        )
        text = PREFIX.sub("", _text(fig.find(TEI + "figDesc")))
        if not label:
            unplaced.append(text)
            continue
        kind = "Table {} caption" if fig.get("type") == "table" else "Figure {} legend"
        for piece in FIRST.split(text, maxsplit=1):
            add(kind.format(label.group(1)), piece)
    for text in unplaced:
        add(UNPLACED, text)
    return out
