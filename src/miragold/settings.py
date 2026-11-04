# Copyright (c) 2026, Joshua I. Gold
# SPDX-License-Identifier: BSD-2-Clause
"""What the tool reads from a workspace's manifest, ``audit.yaml``.

The manifest is written for people (step 1), so the tool reads only a few
entries from it, and reads them forgivingly::

    materials:
      manuscript:
        path: manuscript/paper.pdf        # or materials/manuscript/paper.pdf
        supplement: manuscript/figures.pdf  # optional: a separate PDF with
                                          # what the paper's PDF leaves out,
                                          # such as figure supplements
      code:
        path: code
        repository: https://github.com/<owner>/<repo>
        commit: 0123abc...                # text after the hash is ignored
                                          # (or an OSF project, with no commit:
                                          # https://osf.io/<id>/)
      data:
        path: data
        files:                            # checksums of the files used
          - path: data/trials.csv
            sha256: 0123abc...
    gaps:                                 # what could not be run or checked
      - missing: the list of trials the figures use
        instead: rebuilt from the selection rule in the Methods
        claims: [R1.2.a]                  # the claims it affects (optional)
    settings:                             # optional; defaults shown
      scope: [Results, Figure, Table]     # the audited sections
      trace:
        code_access: auto                 # auto, repository, or index
      run:
        scripts: [code/main.m]            # scripts the run starts, whose
                                          # opening comments are read first
      derive:
        run: auto                         # auto: run a script that passes
                                          # the script checks without asking;
                                          # ask: ask before every script
        programs: [matlab]                # programs a script may start
                                          # without asking (miragold.matlab);
                                          # [] for none; the guide asks if unset
      extract:
        grobid: http://localhost:8070     # a GROBID server to read the PDF
                                          # with, if there is no XML (none)
      assistant:
        model: claude-opus-5-5            # the model API mode sends tasks to

Paths may be given relative to ``materials/`` or to the workspace. Without
a ``repository`` entry, a GitHub or OSF link anywhere in the code entry's
``received_from`` is used. Any entry under ``materials`` with both a
``path`` and a ``sha256`` gives a file's checksum, at any depth. Each gap
needs ``missing``; ``instead`` (what the audit did about it) and ``claims``
are optional.

The audited sections are patterns (regular expressions) matched at the
start of each paragraph's section (:func:`miragold.paragraphs.in_scope`):
``Results`` takes every Results subsection, and ``Figure \\d+ legend$``
only the legends of numbered figures.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import yaml

MANIFEST = "audit.yaml"
COMMIT = re.compile(r"\b[0-9a-f]{40}\b")
GITHUB = re.compile(r"https://github\.com/[\w.-]+/[\w.-]+")
OSF = re.compile(r"https://osf\.io/[a-z0-9]{5,}/?", re.IGNORECASE)
CodeAccess = Literal["auto", "repository", "index"]
DeriveRun = Literal["auto", "ask"]
PROGRAMS = {"matlab": ("MATLAB", ".m")}
"""Programs a derivation script may be allowed to start, each with its name
and the ending of its code files (:mod:`miragold.matlab`)."""
MODEL = "claude-opus-5-5"
"""The model API mode uses unless the manifest names another."""
DEFAULT_SCOPE = ("Results", "Figure", "Table")
"""Sections audited by default (decision 0002): the Results, then figure
legends and tables."""


@dataclass(frozen=True)
class Code:
    path: str
    """The local copy, relative to ``materials/``."""
    repository: str | None = None
    commit: str | None = None

    def link(self) -> str | None:
        """The repository at the commit, for an assistant to browse."""
        if self.repository is None or self.commit is None:
            return None
        return f"{self.repository.removesuffix('.git').rstrip('/')}/tree/{self.commit}"


@dataclass(frozen=True)
class Gap:
    """Something the audit could not run or check from the materials given."""

    missing: str
    """What the materials lack, or what did not run from them."""
    instead: str = ""
    """What the audit did about it: a stand-in, a rerun, or nothing."""
    claims: tuple[str, ...] = ()
    """The claims it affects."""


@dataclass(frozen=True)
class Settings:
    manuscript: str
    """The manuscript file, relative to ``materials/``."""
    supplement: str | None = None
    """A separate PDF printing what the manuscript's PDF leaves out (often
    figure supplements), relative to ``materials/``."""
    code: Code | None = None
    code_access: CodeAccess = "auto"
    run_scripts: tuple[str, ...] = ()
    """Scripts the run starts, relative to ``materials/`` (decision 0013)."""
    derive_run: DeriveRun = "auto"
    """Whether the derive step runs a script that passes the script checks
    without asking (:func:`miragold.derive.script_concerns`)."""
    derive_programs: tuple[str, ...] | None = None
    """Programs (of :data:`PROGRAMS`) a derivation script may start without
    asking; ``None`` if the manifest does not say, so the guide asks."""
    grobid: str | None = None
    """A GROBID server for the extract step (:mod:`miragold.grobid`)."""
    scope: tuple[str, ...] = DEFAULT_SCOPE
    """The audited sections, as patterns matched at the start of a section."""
    checksums: Mapping[str, str] = field(default_factory=dict)
    """SHA-256 of each material file listed with one, by path in ``materials/``."""
    model: str = MODEL
    """The model the guide sends tasks to, in API mode (:mod:`miragold.api`)."""
    gaps: tuple[Gap, ...] = ()
    """What the audit could not run or check from the materials given."""


def _in_materials(path: str) -> str:
    return path.removeprefix("materials/").rstrip("/")


def _checksums(entry: object, out: dict[str, str]) -> dict[str, str]:
    """Every ``path`` given with a ``sha256`` under ``entry``, at any depth."""
    if isinstance(entry, dict):
        if isinstance(entry.get("path"), str) and isinstance(entry.get("sha256"), str):
            out[_in_materials(entry["path"])] = entry["sha256"]
        for value in entry.values():
            _checksums(value, out)
    elif isinstance(entry, list):
        for value in entry:
            _checksums(value, out)
    return out


def _gaps(entries: object, path: Path) -> tuple[Gap, ...]:
    """The manifest's ``gaps``; an entry without ``missing`` is an error."""
    if not isinstance(entries, list):
        entries = [] if entries is None else [entries]
    out = []
    for i, e in enumerate(entries, start=1):
        missing = e.get("missing") if isinstance(e, dict) else None
        if not isinstance(missing, str):
            raise ValueError(  # noqa: TRY004
                f"{path}: gaps, entry {i}: give missing: (what the materials lack, "
                "or what did not run), and if you can, instead: (what the audit "
                "did about it) and claims: (the claims it affects)"
            )
        claims = e.get("claims") or []
        if isinstance(claims, str):
            claims = [claims]
        out.append(
            Gap(
                missing=missing.strip(),
                instead=str(e.get("instead") or "").strip(),
                claims=tuple(str(c) for c in claims),
            )
        )
    return tuple(out)


def set_programs(workspace: Path, programs: Sequence[str]) -> None:
    """Write ``settings: derive: programs`` into the manifest, keeping the
    rest of its text as it is."""
    path = workspace / MANIFEST
    text = path.read_text(encoding="utf-8")
    entry = f"programs: [{', '.join(programs)}]"
    lines = text.splitlines()
    settings = next((i for i, x in enumerate(lines) if x == "settings:"), None)
    derive = next(
        (
            i
            for i, x in enumerate(lines)
            if settings is not None and i > settings and x.strip() == "derive:"
        ),
        None,
    )
    if derive is not None:
        indent = len(lines[derive]) - len(lines[derive].lstrip())
        lines.insert(derive + 1, " " * (indent + 2) + entry)
    elif settings is not None:
        lines[settings + 1 : settings + 1] = ["  derive:", f"    {entry}"]
    else:
        lines += ["settings:", "  derive:", f"    {entry}"]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    if load(workspace).derive_programs != tuple(programs):
        raise ValueError(
            f"The tool could not add {entry} under settings › derive in "
            f"{path}. Add it there yourself, then run miragold audit again."
        )


def missing_paper(workspace: Path, s: Settings, command: str) -> str | None:
    """What to do if the paper or its supplement is not where the manifest
    says, ending with running ``command`` again; ``None`` if both are there."""
    for what, name in (("paper", s.manuscript), ("paper's supplement", s.supplement)):
        if name and not (workspace / "materials" / name).is_file():
            return (
                f"The manifest says the {what} is materials/{name}, but there is "
                f"no file there. Put it there, or correct the path in {MANIFEST}, "
                f"then run miragold {command} again."
            )
    return None


def load(workspace: Path) -> Settings:
    """Read the workspace's manifest; a missing manuscript path is an error."""
    path = workspace / MANIFEST
    if not path.is_file():
        raise FileNotFoundError(f"no {MANIFEST} in {workspace}")
    text = path.read_text(encoding="utf-8")
    try:
        data = yaml.safe_load(text) or {}
    except yaml.YAMLError as e:
        mark = getattr(e, "problem_mark", None)
        where = f" near line {mark.line + 1}" if mark else ""
        raise ValueError(
            f"{path} cannot be read{where}: {getattr(e, 'problem', None) or e}. "
            "Check the indentation and brackets there, then run the command again."
        ) from None
    if not isinstance(data, dict):
        raise ValueError(  # noqa: TRY004 (a message for the user, not a bug)
            f"{path} should list entries such as 'materials:'; see the user guide "
            "(docs/guide.md, 1. Collect materials)."
        )
    materials = data.get("materials") or {}
    manuscript = (materials.get("manuscript") or {}).get("path")
    if not manuscript:
        raise ValueError(f"{path}: materials › manuscript › path is missing")
    supplement = (materials.get("manuscript") or {}).get("supplement")
    if isinstance(supplement, dict):
        supplement = supplement.get("path")
    code = None
    entry = materials.get("code")
    if isinstance(entry, dict) and entry.get("path"):
        raw = entry.get("commit")
        if raw is not None and not isinstance(raw, str):
            # YAML reads an unquoted commit of only digits as a number; take
            # it from the text instead
            raw = " ".join(
                line for line in text.splitlines() if line.strip().startswith("commit:")
            )
        commit = COMMIT.search(str(raw or ""))
        repo = entry.get("repository") or (
            m.group(0)
            if (
                m := GITHUB.search(str(entry.get("received_from") or ""))
                or OSF.search(str(entry.get("received_from") or ""))
            )
            else None
        )
        code = Code(
            path=_in_materials(entry["path"]),
            repository=repo,
            commit=commit.group(0) if commit else None,
        )
    options = data.get("settings") or {}
    access = (options.get("trace") or {}).get("code_access", "auto")
    if access not in ("auto", "repository", "index"):
        raise ValueError(
            f"{path}: settings › trace › code_access must be auto, repository, or index"
        )
    derive_run = (options.get("derive") or {}).get("run", "auto")
    if derive_run not in ("auto", "ask"):
        raise ValueError(f"{path}: settings › derive › run must be auto or ask")
    programs = (options.get("derive") or {}).get("programs")
    if isinstance(programs, str):
        programs = [programs]
    if programs is not None and not set(programs) <= set(PROGRAMS):
        raise ValueError(
            f"{path}: settings › derive › programs may list only {', '.join(PROGRAMS)}"
        )
    server = (options.get("extract") or {}).get("grobid")
    model = (options.get("assistant") or {}).get("model") or MODEL
    scripts = (options.get("run") or {}).get("scripts") or []
    if isinstance(scripts, str):
        scripts = [scripts]
    scope = options.get("scope") or DEFAULT_SCOPE
    if isinstance(scope, str):
        scope = [scope]
    for pattern in scope:
        try:
            re.compile(str(pattern))
        except re.error as e:
            raise ValueError(
                f"{path}: settings › scope: {pattern!r} is not a pattern ({e})"
            ) from e
    return Settings(
        manuscript=_in_materials(manuscript),
        supplement=_in_materials(str(supplement)) if supplement else None,
        code=code,
        code_access=access,
        run_scripts=tuple(_in_materials(str(s)) for s in scripts),
        derive_run=derive_run,
        derive_programs=None if programs is None else tuple(programs),
        grobid=str(server) if server else None,
        scope=tuple(str(p) for p in scope),
        checksums=_checksums(materials, {}),
        model=str(model),
        gaps=_gaps(data.get("gaps"), path),
    )
