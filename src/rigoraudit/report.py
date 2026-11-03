# Copyright (c) 2026, Joshua I. Gold
# SPDX-License-Identifier: BSD-2-Clause
"""The report page: the manuscript beside a card for each claim.

:func:`write` renders the reviewed record (the draft with the review log
applied, decision 0010) into one HTML page, ``rigoraudit report``. The page
is organized by the manuscript's major sections, named and ordered as in
the PDF's outline (:mod:`rigoraudit.sections`). In each, the audited
paragraphs, with every claim marked, sit beside the claims' cards: each
card sets what Results, Methods, the code, and the data say side by side,
with the exact text, line, or value behind each statement, and any
reviewer override beside the computed status. Filters pick claims by type,
section, and finding.

It reads, from the workspace:

- ``record/record.json`` and ``review/log.json``;
- ``work/extract/paragraphs.json``, ``outline.json``, and
  ``published.txt``, from the extract step, and ``equations.json`` with
  the pictures in ``equations/``: each equation's mark (``"[Equation 3]"``)
  in a paragraph or quote is followed by its picture as printed, small,
  shown full size when clicked;
- ``audit.yaml``, for the audited sections and the gaps in the materials,
  listed at the top of the page and noted on each claim they affect;
- the cross-claim findings, worked out from the reviewed record and the
  crosscheck step's answer (:func:`rigoraudit.crosscheck.current`): listed
  under the gaps, and noted on the card of each claim they involve;
- ``work/checks.json``, for the status paragraph and the coverage line;
- the coverage exclusions (:func:`rigoraudit.check.read_exclusions`), if any;
- ``report/header.html``, the audit's own header: the paper, what the
  audit covers, and where each material came from (a heading and a list;
  see :data:`HEADER`). Without it, a plain header is made.
  ``report/footer.html``, if there is one, is added to the footer.

It writes ``report/audit.html``. Paragraphs shown are those in the audited
sections and any other paragraph with a claim. Each paragraph's text is
marked up for the review page (:mod:`rigoraudit.server`): claims carry
``data-claim-id``, findings ``data-finding-id``, and each paragraph's text
``data-section`` and ``data-paragraph``, with the claim labels inside it
marked ``data-not-text``.
"""

from __future__ import annotations

import base64
import json
import re
from collections import Counter
from collections.abc import Sequence
from html import escape
from pathlib import Path, PurePosixPath

from rigoraudit import check, crosscheck, materials, review, settings, status
from rigoraudit.coverage import Exclusion
from rigoraudit.extract import (
    EQUATIONS_FILE,
    FOLDER,
    OUTLINE,
    TEXT,
    read_pages,
    read_text,
)
from rigoraudit.paragraphs import (
    EQUATION_MARK,
    PARAGRAPHS,
    Paragraph,
    equation_mark,
    in_scope,
    read_paragraphs,
)
from rigoraudit.schema import (
    RECORD,
    AuditRecord,
    Claim,
    ClaimType,
    CrossFinding,
    Finding,
    Observation,
    Rule,
    Source,
    Status,
    Trace,
)
from rigoraudit.sections import Place, Sections, figure_number, load_outline
from rigoraudit.verify import ManuscriptText
from rigoraudit.words import plural

TEMPLATE = Path(__file__).parent / "templates" / "report.html"
PAGE = PurePosixPath("report") / "audit.html"
"""The report page, in the workspace."""
HEADER = PurePosixPath("report") / "header.html"
"""The audit's own header, e.g.::

    <header class="top">
      <div class="eyebrow">Audit · first tracing pass · 1 January 2026</div>
      <h1>Author et al. (2026)</h1>
      <p class="paper-title">The paper's title. Journal 1:23.</p>
      <p class="scope">This audit covers the Results ...</p>
    </header>
    <dl class="meta">
      <div><dt>Manuscript</dt><dd>Version of Record PDF ...</dd></div>
      <div><dt>Code</dt><dd>Repository ... at commit ...</dd></div>
    </dl>

The text of its first ``<h1>`` is the page's title."""
FOOTER = PurePosixPath("report") / "footer.html"

RANK = {
    Status.DIFFERS: 0,
    Status.NOT_DESCRIBED: 1,
    Status.NOT_VERIFIABLE: 2,
    Status.CONSISTENT: 3,
}
EFFECT_RANK = {
    "direct": 0,
    "indirect": 1,
    "presentation": 2,
    "unknown": 3,
    "none_observed": 4,
}
STATUS_LABEL = {
    Status.CONSISTENT: "Consistent",
    Status.DIFFERS: "Differs",
    Status.NOT_DESCRIBED: "Not described",
    Status.NOT_VERIFIABLE: "Not verifiable",
}
STATUS_CLASS = {
    Status.CONSISTENT: "ok",
    Status.DIFFERS: "dif",
    Status.NOT_DESCRIBED: "nd",
    Status.NOT_VERIFIABLE: "nv",
}
TYPE_LABEL = {
    ClaimType.NEW_RESULT: "New result",
    ClaimType.REFERENCED_RESULT: "Referenced result",
    ClaimType.COMPARISON: "Comparison",
    ClaimType.INTERPRETATION: "Interpretation",
    ClaimType.PROCEDURE: "Procedure",
    ClaimType.NO_STATED_SUPPORT: "No stated support",
}
TYPE_ORDER = [
    ClaimType.NEW_RESULT,
    ClaimType.PROCEDURE,
    ClaimType.COMPARISON,
    ClaimType.INTERPRETATION,
    ClaimType.REFERENCED_RESULT,
    ClaimType.NO_STATED_SUPPORT,
]
SOURCE_LABEL = {
    Source.METHODS: "Methods",
    Source.RESULTS: "Results / legend",
    Source.CODE: "Code",
    Source.OUTPUT: "Output",
    Source.DATA: "Data",
}
RULE_LABEL = {
    Rule.RESTATES: "one claim restates the other",
    Rule.SAME_PLACE: "their findings cite the same code, data, or Methods",
    Rule.SAME_LABEL: "the values have the same name, subject, and unit",
    Rule.SAME_MEANING: "an assistant found them to be the same quantity",
}
TABLE_SOURCES = [Source.METHODS, Source.RESULTS, Source.CODE, Source.DATA]
EFFECT_LABEL = {
    "direct": "bears on the reported value",
    "indirect": "bears on the sample or analysis",
    "presentation": "wording or labeling",
    "none_observed": "no effect on reported values",
    "unknown": "",
}
OBTAINED_LABEL = {
    "quoted": "quoted",
    "read": "code read, not run",
    "executed": "authors' code run by the audit",
    "recomputed": "recomputed by the audit",
    "computed": "worked out from the printed values",
}
BASIS_LABEL = {
    "exact": "exact match",
    "reported_precision": "reported precision",
    "design_vs_realization": "stated design vs recorded trials",
    "direction": "direction",
}
KEY = (
    '<div class="key">'
    '<span><span class="sw" style="border-color:var(--ok)"></span>consistent</span>'
    '<span><span class="sw" style="border-color:var(--dif)"></span>differs</span>'
    '<span><span class="sw" style="border-color:var(--nd)"></span>not described</span>'
    '<span><span class="sw" style="border-color:var(--ref);border-bottom-style:dashed">'
    "</span>not traced / cited / interpretation</span></div>"
)


class _Page:
    """Everything one rendering needs, read once."""

    def __init__(
        self,
        draft: AuditRecord,
        entries: tuple[review.Entry, ...],
        paragraphs: list[Paragraph],
        sections: Sections,
        scope: Sequence[str],
        text: ManuscriptText,
        gaps: Sequence[settings.Gap] = (),
    ) -> None:
        self.rec = review.apply(draft, entries).record
        self.gaps = gaps
        self.text = text
        self.reviews, self.orphans = review.current(self.rec, entries)
        self.cross_reviews: dict[str, review.Review] = {}
        self.sections = sections
        self.claims = {c.id: c for c in self.rec.claims}
        self.findings: dict[str, list[Finding]] = {}
        for f in self.rec.findings:
            self.findings.setdefault(f.claim_id, []).append(f)
        self.cross: tuple[CrossFinding, ...] | None = ()
        """Set by :func:`render`, which knows the workspace."""
        self.pictures: list[str] = []
        """Each equation's picture as printed, as a data URI; set by
        :meth:`add_equations`."""
        self.equation_at: dict[tuple[str, int, int], int] = {}
        self.equation_named: dict[tuple[str, int, str], list[int]] = {}
        label = {(p.section, p.number): p for p in paragraphs}
        missing = sorted(
            c.id
            for c in self.rec.claims
            if (c.anchor.section, c.anchor.paragraph) not in label
        )
        if missing:
            raise ValueError(
                f"{plural(len(missing), 'claim')} quote paragraphs not in "
                f"{PARAGRAPHS}: {', '.join(missing[:5])}"
            )
        self.claim_para = {
            c.id: label[(c.anchor.section, c.anchor.paragraph)].label
            for c in self.rec.claims
        }
        with_claims = set(self.claim_para.values())
        self.paras = {
            p.label: p
            for p in paragraphs
            if p.label in with_claims or in_scope(p.section, scope)
        }
        self.keys = sorted(self.paras, key=self.para_order)
        self.position = {k: i for i, k in enumerate(self.keys)}
        self.by_major: dict[int, list[str]] = {}
        for k in self.keys:
            self.by_major.setdefault(self.para_order(k)[0].major, []).append(k)

    def add_equations(self, records: Sequence[dict], folder: Path) -> None:
        """Note each equation's picture (``equations.json``'s records, the
        pictures in ``folder``) and where its mark is."""
        for r in records:
            if not r.get("picture") or r.get("paragraph") is None:
                continue
            i = len(self.pictures)
            data = base64.b64encode((folder / r["picture"]).read_bytes()).decode()
            self.pictures.append(f"data:image/png;base64,{data}")
            if r.get("at") is not None:
                self.equation_at[(r["section"], r["paragraph"], r["at"])] = i
            mark = equation_mark(r["number"])
            self.equation_named.setdefault(
                (r["section"], r["paragraph"], mark), []
            ).append(i)

    def with_equations(
        self, text: str, section: str, paragraph: int, start: int
    ) -> str:
        """``text``, which starts at ``start`` in its paragraph, escaped, with
        each equation mark followed by the equation's picture. A mark is
        matched by its place in the paragraph, or else by its number if one
        equation in the paragraph has it."""
        out, pos = [], 0
        for m in EQUATION_MARK.finditer(text):
            i = self.equation_at.get((section, paragraph, start + m.start()))
            if i is None:
                named = self.equation_named.get((section, paragraph, m[0]), [])
                i = named[0] if len(named) == 1 else None
            if i is None:
                continue
            out.append(escape(text[pos : m.end()]))
            out.append(
                f'<img class="eqpic" data-eq="{i}" alt="{escape(m[0][1:-1])} as '
                'printed" title="Click to enlarge" data-not-text>'
            )
            pos = m.end()
        out.append(escape(text[pos:]))
        return "".join(out)

    def quoted(self, anchor) -> str:
        """A manuscript quote, escaped, with its equations' pictures."""
        return self.with_equations(
            anchor.quote, anchor.section, anchor.paragraph, anchor.char_start
        )

    # --- Where things are ---------------------------------------------------

    def para_order(self, key: str) -> tuple[Place, tuple[int, ...]]:
        """A paragraph's section, then: text before figures, a figure's legend
        before its panel text, and a heading before its text."""
        p = self.paras[key]
        place = self.sections.place(p.section, p.page)
        fig = figure_number(p.section)
        if fig is None:
            return place, (0, 0, 0 if self.is_heading(key) else 1, p.number)
        kind = 0 if p.section.endswith(" title") else 1 if "legend" in p.section else 2
        return place, (1, fig, kind, p.number)

    def is_heading(self, key: str) -> bool:
        return self.paras[key].section.endswith(" › Heading")

    def para_heading(self, key: str) -> str:
        """The subheading shown above a paragraph in the manuscript column."""
        section = self.paras[key].section
        if figure_number(section) is not None:  # a figure's title sits under its legend
            return re.sub(r" title$", " legend", section)
        place, _ = self.para_order(key)
        return (
            self.sections.subsections[place.major][place.sub - 1] if place.sub else ""
        )

    def section_of(self, cid: str) -> int:
        return self.para_order(self.claim_para[cid])[0].major

    def reading_order(self, cid: str) -> int:
        key = self.claim_para[cid]
        return self.position[key] * 100000 + self.claims[cid].anchor.char_start

    def claim_state(self, cid: str) -> str:
        c = self.claims[cid]
        if c.trace is Trace.TRACED and self.findings.get(cid):
            return STATUS_CLASS[
                min((f.status for f in self.findings[cid]), key=RANK.get)
            ]
        if unsupported(c):
            return "ref"
        return {
            Trace.DEFERRED: "ref",
            Trace.VIA_DEPENDENCIES: "int",
            Trace.PENDING: "nt",
            Trace.TRACED: "nt",
        }[c.trace]

    # --- Cards --------------------------------------------------------------

    def reviewer_line(self, f: Finding | CrossFinding) -> str:
        """The reviewer's override, beside (never instead of) the computed
        status; for a cross-claim finding, a confirmation too."""
        cross = isinstance(f, CrossFinding)
        r = (self.cross_reviews if cross else self.reviews).get(f.id)
        if r is None:
            return ""
        o = r.override
        who = f'<span class="who">({escape(o.reviewer)}, {o.date.isoformat()})</span>'
        if o.operation is review.Operation.CONFIRM:
            if r.stale:
                return (
                    '<p class="rv stale">Confirmation needs re-review: the values '
                    f"have changed since {escape(o.reviewer)} confirmed them on "
                    f"{o.date.isoformat()}. Earlier reason: {escape(o.reason)}</p>"
                )
            return f'<p class="rv">Reviewer confirmed: {escape(o.reason)} {who}</p>'
        if r.stale:
            return (
                '<p class="rv stale">Reviewer override needs re-review: the finding '
                f"has changed since {escape(o.reviewer)} gave it "
                f"{STATUS_LABEL[o.status]} on {o.date.isoformat()}. Earlier reason: "
                f"{escape(o.reason)}</p>"
            )
        return f'<p class="rv">Reviewer: {chip(o.status)} {escape(o.reason)} {who}</p>'

    def card(self, cid: str) -> str:
        c = self.claims[cid]
        fs = sorted(
            self.findings.get(cid, []),
            key=lambda f: (RANK[f.status], EFFECT_RANK[f.effect.value]),
        )
        state = self.claim_state(cid)
        counts = Counter(f.status for f in fs)
        chips = " ".join(
            chip(s, f"{n} {STATUS_LABEL[s].lower()}")
            for s, n in sorted(counts.items(), key=lambda kv: RANK[kv[0]])
        )
        if c.trace is Trace.DEFERRED:
            chips = '<span class="chip ref">Citation tracing deferred</span>'
        elif c.trace is Trace.VIA_DEPENDENCIES:
            chips = '<span class="chip int">Rests on other claims</span>'
        elif unsupported(c):
            chips = '<span class="chip ref">No stated support</span>'
        elif not fs:
            chips = '<span class="chip nt">Not traced yet</span>'

        extra = ""
        if c.depends_on:
            links = ", ".join(
                f'<a href="#card-{d}" class="idlink st-{self.claim_state(d)}">{d}</a>'
                for d in c.depends_on
                if d in self.claims
            )
            extra += (
                f'<p class="note">Rests on {links}. Interpretations are not traced to '
                "code or data themselves; their support is the claims they rest on.</p>"
            )
        if c.citations:
            extra += (
                f'<p class="note">Cites {escape("; ".join(c.citations))}. Checking '
                "claims against cited work is deferred (decision 0005); the claim is "
                "counted, not traced.</p>"
            )
        if unsupported(c):
            extra += (
                '<p class="note">The paper gives no data, analysis, or citation '
                "for this claim, so there is nothing to trace it to.</p>"
            )
        elif c.trace is Trace.PENDING:
            extra += '<p class="note">Not traced to Methods, code, or data yet.</p>'
        tests = ""
        for x in self.rec.context:
            if x.claim_id != cid:
                continue
            lines = " ".join(t for t in (x.assumes, x.data) if t)
            if x.scope:
                tests += (
                    f'<li><span class="tnum">{escape(x.scope.capitalize())}</span> '
                    f"“{escape(x.test)}”"
                    f"{f' <span class=why>{escape(lines)}</span>' if lines else ''}</li>"
                )
            else:
                extra += f'<p class="note">{escape("The test: " + lines)}</p>'
        if tests:
            tests = (
                '<div class="tests"><p class="note">The tests this claim reports, '
                f'as the findings number them:</p><ul class="tests">{tests}</ul></div>'
            )
        for i, g in enumerate(self.gaps, start=1):
            if cid in g.claims:
                extra += (
                    f'<p class="note">Affected by <a href="#gap-{i}">gap {i}</a> in '
                    f"the materials: {escape(g.missing)}</p>"
                )

        items = []
        for f in fs:
            facet = f.facet.value if f.facet else "whole claim"
            effect = (
                EFFECT_LABEL[f.effect.value]
                if f.status is not Status.CONSISTENT
                else ""
            )
            silent = ""
            if f.not_described_in:
                silent = (
                    '<p class="silent">Silent: '
                    + ", ".join(SOURCE_LABEL[s] for s in f.not_described_in)
                    + "</p>"
                )
            items.append(
                f'<li class="finding {STATUS_CLASS[f.status]}" data-finding-id="{escape(f.id)}" '
                f'data-status="{f.status.value}" data-key="{effect_key(f)}">'
                f'<div class="f-head">{chip(f.status)}'
                f'<span class="facet">{facet}{f" · {escape(f.scope)}" if f.scope else ""}</span>'
                f"{f'<span class=effect>{effect}</span>' if effect else ''}</div>"
                f'<p class="f-sum">{escape(f.summary)}</p>{off_line(f)}{basis_line(f)}{silent}'
                f"{self.reviewer_line(f)}"
                f'<details class="ev-box"><summary>Evidence ({len(f.observations)})</summary>'
                f'<ul class="evs">{"".join(evidence(o, self) for o in f.observations)}</ul>'
                "</details></li>"
            )

        cross = [x for x in self.cross or () if cid in x.claim_ids]
        if cross:
            extra += (
                '<p class="note">Values printed here and in other claims '
                '(<a href="#cross">cross-claim checks</a>):</p><ul class="cross">'
                + "".join(self.cross_item(x, cid) for x in cross)
                + "</ul>"
            )

        is_open = " open" if state in ("dif", "nd") else ""
        untraced = ' data-untraced=""' if not fs else ""
        a = c.anchor
        return f"""
<details class="card st-{state}" id="card-{cid}"{is_open} data-type="{c.type.value}"
  data-section="{self.section_of(cid)}" data-order="{self.reading_order(cid)}"{untraced}
  data-claim-id="{escape(cid)}" data-claim-type="{c.type.value}">
  <summary>
    <span class="cid">{cid}</span>
    <span class="ctype">{TYPE_LABEL[c.type]}</span>
    <span class="chips">{chips}</span>
    <span class="cquote">{self.quoted(a)}</span>
  </summary>
  <div class="card-body">
    <p class="where-line">{escape(loc(a, self.text))} · <button type="button" class="to-text" data-cid="{cid}">Show in text</button></p>
    {tests}
    {facet_table(fs)}
    {extra}
    {f'<ol class="findings">{"".join(items)}</ol>' if items else ""}
  </div>
</details>"""

    def cross_item(self, x: CrossFinding, here: str | None = None) -> str:
        """A cross-claim finding: its status, summary, the rules that joined
        the values, and each value's place, linked to the other claims."""
        rules = ", ".join(RULE_LABEL[r] for r in x.rules)
        places = "; ".join(
            (
                cid
                if cid == here
                else f'<a href="#card-{cid}" class="idlink '
                f'st-{self.claim_state(cid)}">{cid}</a>'
            )
            + f": “{escape(a.quote)}” ({escape(loc(a, self.text))})"
            for cid, a in crosscheck.quotes(x)
        )
        return (
            f'<li class="{STATUS_CLASS[x.status]}" data-cross-id="{escape(x.id)}">'
            f"{chip(x.status)} "
            f'{escape(x.summary)} <span class="why">Joined because {rules}; '
            f"confirmed: {escape(x.reason)} {places}</span>"
            f"{self.reviewer_line(x)}</li>"
        )

    # --- Manuscript column ----------------------------------------------------

    def marked(self, key: str) -> str:
        """The paragraph's text, exactly as extracted, with each claim marked.

        The claim labels added inside it are marked ``data-not-text`` so the
        review page counts characters in the extracted text alone.
        """
        p = self.paras[key]
        spans = sorted(
            (self.claims[cid].anchor.char_start, self.claims[cid].anchor.char_end, cid)
            for cid, k in self.claim_para.items()
            if k == key
        )
        out, pos = [], 0
        for s, e, cid in spans:
            # overlapping claims: the later one is marked from where the other ends
            s = max(s, pos)
            if s >= e:
                continue
            out.append(self.with_equations(p.text[pos:s], p.section, p.number, pos))
            out.append(
                f'<a class="mark st-{self.claim_state(cid)}" href="#card-{cid}" '
                f'data-cid="{cid}">{self.with_equations(p.text[s:e], p.section, p.number, s)}'
                f"<sup data-not-text>{cid}</sup></a>"
            )
            pos = e
        out.append(self.with_equations(p.text[pos:], p.section, p.number, pos))
        return (
            f'<span class="ms-text" data-section="{escape(p.section)}" '
            f'data-paragraph="{p.number}">{"".join(out)}</span>'
        )

    def cids_in(self, key: str) -> str:
        return " ".join(cid for cid, k in self.claim_para.items() if k == key)

    def section_block(self, major: int, keys: list[str]) -> str:
        title = self.sections.title(Place(major, 0))
        ms, heading = [], None
        for k in keys:
            h = self.para_heading(k)
            if self.is_heading(
                k
            ):  # a heading that holds a claim is shown as the heading
                ms.append(
                    f'<h3 class="ms-h ms-claim" data-cids="{self.cids_in(k)}">'
                    f"{self.marked(k)}</h3>"
                )
                heading = h
                continue
            if h and h != heading:
                ms.append(f'<h3 class="ms-h">{escape(h)}</h3>')
            heading = h
            ms.append(
                f'<p class="ms-p" data-cids="{self.cids_in(k)}"><span class="pnum" '
                f"data-not-text>{k}</span>{self.marked(k)}</p>"
            )
        cids = sorted(
            (cid for cid, k in self.claim_para.items() if k in keys),
            key=self.reading_order,
        )
        fs = [f for cid in cids for f in self.findings.get(cid, [])]
        counts = Counter(f.status for f in fs)
        chips = " ".join(
            chip(st, f"{n} {STATUS_LABEL[st].lower()}")
            for st, n in sorted(counts.items(), key=lambda kv: RANK[kv[0]])
        )
        return f"""
<details class="major" id="sec-{major}" data-section="{major}" open>
  <summary><h2>{escape(title)}</h2><span class="sec-n">{plural(len(cids), "claim")} · {plural(len(fs), "finding")}</span>
    <span class="chips">{chips}</span></summary>
  <div class="split">
    <article class="ms" aria-label="{escape(title)}: manuscript text with claims marked">
      {KEY}
      {"".join(ms)}
    </article>
    <section class="cards" aria-label="{escape(title)}: claim cards">
      {"".join(self.card(cid) for cid in cids)}
    </section>
  </div>
</details>"""

    # --- Summary and filters ------------------------------------------------

    def review_line(self) -> str:
        """Overrides, counted apart: the filters use the computed statuses."""
        if not (self.reviews or self.orphans):
            return ""
        n_applied = sum(r.applies for r in self.reviews.values())
        n_stale = sum(r.stale for r in self.reviews.values())
        parts = [f"{plural(n_applied, 'finding')} with a reviewer override"]
        if n_stale:
            parts.append(f"{plural(n_stale, 'override')} needing re-review")
        if self.orphans:
            parts.append(
                f"{plural(len(self.orphans), 'override')} of findings no longer in the record"
            )
        return (
            f'<p class="uncovered">Reviewer overrides: {"; ".join(parts)}. Filters '
            "use the computed outcome.</p>"
        )

    def filters(self) -> str:
        by_type = Counter(c.type for c in self.rec.claims)
        by_status = Counter(f.status for f in self.rec.findings)
        untraced = [c for c in self.rec.claims if not self.findings.get(c.id)]
        kinds = sorted(
            {
                {
                    Trace.VIA_DEPENDENCIES: "interpretation",
                    Trace.DEFERRED: "citation",
                }.get(c.trace, "pending")
                for c in untraced
            }
        )
        type_boxes = [
            box("types", t.value, TYPE_LABEL[t], by_type[t])
            for t in TYPE_ORDER
            if by_type.get(t)
        ]
        outcome_boxes = [
            box("outcomes", st.value, STATUS_LABEL[st], by_status.get(st, 0))
            for st in sorted(STATUS_LABEL, key=RANK.get)
        ]
        label = f"Not traced ({', '.join(kinds)})" if kinds else "Not traced"
        outcome_boxes.append(box("outcomes", "untraced", label, len(untraced)))
        claims_in = Counter(self.section_of(c.id) for c in self.rec.claims)
        majors = sorted(self.by_major)
        section_boxes = [
            box("sections", str(m), self.sections.title(Place(m, 0)), claims_in[m])
            for m in majors
        ]
        return (
            filter_row("types", "Claim type", type_boxes)
            + filter_row("outcomes", "Finding", outcome_boxes)
            + filter_row("sections", "Section", section_boxes)
        )


def unsupported(c: Claim) -> bool:
    """Whether a claim states no support at all, and so has nothing to trace."""
    return c.type is ClaimType.NO_STATED_SUPPORT and c.trace is Trace.PENDING


def chip(status: Status, text: str | None = None) -> str:
    return (
        f'<span class="chip {STATUS_CLASS[status]}">'
        f"{escape(text or STATUS_LABEL[status])}</span>"
    )


def loc(anchor, text: ManuscriptText) -> str:
    """Where an anchor points, in a few words; ``text`` names the pages."""
    if anchor.kind == "manuscript":
        page = text.name(anchor.page).replace("page", "p.", 1) if anchor.page else ""
        page = f" · {page}" if page else ""
        return f"{anchor.section} ¶{anchor.paragraph}{page}"
    if anchor.kind == "code":
        lines = (
            f"{anchor.line_start}"
            if anchor.line_start == anchor.line_end
            else f"{anchor.line_start}–{anchor.line_end}"
        )
        at = f" @ {anchor.commit}" if anchor.commit else ""
        return f"{anchor.file.removeprefix('code/')}:{lines}{at}"
    parts = [anchor.file.removeprefix("data/")]
    if anchor.field:
        parts.append(anchor.field)
    return " · ".join(parts)


def evidence(o: Observation, page: _Page) -> str:
    a = o.anchor
    text = page.text
    if a.kind == "code":
        body = f'<pre class="code"><code>{escape(a.quote)}</code></pre>'
    elif a.kind == "manuscript":
        body = f'<blockquote class="msq">{page.quoted(a)}</blockquote>'
    else:
        rows = [
            ("Value", a.quote),
            ("Selection", a.selection),
            ("How obtained", a.derivation),
            ("Derivation", a.produced_by.script if a.produced_by else None),
        ]
        body = (
            '<dl class="dq">'
            + "".join(f"<dt>{k}</dt><dd>{escape(v)}</dd>" for k, v in rows if v)
            + "</dl>"
        )
    return (
        f'<li class="ev"><div class="ev-head"><span class="src src-{o.source.value}">'
        f"{SOURCE_LABEL[o.source]}</span>"
        f'<span class="where">{escape(loc(a, text))} · {OBTAINED_LABEL[o.obtained.value]}</span>'
        f'</div><p class="stmt">{escape(o.statement)}</p>{body}</li>'
    )


def row_key(f: Finding) -> str:
    name = f.facet.value if f.facet else "whole claim"
    return f"{name} · {f.scope}" if f.scope else name


def facet_table(fs: list[Finding]) -> str:
    """Each facet against each source: what the sources say, at a glance.
    None for a claim compared whole, whose findings say it already."""
    facets = list(dict.fromkeys(row_key(f) for f in fs))
    if not any(f.facet for f in fs):
        return ""
    head = "".join(f"<th>{SOURCE_LABEL[s].split(' /')[0]}</th>" for s in TABLE_SOURCES)
    body = []
    for name in facets:
        cells = []
        for s in TABLE_SOURCES:
            states = []
            for f in fs:
                if row_key(f) != name:
                    continue
                if s in {o.source for o in f.observations}:
                    states.append(f.status)
                elif s in f.not_described_in:
                    states.append("silent")
            if "silent" in states:
                cells.append('<td><span class="cell nd-silent">silent</span></td>')
            elif states:
                st = min(states, key=RANK.get)
                cells.append(
                    f'<td><span class="cell {STATUS_CLASS[st]}">'
                    f"{STATUS_LABEL[st].lower()}</span></td>"
                )
            else:
                cells.append('<td><span class="cell none">·</span></td>')
        body.append(f'<tr><th scope="row">{escape(name)}</th>{"".join(cells)}</tr>')
    return (
        '<div class="tbl-wrap"><table class="facets"><thead><tr><th>Facet</th>'
        f"{head}</tr></thead><tbody>{''.join(body)}</tbody></table></div>"
    )


def off_line(f: Finding) -> str:
    """The stated values that do not agree with what was found, in bold."""
    off = [c for c in f.comparisons if not c.agrees()]
    if not off:
        return ""
    items = "; ".join(f"<b>{escape(c.values_text())}</b>" for c in off)
    return f'<p class="off">Do not agree: {items}</p>'


def basis_line(f: Finding) -> str:
    if f.basis is None:
        return ""
    tol = f" · tolerance: {escape(f.tolerance_text)}" if f.tolerance_text else ""
    return f'<p class="basis">Compared by {BASIS_LABEL[f.basis.value]}{tol}</p>'


def effect_key(f: Finding) -> int:
    """For "order by potential effect": issues first, by effect then status."""
    return (
        (f.status is Status.CONSISTENT) * 100
        + EFFECT_RANK[f.effect.value] * 10
        + RANK[f.status]
    )


def box(row: str, value: str, label: str, n: int) -> str:
    on = " disabled" if n == 0 else " checked"
    return (
        f'<label class="fbox{" zero" if n == 0 else ""}"><input type="checkbox" '
        f'name="{row}" value="{escape(value)}"{on}>{escape(label)} '
        f'<span class="fn">{n}</span></label>'
    )


def filter_row(row: str, title: str, boxes: list[str]) -> str:
    return (
        f'<div class="frow" data-row="{row}"><span class="ftitle">{title}</span>'
        f'<div class="fboxes">{"".join(boxes)}</div>'
        f'<span class="fall"><button type="button" data-all="{row}">all</button> · '
        f'<button type="button" data-none="{row}">none</button></span></div>'
    )


def _coverage(
    page: _Page, checks: status.Checks | None, exclusions: Sequence[Exclusion] | None
) -> str:
    if checks is None or checks.record_digest != status.digest(page.rec):
        return ""
    if checks.uncovered is None or checks.items is None:
        return ""
    where = "a claim or a quoted piece of evidence"
    if exclusions is not None:
        where = (
            "a claim, a quoted piece of evidence, or one of the "
            f'{len(exclusions)} <a href="#exclusions">exclusions</a> listed at the '
            "end, each with its reason"
        )
    if checks.uncovered == 0:
        text = (
            f"Coverage: all {checks.items} numbers, comparison words, and test names "
            f"in the audited text are inside {where}."
        )
    else:
        text = (
            f"Coverage: {checks.uncovered} of {checks.items} numbers, comparison "
            f"words, and test names in the audited text are not inside {where}."
        )
    return f'<p class="uncovered">{text}</p>'


def _exclusions(page: _Page, exclusions: Sequence[Exclusion] | None) -> str:
    if exclusions is None:
        return ""
    rows = "".join(
        f'<li><span class="pnum">{escape(e.paragraph)}</span><q>{escape(e.quote)}</q> '
        f'<span class="why">{escape(e.reason)}</span>'
        + (
            f' <a class="idlink st-{page.claim_state(e.restates)}" '
            f'href="#card-{e.restates}">{e.restates}</a>'
            if e.restates in page.claims
            else ""
        )
        + "</li>"
        for e in exclusions
    )
    return f"""  <details class="issues" id="exclusions">
    <summary><h2>Text excluded from claims</h2><span class="sec-n">{plural(len(exclusions), "passage")} with numbers or comparisons that the audit judged hold no separate claim</span></summary>
    <ol class="excl">{rows}</ol>
  </details>"""


def _absent(absent: Sequence[str]) -> str:
    """The files the code reads that are neither shared nor made by it."""
    if not absent:
        return ""
    names = ", ".join(escape(n) for n in absent[:10])
    more = f", and {len(absent) - 10} more" if len(absent) > 10 else ""
    return (
        f'<p class="note">The code reads {plural(len(absent), "file")} that '
        f"are not in the materials and that it does not make itself: {names}"
        f"{more} (listed in {materials.LIST.as_posix()}, with where each is "
        "read).</p>"
    )


def _gaps(page: _Page, absent: Sequence[str] = ()) -> str:
    """What the audit could not run or check from the materials given, and
    the files the code reads that are not there."""
    if not page.gaps:
        return (
            '<p class="uncovered">Gaps in the materials: none listed in the '
            f"manifest ({settings.MANIFEST}).</p>" + _absent(absent)
        )
    rows = []
    for i, g in enumerate(page.gaps, start=1):
        links = " ".join(
            f'<a class="idlink st-{page.claim_state(c)}" href="#card-{c}">{c}</a>'
            for c in g.claims
            if c in page.claims
        )
        rows.append(
            f'<li id="gap-{i}"><span class="pnum">{i}</span>{escape(g.missing)}'
            + (
                f' <span class="why">Instead: {escape(g.instead)}</span>'
                if g.instead
                else ""
            )
            + (f" {links}" if links else "")
            + "</li>"
        )
    return f"""<details class="issues" id="gaps" open>
    <summary><h2>Gaps in the materials</h2><span class="sec-n">{plural(len(page.gaps), "gap")}: what the audit could not run or check from what the authors shared</span></summary>
    <ol class="excl">{"".join(rows)}</ol>{_absent(absent)}
  </details>"""


def _cross(page: _Page) -> str:
    """The cross-claim findings, differences first."""
    if page.cross is None:
        return """<details class="issues" id="cross">
    <summary><h2>Cross-claim checks</h2><span class="sec-n">not done: the crosscheck step waits for an answer for this record</span></summary>
  </details>"""
    if not page.cross:
        return ""
    xs = sorted(page.cross, key=lambda x: x.status is not Status.DIFFERS)
    differ = sum(1 for x in xs if x.status is Status.DIFFERS)
    return f"""<details class="issues" id="cross"{" open" if differ else ""}>
    <summary><h2>Cross-claim checks</h2><span class="sec-n">{plural(len(xs), "value")} printed in more than one claim; {differ} {"differs" if differ == 1 else "differ"}</span></summary>
    <ul class="cross">{"".join(page.cross_item(x) for x in xs)}</ul>
  </details>"""


def _header(workspace: Path) -> tuple[str, str]:
    """The audit's header, and the page title taken from its first heading."""
    path = workspace / HEADER
    if path.is_file():
        header = path.read_text(encoding="utf-8")
        m = re.search(r"<h1[^>]*>(.*?)</h1>", header, re.DOTALL)
        title = re.sub(r"<[^>]+>", "", m.group(1)).strip() if m else workspace.name
        return header, f"{title} · Audit"
    name = escape(workspace.resolve().name)
    header = (
        f'<header class="top"><div class="eyebrow">Audit</div><h1>{name}</h1>'
        f'<p class="scope">Write this audit\'s own header in {HEADER}: the paper, '
        "what the audit covers, and where each material came from.</p></header>"
    )
    return header, f"{name} · Audit"


def render(workspace: Path) -> tuple[str, str]:
    """The report page for the workspace's reviewed record, as HTML, and the
    status paragraph in it."""
    path = workspace / RECORD
    if not path.is_file():
        raise FileNotFoundError(f"no record in {workspace}: {RECORD} is missing")
    draft = AuditRecord.model_validate_json(path.read_text(encoding="utf-8"))
    entries = review.load(workspace / review.LOG)
    sections = Sections(load_outline(workspace / OUTLINE), read_pages(workspace / TEXT))
    paragraphs = read_paragraphs(workspace / PARAGRAPHS)
    manifest = settings.load(workspace)
    page = _Page(
        draft,
        entries,
        paragraphs,
        sections,
        manifest.scope,
        read_text(workspace / TEXT),
        manifest.gaps,
    )
    page.cross = crosscheck.current(workspace, page.rec)
    page.cross_reviews, _ = review.current_cross(page.cross or (), entries)
    if (workspace / EQUATIONS_FILE).is_file():
        page.add_equations(
            json.loads((workspace / EQUATIONS_FILE).read_text(encoding="utf-8")),
            workspace / FOLDER,
        )

    absent = sorted(
        {
            r.name
            for r in materials.code_reads(workspace, manifest)
            if r.name and not r.found and not r.made
        }
    )
    checks = status.load_checks(workspace)
    standing = status.paragraph(draft, entries, checks=checks)
    exclusions = check.read_exclusions(workspace)
    coverage = _coverage(page, checks, exclusions)
    pending = sum(
        1 for c in page.rec.claims if c.trace is Trace.PENDING and not unsupported(c)
    )
    if coverage and pending:
        coverage = coverage.replace(
            "</p>", f" {plural(pending, 'claim')} not traced yet.</p>"
        )
    uncovered = [t for i, t in enumerate(sections.majors) if i not in page.by_major]
    header, title = _header(workspace)
    footer = workspace / FOOTER
    traced = sum(1 for c in page.rec.claims if page.findings.get(c.id))

    html = TEMPLATE.read_text(encoding="utf-8")
    for k, v in {
        "{{TITLE}}": escape(title),
        "{{HEADER}}": header,
        "{{FOOTER}}": footer.read_text(encoding="utf-8") if footer.is_file() else "",
        "{{SECTIONS}}": "".join(
            page.section_block(m, keys) for m, keys in sorted(page.by_major.items())
        ),
        "{{FILTERS}}": page.filters(),
        "{{REVIEW_LINE}}": f'<p class="uncovered">{escape(standing)}</p>'
        + page.review_line(),
        "{{UNCOVERED}}": escape(", ".join(uncovered)) or "none",
        "{{COVERAGE}}": coverage,
        "{{GAPS}}": _gaps(page, absent),
        "{{CROSS}}": _cross(page),
        "{{EXCLUSIONS}}": _exclusions(page, exclusions),
        "{{EQUATIONS}}": json.dumps(page.pictures),
        "{{N_CLAIMS}}": str(len(page.rec.claims)),
        "{{N_TRACED}}": str(traced),
        "{{N_FINDINGS}}": str(len(page.rec.findings)),
    }.items():
        html = html.replace(k, v)
    return html, standing


def write(workspace: Path) -> Path:
    """Render the report and write it to :data:`PAGE`; return its path. The
    status paragraph also goes in the workspace README."""
    out = workspace / PAGE
    html, standing = render(workspace)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    readme = workspace / "README.md"
    if readme.is_file():
        readme.write_text(
            status.update_block(readme.read_text(encoding="utf-8"), standing),
            encoding="utf-8",
        )
    return out
