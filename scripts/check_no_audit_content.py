# Copyright (c) 2026, Joshua I. Gold
# SPDX-License-Identifier: BSD-2-Clause
"""Refuse commits that carry content from a private audit into this repository.

Examples in this repository are always synthetic. This check compares the
files to be committed (or a commit message) against the audit workspaces it
can see, which stay outside the repository:

- terms: one per line in ``release_terms.txt`` at a workspaces root or in a
  workspace (author names, subjects, file names, distinctive values); matched
  as whole words, case-sensitively;
- copied text: any run of ``RUN`` words that also occurs in a workspace's
  extracted manuscript text, record, or code, if at least half its words are
  longer than one character (runs of single digits and letters, such as
  ``1 1 2 2`` or ``x = a + b``, are common to any two documents);
- material files: PDFs, data and archive formats, and files over ``MAX_BYTES``.

Workspaces roots are read from ``MIRAGOLD_PRIVATE_ROOTS`` (separated by
``os.pathsep``), or default to ``../audit_examples`` beside the repository. A
workspace is any subfolder holding an ``audit.yaml``. With no root found, only
the file checks run, with a warning.

Usage:
    python scripts/check_no_audit_content.py              # all tracked files
    python scripts/check_no_audit_content.py --staged     # staged changes (pre-commit)
    python scripts/check_no_audit_content.py --message F  # a commit message (commit-msg)
"""

import argparse
import json
import os
import re
import subprocess
import sys
from collections.abc import Iterable, Iterator
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
RUN = 8
MAX_BYTES = 1_000_000
BLOCKED_SUFFIXES = {
    ".pdf", ".mat", ".rar", ".zip", ".gz", ".tar", ".7z", ".h5", ".hdf5",
    ".nwb", ".npy", ".npz", ".csv", ".tsv", ".xlsx", ".xls", ".docx", ".pptx",
}  # fmt: skip
# Standard text that audited code can share: the lockfile, and the license,
# whose wording also appears in code that carries the same license.
NOT_TEXT_CHECKED = {"uv.lock", "LICENSE"}
# The extracted manuscript text and the record. Not other stage outputs, which
# carry the tool's own messages; nor, in the record, the wording of findings
# the tool drafted (see record_strings).
SOURCE_TEXT = (
    "work/extract/*.txt", "work/extract/*.json",
    "record/record.json",
)  # fmt: skip
# Fields of a source file that hold the tool's own messages, not the paper's.
TOOL_FIELDS = {"equations.json": {"note"}}
SOURCE_CODE_SUFFIXES = {".m", ".py", ".r", ".R", ".jl", ".ipynb", ".md", ".txt"}
SOURCE_MAX_BYTES = 5_000_000

_DASHES = str.maketrans({"−": "-", "–": "-", "—": "-", "‐": "-"})


def words(text: str) -> list[str]:
    """Lowercased words and numbers, with dashes and minus signs unified."""
    return re.findall(r"[a-z0-9]+(?:[.,][0-9]+)*", text.translate(_DASHES).lower())


def runs(tokens: list[str]) -> Iterator[tuple[int, tuple[str, ...]]]:
    """Each run of ``RUN`` tokens worth comparing, with where it starts."""
    for i in range(len(tokens) - RUN + 1):
        run = tuple(tokens[i : i + RUN])
        if 2 * sum(len(t) > 1 for t in run) >= RUN:
            yield i, run


def private_roots() -> list[Path]:
    env = os.environ.get("MIRAGOLD_PRIVATE_ROOTS")
    candidates = env.split(os.pathsep) if env else [str(REPO.parent / "audit_examples")]
    return [
        Path(c).expanduser().resolve() for c in candidates if c and Path(c).is_dir()
    ]


def workspaces(roots: Iterable[Path]) -> list[Path]:
    return sorted(p.parent for r in roots for p in r.glob("*/audit.yaml"))


def read_terms(roots: list[Path], spaces: list[Path]) -> list[str]:
    terms = []
    for folder in [*roots, *spaces]:
        f = folder / "release_terms.txt"
        if f.is_file():
            lines = (ln.strip() for ln in f.read_text(encoding="utf-8").splitlines())
            terms += [ln for ln in lines if ln and not ln.startswith("#")]
    return sorted(set(terms))


def source_files(space: Path) -> Iterator[Path]:
    for pattern in SOURCE_TEXT:
        yield from (
            p for p in space.glob(pattern) if p.stat().st_size <= SOURCE_MAX_BYTES
        )
    code = space / "materials" / "code"
    if code.exists():
        for dirpath, dirnames, filenames in os.walk(code, followlinks=True):
            dirnames[:] = [d for d in dirnames if not d.startswith(".")]
            for name in filenames:
                p = Path(dirpath) / name
                if (
                    p.suffix in SOURCE_CODE_SUFFIXES
                    and p.stat().st_size <= SOURCE_MAX_BYTES
                ):
                    yield p


def json_strings(value: object, skip: Iterable[str] = ()) -> Iterator[str]:
    """String values in a JSON document, without its keys (shared with any
    record) or the values of fields named in ``skip``."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for k, v in value.items():
            if k not in skip:
                yield from json_strings(v, skip)
    elif isinstance(value, list):
        for v in value:
            yield from json_strings(v, skip)


def record_strings(record: dict) -> Iterator[str]:
    """String values in a record, without the tool's own wording: in the
    findings it drafted (their quotes, which are the paper's, are kept) and in
    what a test assumes (``context``)."""
    for k, v in record.items():
        if k != "findings":
            yield from json_strings(v, {"assumes"} if k == "context" else ())
    for f in record.get("findings", []):
        if (f.get("drafted_by") or {}).get("kind") != "tool":
            yield from json_strings(f)
            continue
        for o in f.get("observations", []):
            if quote := o.get("anchor", {}).get("quote"):
                yield quote


def private_runs(spaces: list[Path]) -> set[tuple[str, ...]]:
    seen: set[tuple[str, ...]] = set()
    for space in spaces:
        for f in source_files(space):
            text = f.read_text(errors="ignore", encoding="utf-8")
            if f.suffix == ".json":
                try:
                    doc = json.loads(text)
                    if f.name == "record.json":
                        texts = list(record_strings(doc))
                    else:
                        texts = list(json_strings(doc, TOOL_FIELDS.get(f.name, ())))
                except json.JSONDecodeError:
                    texts = [text]
            else:
                texts = [text]
            for t in texts:
                seen.update(r for _, r in runs(words(t)))
    return seen


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=REPO, check=True, capture_output=True, encoding="utf-8"
    ).stdout


def files_to_check(staged: bool) -> list[tuple[str, bytes]]:
    """(path, content) for each file: staged versions, or the tracked files on disk."""
    if staged:
        names = git(
            "diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z"
        ).split("\0")
        show = (lambda n: subprocess.run(
            ["git", "show", f":{n}"], cwd=REPO, check=True, capture_output=True
        ).stdout)  # fmt: skip
        return [(n, show(n)) for n in names if n]
    names = git("ls-files", "-z").split("\0")
    return [(n, (REPO / n).read_bytes()) for n in names if n and (REPO / n).is_file()]


def file_problems(name: str, content: bytes) -> list[str]:
    problems = []
    if Path(name).suffix.lower() in BLOCKED_SUFFIXES:
        problems.append(f"{name}: material or data file type ({Path(name).suffix})")
    if len(content) > MAX_BYTES:
        problems.append(
            f"{name}: {len(content):,} bytes, over the {MAX_BYTES:,}-byte limit"
        )
    return problems


def text_problems(
    name: str, text: str, terms: list[str], seen: set[tuple[str, ...]]
) -> list[str]:
    problems = []
    for n, line in enumerate(text.splitlines(), 1):
        for term in terms:
            if re.search(rf"(?<!\w){re.escape(term)}(?!\w)", line):
                problems.append(f"{name}:{n}: term {term!r}")
    tokens = words(text)
    hits = [i for i, r in runs(tokens) if r in seen]
    if hits:
        # report each stretch of overlapping runs once
        start = prev = hits[0]
        for i in [*hits[1:], None]:
            if i is not None and i <= prev + RUN:
                prev = i
                continue
            snippet = " ".join(tokens[start : prev + RUN])
            problems.append(f"{name}: text found in an audit workspace: {snippet!r}")
            if i is not None:
                start = prev = i
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--staged", action="store_true", help="check staged changes")
    group.add_argument("--message", type=Path, help="check a commit message file")
    args = parser.parse_args(argv)

    roots = private_roots()
    spaces = workspaces(roots)
    if not spaces:
        print("check_no_audit_content: no audit workspaces found; checking file types only. "
              "Set MIRAGOLD_PRIVATE_ROOTS to check content.", file=sys.stderr)  # fmt: skip
    terms = read_terms(roots, spaces)
    seen = private_runs(spaces)

    problems: list[str] = []
    if args.message:
        text = args.message.read_text(encoding="utf-8")
        text = "\n".join(ln for ln in text.splitlines() if not ln.startswith("#"))
        problems = text_problems("commit message", text, terms, seen)
    else:
        for name, content in files_to_check(args.staged):
            problems += file_problems(name, content)
            if name not in NOT_TEXT_CHECKED:
                problems += text_problems(
                    name, content.decode(errors="ignore"), terms, seen
                )

    for p in problems:
        print(p, file=sys.stderr)
    if problems:
        print(f"\n{len(problems)} problem(s): audit content must not enter this repository. "
              "Use synthetic examples.", file=sys.stderr)  # fmt: skip
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
