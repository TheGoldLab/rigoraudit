# Copyright (c) 2026, Joshua I. Gold
# SPDX-License-Identifier: BSD-2-Clause
"""Compare the claims of a guided run with a reference audit of the same paper.

The reference is a finished record (``record/record.json``); the guided run
needs only accepted segment and decompose answers. Claims are matched by
their quoted words, since the two audits may number paragraphs and claims
differently (one may have read the XML, the other the PDF):

- same: one claim each, quoting mostly the same words;
- different extent: one claim each, but one quotes much more than the other;
- split differently: one claim on one side overlaps several on the other;
- missed: a reference claim no guided claim in its section overlaps;
- extra: a guided claim no reference claim overlaps. Claims in sections the
  other audit has no claims in (e.g. figure-supplement legends) are listed
  apart, missed or extra, since that audit may not have covered them.

For matched claims the report gives differences in type, in ``restates``,
and, for new results, in the facets quoted from the Results and the values
read from them. It is written as Markdown for the auditor to judge; it
quotes the paper, so save it in the audit's ``notes/``, never in this
repository.

Usage:
    uv run python scripts/compare_claims.py REFERENCE GUIDED OUT.md
"""

import argparse
import difflib
import re
import sys
import unicodedata
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from miragold import decompose, segment
from miragold.schema import RECORD, AuditRecord, ClaimType, Source
from miragold.settings import load

MIN_WORDS = 4
"""Fewest shared words in a row that link two claims."""
SAME = 0.8
"""Share of each claim's words the other must quote for "same"."""
LINK = 0.4
"""Share of the shorter claim's words the other must quote to link them."""


@dataclass
class Claim:
    """One claim as both audits can describe it."""

    id: str
    type: ClaimType
    section: str
    quote: str
    restates: str | None
    facets: dict[str, tuple[str, tuple[str, ...]]] = field(default_factory=dict)
    """Facet name to its Results quote and the values read from it."""
    words: list[str] = field(default_factory=list)


def words(text: str) -> list[str]:
    """The words and numbers of ``text``, lower case, with symbols dropped.

    >>> words("Mean RT was ∼0.5 s (n = 12).")
    ['mean', 'rt', 'was', '0.5', 's', 'n', '12']
    """
    text = unicodedata.normalize("NFKC", text).lower().replace("−", "-")
    return re.findall(r"\d+(?:\.\d+)?|[^\W\d_]+", text)


def shared(a: list[str], b: list[str]) -> int:
    """How many words of ``a`` and ``b`` fall in common runs of at least
    :data:`MIN_WORDS` words in a row, or of all of the shorter one.

    >>> shared("the cat sat on the mat".split(), "a cat sat on the rug".split())
    4
    >>> shared("12 ms".split(), "shift of 12 ms".split())
    2
    """
    least = min(MIN_WORDS, len(a), len(b))
    m = difflib.SequenceMatcher(None, a, b, autojunk=False)
    return sum(blk.size for blk in m.get_matching_blocks() if blk.size >= max(least, 1))


def _value(v: object) -> str:
    rel = getattr(v, "relation", None)
    rel = "" if rel is None or rel.value == "=" else rel.value
    unit = getattr(v, "unit", None) or ""
    return f"{v.name} {rel}{v.value:g}{unit}".strip()  # type: ignore[attr-defined]


def reference_claims(workspace: Path) -> list[Claim]:
    """Claims of a finished record, with the facets its findings quote from the Results."""
    r = AuditRecord.model_validate_json(
        (workspace / RECORD).read_text(encoding="utf-8")
    )
    out = []
    for c in r.claims:
        claim = Claim(c.id, c.type, c.anchor.section, c.anchor.quote, c.restates)
        for f in r.findings_for(c.id):
            if f.facet is None:
                continue
            for o in f.observations:
                if o.source is Source.RESULTS and f.facet.value not in claim.facets:
                    claim.facets[f.facet.value] = (
                        o.anchor.quote,  # type: ignore[union-attr]
                        tuple(_value(v) for v in o.values),
                    )
        out.append(claim)
    return out


def guided_claims(workspace: Path) -> list[Claim]:
    """Claims of accepted segment answers, with facets from accepted decompose answers."""
    manuscript = load(workspace).manuscript
    observed = decompose.results_observations(workspace, manuscript)
    out = []
    for c in segment.record_claims(workspace, manuscript):
        claim = Claim(c.id, c.type, c.anchor.section, c.anchor.quote, c.restates)
        for facet, o in observed.get(c.id, {}).items():
            claim.facets[facet.value] = (
                o.anchor.quote,  # type: ignore[union-attr]
                tuple(_value(v) for v in o.values),
            )
        out.append(claim)
    return out


def part(c: Claim) -> str:
    """The part of the paper a claim is in, for matching: its section, with a
    figure's title counted as part of its legend (some extractions print the
    title as the legend's first sentence).

    >>> part(Claim("F1.a", ClaimType.PROCEDURE, "Figure 1 title", "x", None))
    'Figure 1 legend'
    """
    return re.sub(r"^(Figure \d+) title$", r"\1 legend", c.section)


@dataclass
class Group:
    """Claims linked by shared words: some from each audit."""

    ref: list[Claim]
    guided: list[Claim]
    kind: str = ""


def match(ref: list[Claim], guided: list[Claim]) -> list[Group]:
    """Link claims that share words, and sort each linked group into a kind."""
    for c in (*ref, *guided):
        c.words = words(c.quote)
    links: dict[int, set[int]] = defaultdict(set)
    overlap: dict[tuple[int, int], int] = {}
    for i, r in enumerate(ref):
        for j, g in enumerate(guided):
            if part(r) != part(g):
                continue
            n = shared(r.words, g.words)
            if n and n >= LINK * min(len(r.words), len(g.words)):
                links[i].add(j)
                overlap[i, j] = n
    # Pair near-identical claims first, so that a sentence a legend repeats
    # does not tie them into a group with the other claims it appears in.
    paired_r, paired_g = set(), set()
    for (i, j), n in sorted(overlap.items(), key=lambda kv: -kv[1]):
        size = max(len(ref[i].words), len(guided[j].words))
        if i not in paired_r and j not in paired_g and n >= SAME * size:
            paired_r.add(i)
            paired_g.add(j)
            links[i] = {j}
    for i in links:
        if i not in paired_r:
            links[i] -= paired_g
    back: dict[int, set[int]] = defaultdict(set)
    for i, js in links.items():
        for j in js:
            back[j].add(i)
    groups, seen_r, seen_g = [], set(), set()
    for i in range(len(ref)):
        if i in seen_r:
            continue
        rs, gs, todo = {i}, set(), [("r", i)]
        while todo:
            side, k = todo.pop()
            for other in links[k] if side == "r" else back[k]:
                pool, mark = (gs, "g") if side == "r" else (rs, "r")
                if other not in pool:
                    pool.add(other)
                    todo.append((mark, other))
        seen_r |= rs
        seen_g |= gs
        groups.append(
            Group([ref[k] for k in sorted(rs)], [guided[k] for k in sorted(gs)])
        )
    groups += [Group([], [g]) for j, g in enumerate(guided) if j not in seen_g]
    ref_sections = {part(c) for c in ref}
    guided_sections = {part(c) for c in guided}
    for grp in groups:
        if not grp.guided:
            grp.kind = (
                "missed"
                if part(grp.ref[0]) in guided_sections
                else "missed, unaudited section"
            )
        elif not grp.ref:
            grp.kind = (
                "extra"
                if part(grp.guided[0]) in ref_sections
                else "extra, unaudited section"
            )
        elif len(grp.ref) == 1 and len(grp.guided) == 1:
            r, g = grp.ref[0], grp.guided[0]
            n = overlap[ref.index(r), guided.index(g)]
            grp.kind = (
                "same"
                if n >= SAME * max(len(r.words), len(g.words))
                else "different extent"
            )
        else:
            grp.kind = "split differently"
    return groups


def differences(r: Claim, g: Claim) -> list[str]:
    """What two matched claims say differently, one line each."""
    out = []
    n = shared(r.words, g.words)
    if n < SAME * max(len(r.words), len(g.words)):
        if n == len(r.words):
            out.append(
                "extent: the guided quote holds all of the reference quote, and more"
            )
        elif n == len(g.words):
            out.append(
                "extent: the reference quote holds all of the guided quote, and more"
            )
    if r.type != g.type:
        out.append(f"type: reference {r.type}, guided {g.type}")
    if bool(r.restates) != bool(g.restates):
        out.append(
            f"restates: reference {r.restates or 'nothing'}, guided {g.restates or 'nothing'}"
        )
    if ClaimType.NEW_RESULT not in (r.type, g.type):
        return out
    for facet in sorted(set(r.facets) | set(g.facets)):
        if facet not in g.facets:
            out.append(f"{facet}: only the reference quotes it: “{r.facets[facet][0]}”")
        elif facet not in r.facets:
            out.append(
                f"{facet}: only the guided run quotes it: “{g.facets[facet][0]}”"
            )
        else:
            (rq, rv), (gq, gv) = r.facets[facet], g.facets[facet]
            if shared(words(rq), words(gq)) < 0.5 * min(len(words(rq)), len(words(gq))):
                out.append(f"{facet}: quotes differ: reference “{rq}”; guided “{gq}”")
            if sorted(rv) != sorted(gv):
                out.append(
                    f"{facet} values: reference {', '.join(rv) or 'none'}; "
                    f"guided {', '.join(gv) or 'none'}"
                )
    return out


ORDER = [
    "same",
    "different extent",
    "split differently",
    "missed",
    "missed, unaudited section",
    "extra",
    "extra, unaudited section",
]
EXPLAIN = {
    "same": "One claim each, quoting mostly the same words. Listed only where they differ in type, restates, or facets.",
    "different extent": "One claim each, but one quotes much more of the text.",
    "split differently": "The same words cut into a different number of claims.",
    "missed": "Reference claims the guided run has no claim for, in sections the guided run covered.",
    "missed, unaudited section": "Reference claims in sections where the guided run has no claims at all.",
    "extra": "Guided claims the reference has no claim for, in sections the reference audited.",
    "extra, unaudited section": "Guided claims in sections where the reference has no claims at all.",
}


def _line(side: str, c: Claim) -> str:
    return f"- {side} **{c.id}** ({c.type}, {c.section}): “{c.quote}”"


def report(groups: list[Group], ref_name: str, guided_name: str) -> str:
    """The comparison as Markdown."""
    by_kind: dict[str, list[Group]] = defaultdict(list)
    for grp in groups:
        by_kind[grp.kind].append(grp)
    out = [
        f"# Claims compared: {guided_name} against {ref_name}",
        "",
        "Written by `scripts/compare_claims.py`. Claims are matched by their quoted words.",
        "",
        "| Kind | Groups | Reference claims | Guided claims |",
        "|---|---|---|---|",
    ]
    for kind in ORDER:
        gs = by_kind[kind]
        out.append(
            f"| {kind} | {len(gs)} | {sum(len(g.ref) for g in gs)} | {sum(len(g.guided) for g in gs)} |"
        )
    for kind in ORDER:
        gs = by_kind[kind]
        if not gs:
            continue
        body = []
        for grp in gs:
            diffs = (
                differences(grp.ref[0], grp.guided[0])
                if len(grp.ref) == 1 and len(grp.guided) == 1
                else []
            )
            if kind == "same" and not diffs:
                continue
            body += [_line("reference", c) for c in grp.ref]
            body += [_line("guided", c) for c in grp.guided]
            body += [f"  - {d}" for d in diffs]
            body.append("")
        out += ["", f"## {kind.capitalize()}", "", EXPLAIN[kind], ""]
        out += body or ["None differ.", ""]
    return "\n".join(out).rstrip() + "\n"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("reference", type=Path, help="the reference audit's workspace")
    p.add_argument("guided", type=Path, help="the guided run's workspace")
    p.add_argument("out", type=Path, help="the Markdown file to write")
    a = p.parse_args(argv)
    groups = match(reference_claims(a.reference), guided_claims(a.guided))
    a.out.write_text(report(groups, a.reference.name, a.guided.name), encoding="utf-8")
    counts = defaultdict(int)
    for grp in groups:
        counts[grp.kind] += 1
    print(", ".join(f"{k}: {counts[k]}" for k in ORDER), "→", a.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
