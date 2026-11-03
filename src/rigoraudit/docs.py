# Copyright (c) 2026, Joshua I. Gold
# SPDX-License-Identifier: BSD-2-Clause
"""Read the authors' documentation before running their code (decision 0013).

:func:`list_documentation` finds every file in ``materials/`` that documents
the code or data: READMEs and other prose, files that name dependencies, the
text cells of each Jupyter notebook, and the opening comment of each script
the run will start (``settings › run ›
scripts`` in the manifest). An assistant reads them (``rigoraudit/
instructions/docs.md``) and says, under fixed headings, what each one says
about running the code, quoting it word for word. Accepted answers are kept
in ``work/docs/answers/`` with a checksum of each file read, and
:func:`unread` lists the files no accepted answer covers at their current
content, so a run can wait until every one has been read.

PDF documents are listed and handed off to be attached, but their quotes
cannot be checked yet, and the record says so.
"""

from __future__ import annotations

import datetime
import hashlib
import os
import re
from collections.abc import Sequence
from enum import StrEnum
from itertools import takewhile
from pathlib import Path, PurePosixPath

from rigoraudit import codeindex, handoffs, instructions
from rigoraudit.handoffs import AnswerError, Problem, Problems
from rigoraudit.schema import Frozen, NonEmptyStr
from rigoraudit.settings import Settings
from rigoraudit.words import plural

STEP = "docs"
MAX_CHARS = 30000
"""Documentation text per handoff; a longer file goes in one of its own."""
MAX_TEXT_BYTES = 200_000
"""Larger text files are taken to be data, not documentation."""
HEADER_LINES = 80
"""Most lines of a script's opening comment."""
NOUNS = {"files": "file", "notes": "note", "disagreements": "disagreement"}

PROSE = re.compile(
    r"(?<![a-z])(read[ _-]?me|install|notes?|changelog|changes|usage|howto"
    r"|codebook|manual|guide|documentation)(?![a-z])",
    re.IGNORECASE,
)
"""Names of prose documentation, matched anywhere in the file name."""
PROSE_SUFFIXES = {".md", ".rst", ".markdown"}
DEPENDENCY_FILES = {
    "requirements.txt", "environment.yml", "environment.yaml", "pyproject.toml",
    "setup.py", "setup.cfg", "pipfile", "description", "renv.lock",
    "project.toml", "manifest.toml", "makefile", "dockerfile", "contents.m",
    "package.json", "install.r",
}  # fmt: skip
DEPENDENCY_SUFFIXES = {".prj"}


class Kind(StrEnum):
    PROSE = "documentation"
    PDF = "PDF document"
    DEPENDENCIES = "dependencies"
    HEADER = "script's opening comment"
    NOTEBOOK = "notebook's text cells"


class Heading(StrEnum):
    RUN = "run"
    SOFTWARE = "software"
    DATA = "data"
    SETTINGS = "settings"
    OUTPUTS = "outputs"
    PROBLEMS = "problems"


class DocFile(Frozen):
    file: NonEmptyStr
    """Path relative to ``materials/``."""
    kind: Kind
    text: str | None
    """The text read; ``None`` for a PDF."""
    sha256: NonEmptyStr
    """Of the text read, or of the file for a PDF."""


# --- Finding the documentation ----------------------------------------------


def _kind(name: str, size: int) -> Kind | None:
    lower = name.lower()
    suffix = PurePosixPath(lower).suffix
    if lower in DEPENDENCY_FILES or suffix in DEPENDENCY_SUFFIXES:
        return Kind.DEPENDENCIES
    if lower.startswith("requirements") and suffix == ".txt":
        return Kind.DEPENDENCIES
    if suffix == ".pdf":
        return Kind.PDF if PROSE.search(lower) else None
    if size > MAX_TEXT_BYTES:
        return None
    if suffix in PROSE_SUFFIXES or PROSE.search(lower):
        return Kind.PROSE
    return None


def opening_comment(lines: Sequence[str], suffix: str) -> str:
    """A script's opening comment block, after any ``function`` or ``#!``
    line; for Python, its docstring or leading ``#`` lines."""
    rest = list(lines)
    while rest and (
        not rest[0].strip() or rest[0].lstrip().startswith(("function", "#!"))
    ):
        rest.pop(0)
    first = rest[0].lstrip() if rest else ""
    if suffix == ".py" and first[:3] in ('"""', "'''"):
        quote = first[:3]
        ends = [
            i for i, ln in enumerate(rest) if quote in (first[3:] if i == 0 else ln)
        ]
        return "\n".join(rest[: ends[0] + 1 if ends else HEADER_LINES][:HEADER_LINES])
    mark = "%" if suffix == ".m" else "#"
    out = list(takewhile(lambda ln: ln.lstrip().startswith(mark), rest))
    return "\n".join(out[:HEADER_LINES])


def _sha(text: str | bytes) -> str:
    data = text.encode("utf-8") if isinstance(text, str) else text
    return hashlib.sha256(data).hexdigest()


def list_documentation(
    workspace: Path, settings: Settings, scripts: Sequence[str] = ()
) -> list[DocFile]:
    """Every documentation file in ``materials/``, the text cells of each
    notebook, and the opening comment of each script in ``scripts`` (and
    ``settings.run_scripts``).

    The code folder is read at the manifest's commit when it is a git
    repository. The manuscript's folder is skipped: the paper and its
    supplements are not documentation of the code. A PDF counts only when its
    name says it is documentation (a README, manual, guide, or codebook).
    """
    materials = workspace / "materials"
    code = settings.code
    code_root = materials / code.path if code else None
    commit = code.commit if code else None
    manuscript_folder = (materials / settings.manuscript).parent
    if manuscript_folder == materials:
        manuscript_folder = None
    found: list[DocFile] = []

    def add_text(file: str, kind: Kind, text: str) -> None:
        found.append(DocFile(file=file, kind=kind, text=text, sha256=_sha(text)))

    def add_notebook(file: str, text: str | None) -> None:
        if text and (cells := codeindex.notebook_text(text)):
            add_text(f"{file} (text cells)", Kind.NOTEBOOK, cells)

    if code_root is not None and code_root.is_dir():
        for name in codeindex.list_files(code_root, commit):
            path = code_root / name
            if path.suffix.lower() == codeindex.NOTEBOOK:
                add_notebook(
                    f"{code.path}/{name}", codeindex.code_text(code_root, name, commit)
                )
                continue
            size = path.stat().st_size if path.is_file() else 0
            kind = _kind(PurePosixPath(name).name, size)
            if kind is None:
                continue
            file = f"{code.path}/{name}"
            if kind is Kind.PDF and path.is_file():
                found.append(
                    DocFile(
                        file=file, kind=kind, text=None, sha256=_sha(path.read_bytes())
                    )
                )
                continue
            lines = codeindex.code_lines(code_root, name, commit)
            if lines is not None:
                add_text(file, kind, "\n".join(lines))
    for dirpath, dirnames, filenames in os.walk(materials):
        here = Path(dirpath)
        dirnames[:] = sorted(
            d
            for d in dirnames
            if not d.startswith(".") and here / d not in (code_root, manuscript_folder)
        )
        for f in sorted(filenames):
            path = here / f
            file = path.relative_to(materials).as_posix()
            if f.startswith(".") or file == settings.manuscript:
                continue
            if path.suffix.lower() == codeindex.NOTEBOOK:
                add_notebook(file, path.read_text(encoding="utf-8", errors="replace"))
                continue
            kind = _kind(f, path.stat().st_size)
            if kind is Kind.PDF:
                found.append(
                    DocFile(
                        file=file, kind=kind, text=None, sha256=_sha(path.read_bytes())
                    )
                )
            elif kind is not None:
                add_text(file, kind, path.read_text(encoding="utf-8", errors="replace"))
    for script in dict.fromkeys([*settings.run_scripts, *scripts]):
        rel = script.removeprefix("materials/")
        lines = None
        if code is not None and rel.startswith(code.path + "/"):
            lines = codeindex.code_lines(code_root, rel[len(code.path) + 1 :], commit)
        elif (materials / rel).is_file():
            lines = (materials / rel).read_text(errors="replace").split("\n")
        if lines is None:
            raise FileNotFoundError(f"script to run not found in materials/: {script}")
        header = opening_comment(lines, PurePosixPath(rel).suffix.lower())
        add_text(f"{rel} (opening comment)", Kind.HEADER, header or "(none)")
    return sorted(found, key=lambda d: d.file)


# --- The answer -------------------------------------------------------------


class Note(Frozen):
    heading: Heading
    quote: NonEmptyStr
    states: NonEmptyStr


class FileNotes(Frozen):
    file: NonEmptyStr
    notes: tuple[Note, ...] = ()
    says_nothing: tuple[Heading, ...] = ()


class Disagreement(Frozen):
    file: NonEmptyStr
    quote: NonEmptyStr
    states: NonEmptyStr
    """What it disagrees with, and how."""


class DocsAnswer(Frozen):
    instructions: NonEmptyStr
    files: tuple[FileNotes, ...]
    disagreements: tuple[Disagreement, ...] = ()


def parse_answer(text: str) -> DocsAnswer:
    return handoffs.parse_reply(text, DocsAnswer, NOUNS)


def _flat(text: str) -> str:
    return " ".join(text.split())


def check_answer(answer: DocsAnswer, given: Sequence[DocFile]) -> Problems:
    """Everything wrong with ``answer``, as sentences; empty if nothing is.

    Quotes are matched with runs of spaces and line breaks treated as one
    space, since documentation is often wrapped. A PDF's quotes are not
    checked.
    """
    problems = handoffs.version_problem(STEP, answer.instructions)
    by_file = {d.file: d for d in given}
    named = [f.file for f in answer.files]
    for file in sorted({f for f in named if named.count(f) > 1}):
        problems.add("file-repeated", f"{file} is answered more than once.")
    for file in sorted(set(named) - set(by_file)):
        problems.add(
            "file-not-given", f"{file} was not given; answer only the files given."
        )
    for file in [f for f in by_file if f not in named]:
        problems.add(
            "file-missing", f"{file} has no answer; give every heading for it."
        )

    def quote_problem(file: str, quote: str, where: str) -> None:
        doc = by_file.get(file)
        if doc is None or doc.text is None:
            return
        if _flat(quote) not in _flat(doc.text):
            problems.add(
                "quote-not-found",
                f"In {where}: the quote is not in {file} word for word: {quote!r}",
            )

    for f in answer.files:
        noted = [n.heading for n in f.notes]
        for h in Heading:
            if h in noted and h in f.says_nothing:
                problems.add(
                    "heading-both",
                    f"{f.file}: {h.value} has notes and is also listed as saying "
                    "nothing; keep one.",
                )
            elif h not in noted and h not in f.says_nothing:
                problems.add(
                    "heading-missing",
                    f"{f.file}: say what it says about {h.value}, or list "
                    f"{h.value} under says_nothing.",
                )
        for n in f.notes:
            quote_problem(f.file, n.quote, f"{f.file}, {n.heading.value}")
    for i, d in enumerate(answer.disagreements, start=1):
        if d.file not in by_file:
            problems.add(
                "file-not-given",
                f"Disagreement {i} names {d.file}, which was not given.",
            )
        else:
            quote_problem(d.file, d.quote, f"disagreement {i}")
    return problems


# --- Handoffs and import ----------------------------------------------------


class Handoff(Frozen):
    name: NonEmptyStr
    instructions: NonEmptyStr
    files: tuple[DocFile, ...]


class Accepted(Frozen):
    handoff: NonEmptyStr
    files: dict[str, str]
    """Each file read, with the checksum of what was read."""
    unchecked: tuple[str, ...] = ()
    """Files whose quotes could not be checked (PDFs)."""
    drafted_by: NonEmptyStr
    imported: NonEmptyStr
    answer: DocsAnswer


def read_accepted(workspace: Path) -> list[Accepted]:
    return handoffs.read_answers(workspace, STEP, Accepted)


def pending_handoffs(workspace: Path) -> list[Handoff]:
    answered = {a.handoff for a in read_accepted(workspace)}
    return handoffs.read_pending(workspace, STEP, Handoff, answered)


def unread(
    workspace: Path, settings: Settings, scripts: Sequence[str] = ()
) -> list[DocFile]:
    """The documentation no accepted answer covers at its current content."""
    read = {(f, sha) for a in read_accepted(workspace) for f, sha in a.files.items()}
    return [
        d
        for d in list_documentation(workspace, settings, scripts)
        if (d.file, d.sha256) not in read
    ]


def plan_handoffs(
    workspace: Path,
    settings: Settings,
    scripts: Sequence[str] = (),
    max_chars: int = MAX_CHARS,
) -> list[Handoff]:
    groups: list[list[DocFile]] = []
    for d in unread(workspace, settings, scripts):
        size = len(d.text or "")
        if groups and sum(len(x.text or "") for x in groups[-1]) + size <= max_chars:
            groups[-1].append(d)
        else:
            groups.append([d])
    version = instructions.load(STEP).label
    return [
        Handoff(
            name=f"docs-{k}-{_sha(g[0].file)[:6]}",
            instructions=version,
            files=tuple(g),
        )
        for k, g in enumerate(groups, start=1)
    ]


def render_handoff(h: Handoff) -> str:
    body = []
    for d in h.files:
        body += ["", f"### `{d.file}` ({d.kind.value})", ""]
        if d.text is None:
            body.append(
                "This is a PDF: attach the file to the chat along with this text."
            )
        else:
            fence = "````" if "```" in d.text else "```"
            body += [fence, d.text.rstrip(), fence]
    what = f"the {plural(len(h.files), 'file')} below"
    return handoffs.render(STEP, h.name, h.instructions, what, body)


def write_handoffs(
    workspace: Path,
    settings: Settings,
    scripts: Sequence[str] = (),
    max_chars: int = MAX_CHARS,
) -> list[Path]:
    answered = {a.handoff for a in read_accepted(workspace)}
    planned = plan_handoffs(workspace, settings, scripts, max_chars)
    return handoffs.write_handoffs(
        workspace, STEP, ((h.name, h, render_handoff(h)) for h in planned), answered
    )


def import_answer(
    workspace: Path,
    reply: str,
    drafted_by: str,
    handoff: str | None = None,
    today: datetime.date | None = None,
) -> tuple[Path | None, list[Problem]]:
    """Check a reply and, if it has no problems, save it as accepted."""
    try:
        answer = parse_answer(reply)
    except AnswerError as e:
        return None, e.problems
    pending = pending_handoffs(workspace)
    named = {f.file for f in answer.files}
    if handoff is not None:
        fits = [h for h in pending if h.name == handoff]
    else:
        fits = [h for h in pending if named and named <= {d.file for d in h.files}]
    if len(fits) != 1:
        if not pending:
            return None, [
                Problem(
                    "no-handoff-waiting",
                    "No handoff is waiting for an answer; run rigoraudit handoff docs.",
                )
            ]
        return None, [
            Problem(
                "which-handoff",
                "Could not tell which handoff the answer is for; say which with "
                f"--handoff ({', '.join(h.name for h in pending)}).",
            )
        ]
    chosen = fits[0]
    problems = check_answer(answer, chosen.files)
    if problems:
        return None, problems
    record = Accepted(
        handoff=chosen.name,
        files={d.file: d.sha256 for d in chosen.files},
        unchecked=tuple(d.file for d in chosen.files if d.text is None),
        drafted_by=drafted_by,
        imported=(today or datetime.date.today()).isoformat(),
        answer=answer,
    )
    return handoffs.save_answer(workspace, STEP, chosen.name, record), []
