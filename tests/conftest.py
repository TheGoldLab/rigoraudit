# Copyright (c) 2026, Joshua I. Gold
# SPDX-License-Identifier: BSD-2-Clause

import datetime
import re

import pytest

from rigoraudit import clipboard, compare, decompose, derive, handoffs, segment, trace
from rigoraudit.schema import Drafter, DrafterKind

DRAFTER = Drafter(
    kind=DrafterKind.PERSON, name="A. Reviewer", date=datetime.date(2026, 1, 1)
)
"""Drafter for records built in tests."""


@pytest.fixture(autouse=True)
def no_clipboard(monkeypatch):
    """Tests never touch the computer's clipboard; those of the clipboard
    give the guide a stand-in."""
    monkeypatch.setattr(clipboard, "find", lambda: None)


@pytest.fixture(autouse=True)
def every_problem_has_a_kind(monkeypatch):
    """Feedback reports count problems by kind (decision 0012), so every problem
    an import returns, in any test, must have one."""
    for module in (segment, decompose, trace, derive, compare):
        original = module.import_answer

        def checked(*args, _original=original, **kwargs):
            saved, problems = _original(*args, **kwargs)
            unkinded = [p for p in problems if handoffs.kind(p) == "other"]
            assert not unkinded, f"problems with no kind: {unkinded}"
            return saved, problems

        monkeypatch.setattr(module, "import_answer", checked)


def make_pdf(pages: list[list], second: str = "Helvetica-Bold") -> bytes:
    """A PDF with one line of Helvetica text per entry, top to bottom.

    An entry is the line's text, or ``(text, x, size, drop)``: its left edge,
    type size, and how far below the line before it it is printed (all in
    points; a line of text alone is ``(text, 50, 10, 14)``). Text between
    ``**`` is set in the ``second`` font, in the size given as a fifth item
    if there is one.
    """
    font = "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"
    bold = f"<< /Type /Font /Subtype /Type1 /BaseFont /{second} >>"
    objects = ["<< /Type /Catalog /Pages 2 0 R >>", "", font, bold]
    kids = []
    for lines in pages:
        ops, y = [], 764
        for line in lines:
            line, x, size, drop, *other = (
                (line, 50, 10, 14) if isinstance(line, str) else line
            )
            sizes = (size, other[0] if other else size)
            y -= drop
            text = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
            runs = "".join(
                f"/F{1 + i % 2} {sizes[i % 2]} Tf ({part}) Tj "
                for i, part in enumerate(re.split(r"\*\*", text))
                if part
            )
            ops.append(f"BT {x} {y} Td {runs}ET")
        stream = "\n".join(ops)
        objects.append(f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream")
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents "
            f"{len(objects)} 0 R /Resources << /Font << /F1 3 0 R /F2 4 0 R >> >> >>"
        )
        kids.append(f"{len(objects)} 0 R")
    objects[1] = f"<< /Type /Pages /Kids [{' '.join(kids)}] /Count {len(kids)} >>"
    out, offsets = b"%PDF-1.4\n", []
    for n, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += f"{n} 0 obj\n{body}\nendobj\n".encode("latin-1")
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{o:010d} 00000 n \n".encode() for o in offsets)
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref}\n%%EOF\n"
    ).encode()
    return out
