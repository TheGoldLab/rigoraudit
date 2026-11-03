# Copyright (c) 2026, Joshua I. Gold
# SPDX-License-Identifier: BSD-2-Clause
"""Each display equation as printed, beside the auditor's typed-in version.

An equation checked in a derivation is typed in by hand, and a slip in the
typing looks like a slip in the paper. ``rigoraudit equations`` writes
``work/equations.html``: for each equation the extract step found
(``work/extract/equations.json``), its picture as printed, the text the
extract step read, and the auditor's version drawn as maths, so the two can
be compared by eye.

The auditor's versions are in ``derivations/equations.yaml``, in LaTeX, by
the equation's number as printed, or for one without, its key from its page
and place there (``"p22@233"``; :mod:`rigoraudit.numbering`)::

    "3": '\\frac{dx}{dt} = -\\lambda x'
    A12:
      latex: |
        p(x \\mid \\theta) = \\mathcal{N}(\\mu, \\sigma^2)
      note: typed from page 21; the printed subscript is unclear
    p22@233: 'y = a + b'

Making the page also applies the auditor's corrections to the numbers
(``derivations/equation_numbers.yaml``) to ``equations.json``.

The page is one file that opens without a connection: the pictures are in
it, and so is KaTeX (``katex/``, MIT license), which draws the LaTeX.
"""

from __future__ import annotations

import base64
import html
import json
import re
import struct
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

import yaml

from rigoraudit import numbering, pictures
from rigoraudit.extract import (
    EQUATIONS_FILE,
    FOLDER,
    number_records,
    write_equations,
)
from rigoraudit.extract import (
    numbering_note as numbering_check,
)

TYPED = PurePosixPath("derivations/equations.yaml")
PAGE = PurePosixPath("work/equations.html")
KATEX = Path(__file__).parent / "katex"
ZOOM = 2.5
"""Screen pixels per printed point, for the picture and the typed version
alike, so the two are drawn the same size."""
SIZE = 10.0
"""Type size (points) for an equation listed without one."""
_FONT = re.compile(
    r'url\(fonts/([\w-]+)\.woff2\) format\("woff2"\)(?:,url\([^)]*\) format\("\w+"\))*'
)


@dataclass(frozen=True)
class Typed:
    """The auditor's version of one equation."""

    latex: str
    note: str = ""


def read_typed(path: Path) -> dict[str, Typed]:
    """The typed versions in ``path`` (see the module's description), by
    key; none if there is no file.

    Raises ``ValueError`` naming the entry that is not LaTeX text or a
    mapping with ``latex`` (and optionally ``note``).
    """
    if not path.is_file():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        # a mistake in the file, not in the code
        raise ValueError(f"{path} should map equation numbers to LaTeX")  # noqa: TRY004
    out = {}
    for k, v in data.items():
        if isinstance(v, str):
            v = {"latex": v}
        if (
            not isinstance(v, dict)
            or not isinstance(v.get("latex"), str)
            or not isinstance(v.get("note", ""), str)
            or set(v) - {"latex", "note"}
        ):
            raise ValueError(
                f"{path}: equation {k}: give LaTeX text, or latex: and note:"
            )
        out[str(k)] = Typed(v["latex"].strip(), v.get("note", "").strip())
    return out


def _data_uri(path: Path, kind: str) -> str:
    return f"data:{kind};base64,{base64.b64encode(path.read_bytes()).decode()}"


def _katex() -> str:
    """KaTeX's style sheet, with its fonts in it, and its script."""

    def font(m: re.Match) -> str:
        uri = _data_uri(KATEX / "fonts" / f"{m[1]}.woff2", "font/woff2")
        return f'url({uri}) format("woff2")'

    css = _FONT.sub(font, (KATEX / "katex.min.css").read_text(encoding="utf-8"))
    js = (KATEX / "katex.min.js").read_text(encoding="utf-8")
    return f"<style>{css}</style>\n<script>{js}</script>"


STYLE = """
:root { --ink: #1b1b1b; --muted: #5f5f5f; --rule: #d9d9d9; --soft: #f5f5f3;
  --bg: #fff; --miss: #a65d12; }
body { background: var(--bg); color: var(--ink); font: 15px/1.5 system-ui, sans-serif;
  margin: 0 auto; max-width: 72rem; padding: 24px 16px 48px; }
h1 { font-size: 1.4rem; margin: 0 0 4px; }
.lede { color: var(--muted); margin: 0 0 20px; }
nav { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 16px; }
nav button { font: inherit; font-size: 13px; padding: 4px 10px; border: 1px solid var(--rule);
  border-radius: 14px; background: var(--bg); cursor: pointer; }
nav button[aria-pressed="true"] { background: var(--ink); color: var(--bg); border-color: var(--ink); }
.eq { border-top: 1px solid var(--rule); padding: 14px 0; }
.eq h2 { font-size: 1rem; margin: 0 0 8px; }
.eq h2 span { color: var(--muted); font-weight: 400; font-size: 13px; margin-left: 8px; }
.pair { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 22rem), 1fr)); gap: 12px; }
.pair > div { background: var(--soft); border-radius: 6px; padding: 10px; overflow-x: auto;
  min-width: 0; }
.label { font-size: 12px; color: var(--muted); margin: 0 0 6px; }
.pair img { display: block; background: #fff; }
.missing { color: var(--miss); font-size: 13px; margin: 0; }
.note { font-size: 13px; margin: 6px 0 0; }
.note.number { color: var(--miss); margin: 0 0 8px; }
details { margin-top: 8px; font-size: 13px; color: var(--muted); }
pre { white-space: pre-wrap; word-break: break-word; font-size: 12px; margin: 4px 0 0; }
.tex-error { color: var(--miss); }
.tex .katex-display { margin: 0; text-align: left; }
.tex .katex-display > .katex { text-align: left; font-size: 1em; }
"""

SCRIPT = """
document.querySelectorAll(".tex").forEach((el) => {
  try {
    katex.render(el.dataset.tex, el, {displayMode: true, throwOnError: true});
  } catch (e) {
    el.classList.add("tex-error");
    el.textContent = "Could not draw this LaTeX: " + e.message;
  }
});
const buttons = document.querySelectorAll("nav button");
buttons.forEach((b) => b.addEventListener("click", () => {
  buttons.forEach((o) => o.setAttribute("aria-pressed", String(o === b)));
  document.querySelectorAll(".eq").forEach((eq) => {
    eq.hidden = b.dataset.show !== "all" && !eq.classList.contains(b.dataset.show);
  });
}));
"""


def _picture_html(path: Path, title: str) -> str:
    """The picture at ``path``, drawn :data:`ZOOM` pixels to the point."""
    data = path.read_bytes()
    width, height = struct.unpack(">II", data[16:24])
    w, h = (round(v / pictures.SCALE * ZOOM) for v in (width, height))
    return (
        f'<img src="{_data_uri(path, "image/png")}" width="{w}" height="{h}" '
        f'alt="{html.escape(title)} as printed">'
    )


def _typed_html(t: Typed | None, size: float) -> str:
    """The typed version, drawn at the printed ``size`` (points)."""
    if t is None:
        return f'<p class="missing">Not typed in yet ({TYPED}).</p>'
    note = f'<p class="note">{html.escape(t.note)}</p>' if t.note else ""
    return (
        f'<div class="tex" style="font-size: {size * ZOOM:.1f}px" '
        f'data-tex="{html.escape(t.latex)}"></div>{note}'
        f"<details><summary>LaTeX</summary><pre>{html.escape(t.latex)}</pre></details>"
    )


def page(workspace: Path) -> tuple[str, int, int, list[str]]:
    """The comparison page for ``workspace``, the number of equations, how
    many are typed in, and the typed keys that match no equation."""
    listed, fixes = numbered(workspace)
    typed = read_typed(workspace / TYPED)
    keys = [r["key"] for r in listed]
    matched = numbering.match_typed(keys, typed)
    by_key = {k: typed[t] for t, k in matched.items()}
    typed_as = {k: t for t, k in matched.items() if t != k}
    blocks = []
    for n, (r, k) in enumerate(zip(listed, keys, strict=True), 1):
        t = by_key.get(k)
        title = f"Equation {k}"
        where = []
        if r.get("page"):
            where.append(f"page {r['page']}")
            if r["number"] and r.get("down") is not None:
                where.append(f"place p{r['page']}@{r['down']}")
        if not r["number"]:
            where.insert(0, "no number printed")
        if r.get("section"):
            where.append(f"{r['section']}, paragraph {r['paragraph']}")
        if k in typed_as:
            where.append(f"typed in as {typed_as[k]}")
        printed = (
            _picture_html(workspace / FOLDER / r["picture"], title)
            if r.get("picture")
            else '<p class="missing">No picture: not found in the PDF.</p>'
        )
        note = (
            f'<p class="note number">{html.escape(r["note"])}</p>'
            if r.get("note")
            else ""
        )
        blocks.append(
            f'<section class="eq {"typed" if t else "untyped"}" id="eq-{n}">'
            f"<h2>{html.escape(title)}<span>{html.escape(' · '.join(where))}</span></h2>"
            f"{note}"
            f'<div class="pair"><div><p class="label">As printed</p>{printed}</div>'
            f'<div><p class="label">Typed in</p>{_typed_html(t, r.get("size") or SIZE)}</div></div>'
            f"<details><summary>Text the extract step read</summary>"
            f"<pre>{html.escape(r.get('text') or '')}</pre></details></section>"
        )
    unmatched = [k for k in typed if k not in matched]
    done = len(matched)
    extra = (
        f'<p class="missing">Typed in, but no equation listed with this number: '
        f"{html.escape(', '.join(unmatched))}.</p>"
        if unmatched
        else ""
    )
    if check := numbering_check(listed, fixes):
        extra += f'<p class="missing">{html.escape(check)}</p>'
    body = (
        "<h1>Equations: as printed and as typed in</h1>"
        f'<p class="lede">{len(listed)} equations; {done} typed in '
        f"({TYPED}). Pictures are from the PDF; check each typed version "
        "against its picture, symbol by symbol.</p>"
        f"{extra}<nav>"
        '<button data-show="all" aria-pressed="true">All</button>'
        '<button data-show="typed" aria-pressed="false">Typed in</button>'
        '<button data-show="untyped" aria-pressed="false">Not typed in</button>'
        f"</nav>{''.join(blocks)}"
    )
    text = (
        '<!doctype html>\n<html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>Equations</title>{_katex()}<style>{STYLE}</style></head>"
        f"<body>{body}<script>{SCRIPT}</script></body></html>\n"
    )
    return text, len(listed), done, unmatched


def numbered(workspace: Path) -> tuple[list[dict], dict]:
    """The listed equations, numbered with the auditor's corrections
    (:func:`rigoraudit.extract.number_records`), and the corrections."""
    listed = json.loads((workspace / EQUATIONS_FILE).read_text(encoding="utf-8"))
    fixes = numbering.read_corrections(workspace / numbering.CORRECTIONS)
    number_records(listed, fixes)
    return listed, fixes


def write_page(workspace: Path) -> str:
    """Write ``work/equations.html`` and say what is in it."""
    if not (workspace / EQUATIONS_FILE).is_file():
        raise FileNotFoundError(
            f"no {EQUATIONS_FILE} in {workspace}; run rigoraudit extract first"
        )
    listed, fixes = numbered(workspace)
    write_equations(workspace / FOLDER, listed)
    text, n, done, unmatched = page(workspace)
    (workspace / PAGE).write_text(text, encoding="utf-8")
    out = f"Wrote {PAGE}: {n} equations, {done} typed in. Open it in a browser."
    if check := numbering_check(listed, fixes):
        out += f"\n{check}"
    if unmatched:
        out += (
            f"\nTyped in {TYPED}, but no equation has this number: "
            f"{', '.join(unmatched)}."
        )
    return out
