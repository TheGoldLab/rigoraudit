# Copyright (c) 2026, Joshua I. Gold
# SPDX-License-Identifier: BSD-2-Clause
"""An index of the authors' code, for an assistant that cannot browse it.

When the trace step cannot point an assistant at a public repository
(decision 0011 item 6), it sends this index instead: each code file, its
length, the functions it defines, and the line where each name is first
set. The assistant then asks for the lines it needs (``rigoraudit.trace``).

The index is read from the local copy, at the commit when the copy is a git
repository, and recognizes Python, MATLAB, R, and Julia by line patterns,
not by parsing; it is a map for asking, not a record. A Jupyter notebook
is read as its code cells only (``notebook_lines``), and its line numbers
everywhere are those of that view; its index also lists the headings of its
text cells, and the docs step reads the text itself (``notebook_text``).
Other files are counted by folder, not indexed.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from collections import Counter
from dataclasses import dataclass, replace
from functools import cache
from pathlib import Path, PurePosixPath

from rigoraudit.words import plural

_NAME = r"[A-Za-z_]\w*"
_PY_ASSIGN = re.compile(rf"^\s*({_NAME}(?:\s*,\s*{_NAME})*)\s*(?:[-+*/]?=)(?!=)")
LANGUAGES: dict[str, dict[str, object]] = {
    ".py": {
        "comment": "#",
        "functions": re.compile(rf"^\s*(?:async\s+)?(?:def|class)\s+({_NAME})"),
        "assign": [_PY_ASSIGN],
    },
    ".m": {
        "comment": "%",
        "functions": re.compile(
            rf"^\s*function\s+(?:(?:\[[^\]]*\]|{_NAME})\s*=\s*)?({_NAME})"
        ),
        "assign": [
            re.compile(rf"^\s*({_NAME})(?:\([^)]*\)|\{{[^}}]*\}}|\.{_NAME})*\s*=(?!=)"),
            re.compile(r"^\s*\[([^\]]+)\]\s*=(?!=)"),
        ],
    },
    ".r": {
        "comment": "#",
        "functions": re.compile(r"^\s*([A-Za-z.][\w.]*)\s*(?:<-|=)\s*function\b"),
        "assign": [re.compile(r"^\s*([A-Za-z.][\w.]*)\s*(?:<<?-|=(?!=))")],
    },
    ".jl": {
        "comment": "#",
        "functions": re.compile(rf"^\s*function\s+({_NAME})"),
        "assign": [_PY_ASSIGN],
    },
}
NOTEBOOK = ".ipynb"
_KERNELS = {"python": ".py", "matlab": ".m", "octave": ".m", "r": ".r", "julia": ".jl"}
_NOTEBOOK_HEAD = re.compile(r"^\S+ Code cells of a Jupyter notebook in (.+)$")


@dataclass(frozen=True)
class FileIndex:
    file: str
    """Path relative to the code folder, with ``/``."""
    lines: int
    functions: tuple[tuple[str, int], ...]
    """Each function (or class) defined, with its line."""
    first_set: tuple[tuple[str, int], ...]
    """Each other name, with the line where it is first set."""
    sections: tuple[tuple[str, int], ...] = ()
    """For a notebook, each heading in its text, with the line where the code
    after it starts."""


@dataclass(frozen=True)
class CodeIndex:
    files: tuple[FileIndex, ...]
    other: dict[str, int]
    """Files not indexed, counted by folder (``.`` for the top)."""


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout


def _notebook(text: str) -> tuple[list[str], list[tuple[int, int | None, str]]]:
    """The notebook view (see ``notebook_lines``) and the text cells, each
    with its number and the view's line where the next code cell starts
    (``None`` after the last one). Both empty if the text is not a notebook."""
    try:
        book = json.loads(text)
    except ValueError:
        return [], []
    if not isinstance(book, dict):
        return [], []
    meta = book.get("metadata") or {}
    language = str(
        (meta.get("language_info") or {}).get("name")
        or (meta.get("kernelspec") or {}).get("language")
        or "python"
    ).lower()
    comment = LANGUAGES.get(_KERNELS.get(language, ""), {}).get("comment", "#")
    out = [f"{comment} Code cells of a Jupyter notebook in {language}"]
    texts: list[tuple[int, int | None, str]] = []
    waiting: list[tuple[int, str]] = []
    code = 0
    for cell in book.get("cells") or ():
        source = cell.get("source") or ""
        if isinstance(source, list):
            source = "".join(source)
        source = source.replace("\r\n", "\n")
        if cell.get("cell_type") == "markdown" and source.strip():
            waiting.append((len(texts) + len(waiting) + 1, source.strip()))
        elif cell.get("cell_type") == "code":
            code += 1
            texts += [(k, len(out) + 1, t) for k, t in waiting]
            waiting = []
            out += [f"{comment} code cell {code}", *source.split("\n")]
    texts += [(k, None, t) for k, t in waiting]
    return out, texts


def notebook_lines(text: str) -> list[str]:
    """The code cells of a Jupyter notebook, as the lines of one file: a first
    line naming the notebook's language, then each cell headed by a comment
    line with its number among the code cells. Empty if the text is not a
    notebook."""
    return _notebook(text)[0]


def notebook_text(text: str) -> str:
    """The text cells of a Jupyter notebook, each headed by its number and the
    line (in ``notebook_lines``) where the code after it starts. Empty if
    there are none."""
    return "\n\n".join(
        f"Text cell {k}, "
        + (f"before line {line}:" if line else "after the last code cell:")
        + f"\n{t}"
        for k, line, t in _notebook(text)[1]
    )


def notebook_sections(text: str) -> tuple[tuple[str, int], ...]:
    """Each heading in a notebook's text cells, with the line (in
    ``notebook_lines``) where the code after it starts."""
    return tuple(
        (h.lstrip("#").strip(), line)
        for _, line, t in _notebook(text)[1]
        if line
        for h in t.split("\n")
        if h.startswith("#") and h.lstrip("#").strip()
    )


def code_suffix(file: str, lines: list[str]) -> str:
    """The suffix that picks ``file``'s language in ``LANGUAGES``; for a
    notebook, from the first line of ``notebook_lines``."""
    suffix = PurePosixPath(file).suffix.lower()
    if suffix != NOTEBOOK:
        return suffix
    m = _NOTEBOOK_HEAD.match(lines[0]) if lines else None
    return _KERNELS.get(m.group(1), "") if m else ""


def _view(path: Path, text: str) -> list[str]:
    if path.suffix.lower() == NOTEBOOK:
        return notebook_lines(text)
    return text.replace("\r\n", "\n").split("\n")


def read_lines(path: Path) -> list[str]:
    """Lines of the file at ``path`` in the working tree (a notebook's code
    cells only)."""
    return _view(path, path.read_text(encoding="utf-8", errors="replace"))


@cache
def _text_at_commit(path: Path, commit: str) -> str | None:
    repo = Path(_git(path.parent, "rev-parse", "--show-toplevel").strip())
    rel = path.resolve().relative_to(repo.resolve()).as_posix()
    try:
        return _git(repo, "show", f"{commit}:{rel}")
    except subprocess.CalledProcessError:
        return None


def file_at_commit(path: Path, commit: str) -> list[str] | None:
    """Lines of ``path`` at ``commit`` (a notebook's code cells only), or None
    if it is not in that commit."""
    content = _text_at_commit(path, commit)
    return None if content is None else _view(path, content)


def list_files(code_root: Path, commit: str | None) -> list[str]:
    """Files in the local copy, at ``commit`` when it is a git repository."""
    if commit is not None:
        try:
            top = Path(_git(code_root, "rev-parse", "--show-toplevel").strip())
            prefix = code_root.resolve().relative_to(top.resolve()).as_posix()
            names = _git(top, "ls-tree", "-r", "-z", "--name-only", commit, "--", ".")
            out = []
            for name in filter(None, names.split("\0")):
                if prefix != "." and not name.startswith(prefix + "/"):
                    continue
                out.append(name if prefix == "." else name[len(prefix) + 1 :])
            return sorted(out)
        except (subprocess.CalledProcessError, OSError, ValueError):
            pass
    out = []
    for dirpath, dirnames, filenames in os.walk(code_root):
        dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
        rel = Path(dirpath).relative_to(code_root)
        out += [(rel / f).as_posix() for f in filenames if not f.startswith(".")]
    return sorted(out)


def code_text(code_root: Path, file: str, commit: str | None) -> str | None:
    """The whole text of ``file`` in the local copy, at ``commit`` when the
    copy is a git repository holding it; ``None`` if the file is not there."""
    rel = PurePosixPath(file.lstrip("/"))
    if ".." in rel.parts:
        return None
    path = code_root / rel
    if not path.is_file():
        return None
    if commit is not None:
        try:
            at_commit = _text_at_commit(path, commit)
        except (subprocess.CalledProcessError, OSError, ValueError):
            at_commit = None
        if at_commit is not None:
            return at_commit
    return path.read_text(encoding="utf-8", errors="replace")


def code_lines(code_root: Path, file: str, commit: str | None) -> list[str] | None:
    """Lines of ``file`` in the local copy, at ``commit`` when the copy is a git
    repository holding it (a notebook's code cells only); ``None`` if the file
    is not there."""
    text = code_text(code_root, file, commit)
    return None if text is None else _view(code_root / file.lstrip("/"), text)


def index_lines(file: str, lines: list[str]) -> FileIndex:
    """Index one file's lines; ``code_suffix`` picks the language."""
    lang = LANGUAGES[code_suffix(file, lines)]
    functions: dict[str, int] = {}
    first: dict[str, int] = {}
    for n, line in enumerate(lines, 1):
        if line.lstrip().startswith(lang["comment"]):  # type: ignore[arg-type]
            continue
        if m := lang["functions"].match(line):  # type: ignore[union-attr]
            functions.setdefault(m.group(1), n)
            continue
        for pattern in lang["assign"]:  # type: ignore[union-attr]
            if m := pattern.match(line):
                for name in re.split(r"[\s,]+", m.group(1).strip()):
                    if re.fullmatch(r"[A-Za-z_.][\w.]*", name) and name != "~":
                        first.setdefault(name, n)
                break
    return FileIndex(
        file=file,
        lines=len(lines) - (bool(lines) and lines[-1] == ""),
        functions=tuple(functions.items()),
        first_set=tuple((k, v) for k, v in first.items() if k not in functions),
    )


def build_index(code_root: Path, commit: str | None) -> CodeIndex:
    """Index the code files in ``code_root``; count the others by folder."""
    files, other = [], Counter()
    for name in list_files(code_root, commit):
        if PurePosixPath(name).suffix.lower() in (*LANGUAGES, NOTEBOOK):
            text = code_text(code_root, name, commit)
            lines = None if text is None else _view(code_root / name, text)
            if lines is not None and code_suffix(name, lines) in LANGUAGES:
                found = index_lines(name, lines)
                if PurePosixPath(name).suffix.lower() == NOTEBOOK:
                    found = replace(found, sections=notebook_sections(text))
                files.append(found)
                continue
        other[PurePosixPath(name).parent.as_posix()] += 1
    return CodeIndex(files=tuple(files), other=dict(sorted(other.items())))


def render_index(index: CodeIndex) -> list[str]:
    """The index as Markdown lines, for a handoff."""

    def names(pairs):
        return ", ".join(f"{name} ({line})" for name, line in pairs) or "none"

    out = []
    for f in index.files:
        out += [
            "",
            f"### `{f.file}` ({plural(f.lines, 'line')})",
            "",
            f"- functions: {names(f.functions)}",
            f"- first set: {names(f.first_set)}",
        ]
        if f.sections:
            out.append(f"- sections of its text: {names(f.sections)}")
    if index.other:
        n = sum(index.other.values())
        where = ", ".join(f"{folder}/ ({k})" for folder, k in index.other.items())
        out += ["", f"Other files, not indexed: {n}, in {where}."]
    return out
