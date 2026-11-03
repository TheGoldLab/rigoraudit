# Copyright (c) 2026, Joshua I. Gold
# SPDX-License-Identifier: BSD-2-Clause
"""Draft the report's header from the manifest (decision 0011).

The report opens with the audit's own header, ``report/header.html``
(:data:`rigoraudit.report.HEADER`): the paper, what the audit covers, and
where each material came from. Once the other steps are done, this step
hands an assistant the manifest and the paper's first page
(``rigoraudit/instructions/header.md``), and the assistant answers with
the header's parts as plain text: a short heading, the paper's title word
for word, where it was published, what the audit covers, and a line for
each material. The tool checks the title is on the first page and that
the manuscript and the code (if the manifest names any) each have a line,
then writes the header itself, so the reply cannot put markup in the page.

The step is not handed off once ``report/header.html`` exists, whoever
wrote it; edit that file to change the header.
"""

from __future__ import annotations

import datetime
from collections import Counter
from html import escape
from pathlib import Path

from rigoraudit import handoffs, instructions
from rigoraudit.extract import TEXT, read_pages
from rigoraudit.handoffs import AnswerError, Problem, Problems
from rigoraudit.report import HEADER
from rigoraudit.schema import Frozen, NonEmptyStr
from rigoraudit.settings import MANIFEST, Settings

STEP = "header"
NAME = "header"
NOUNS = {"materials": "material"}


class Handoff(Frozen):
    name: NonEmptyStr
    instructions: NonEmptyStr
    manifest: NonEmptyStr
    """The manifest's text."""
    first_page: NonEmptyStr
    """The paper's first page, from its text layer."""
    scope: tuple[str, ...]
    materials: tuple[str, ...]
    """The materials that must each have a line, e.g. ``("Manuscript", "Code")``."""


class Material(Frozen):
    name: NonEmptyStr
    text: NonEmptyStr


class HeaderAnswer(Frozen):
    instructions: NonEmptyStr
    """The instructions the answer followed, e.g. ``"header v1"``."""
    heading: NonEmptyStr
    """E.g. ``"Lee et al. (2026)"``."""
    title: NonEmptyStr
    """The paper's title, word for word from its first page."""
    published: str = ""
    covers: NonEmptyStr
    materials: tuple[Material, ...]


class Accepted(Frozen):
    handoff: NonEmptyStr
    drafted_by: NonEmptyStr
    imported: NonEmptyStr
    """Date the answer was accepted, ``YYYY-MM-DD``."""
    answer: HeaderAnswer


def parse_answer(text: str) -> HeaderAnswer:
    """Read an answer: bare JSON, or the first fenced block in a reply."""
    return handoffs.parse_reply(text, HeaderAnswer, NOUNS)


def read_accepted(workspace: Path) -> list[Accepted]:
    return handoffs.read_answers(workspace, STEP, Accepted)


def plan_handoffs(workspace: Path, settings: Settings) -> list[Handoff]:
    """The handoff still needed: none once the header exists or is answered."""
    if (workspace / HEADER).is_file() or read_accepted(workspace):
        return []
    return [
        Handoff(
            name=NAME,
            instructions=instructions.load(STEP).label,
            manifest=(workspace / MANIFEST).read_text(encoding="utf-8"),
            first_page=read_pages(workspace / TEXT)[0],
            scope=settings.scope,
            materials=("Manuscript", "Code") if settings.code else ("Manuscript",),
        )
    ]


def render_handoff(handoff: Handoff) -> str:
    """The text to paste: the instructions, then the manifest and first page."""
    task = (
        f"The audited sections: {', '.join(handoff.scope)}. Give a line for each "
        f"of: {', '.join(handoff.materials)}."
    )
    body = [
        "",
        task,
        "",
        f"## The manifest ({MANIFEST})",
        "",
        "```yaml",
        handoff.manifest.rstrip(),
        "```",
        "",
        "## The paper's first page",
        "",
        "```",
        handoff.first_page.rstrip(),
        "```",
    ]
    what = "the manifest and the first page below"
    return handoffs.render(STEP, handoff.name, handoff.instructions, what, body)


def write_handoffs(workspace: Path, settings: Settings) -> list[Path]:
    """Write the handoff if one is needed; return the file to paste."""
    return handoffs.write_handoffs(
        workspace,
        STEP,
        ((h.name, h, render_handoff(h)) for h in plan_handoffs(workspace, settings)),
        answered={a.handoff for a in read_accepted(workspace)},
    )


def pending_handoffs(workspace: Path) -> list[Handoff]:
    answered = {a.handoff for a in read_accepted(workspace)}
    return handoffs.read_pending(workspace, STEP, Handoff, answered)


def _words(text: str) -> str:
    return " ".join(text.split())


def check_answer(answer: HeaderAnswer, handoff: Handoff) -> Problems:
    """Everything wrong with an answer: the title as printed, and a line for
    each material, once."""
    problems = handoffs.version_problem(STEP, answer.instructions)
    if _words(answer.title) not in _words(handoff.first_page):
        problems.add(
            "title-not-found",
            f"The title is not on the first page word for word: {answer.title!r}",
        )
    given = Counter(m.name for m in answer.materials)
    for name in handoff.materials:
        if not given[name]:
            problems.add("material-missing", f"There is no line for {name}.")
    for name in sorted(n for n, k in given.items() if k > 1):
        problems.add("material-twice", f"{name} has more than one line.")
    return problems


def render_header(answer: HeaderAnswer) -> str:
    """The header's HTML, every part escaped."""
    paper = escape(answer.title) + (
        f" {escape(answer.published)}" if answer.published else ""
    )
    rows = "\n".join(
        f"  <div><dt>{escape(m.name)}</dt><dd>{escape(m.text)}</dd></div>"
        for m in answer.materials
    )
    return (
        '<header class="top">\n'
        '  <div class="eyebrow">Audit</div>\n'
        f"  <h1>{escape(answer.heading)}</h1>\n"
        f'  <p class="paper-title">{paper}</p>\n'
        f'  <p class="scope">{escape(answer.covers)}</p>\n'
        "</header>\n"
        f'<dl class="meta">\n{rows}\n</dl>\n'
    )


def import_answer(
    workspace: Path,
    reply: str,
    drafted_by: str,
    handoff: str | None = None,
    today: datetime.date | None = None,
) -> tuple[Path | None, list[Problem]]:
    """Check a reply and, if it has no problems, save it and write the header.

    Returns the saved answer, or ``None`` and the problems to give back to the
    assistant.
    """
    try:
        answer = parse_answer(reply)
    except AnswerError as e:
        return None, e.problems
    pending = [h for h in pending_handoffs(workspace) if handoff in (None, h.name)]
    if not pending:
        return None, [
            Problem(
                "no-handoff-waiting",
                "No handoff is waiting for an answer; run rigoraudit handoff header.",
            )
        ]
    chosen = pending[0]
    if problems := check_answer(answer, chosen):
        return None, problems
    path = workspace / HEADER
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_header(answer), encoding="utf-8")
    accepted = Accepted(
        handoff=chosen.name,
        drafted_by=drafted_by,
        imported=(today or datetime.date.today()).isoformat(),
        answer=answer,
    )
    return handoffs.save_answer(workspace, STEP, chosen.name, accepted), []
