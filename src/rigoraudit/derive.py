# Copyright (c) 2026, Joshua I. Gold
# SPDX-License-Identifier: BSD-2-Clause
"""Recompute each claim's values with a script the assistant writes
(decisions 0007 and 0011).

After tracing, the decomposed claims are handed to an assistant, up to
:data:`MAX_CLAIMS` at a time, each with the numbers its paragraph prints, the Methods passages and code lines the trace
found, the notes from the authors' documentation, and a list of the
materials (``rigoraudit/instructions/derive.md``). The answer says, for
each printed number, the key under which a script will save its value, the
lines of code that set it (a setting, which nothing computes), or why it
cannot be recomputed; it may add values the paragraph does not print (a
difference behind "higher"). One script, for all the task's claims,
comes in the same reply.

The tool checks the answer, saves the script in ``derivations/`` (named for
the task's claims, :func:`script_path`), and runs it on this computer:
without asking if :func:`script_concerns` finds nothing for a person to
look at, otherwise once the user has agreed (decision 0011, item 6, and its
note of 2026-11-01). The manifest's ``derive: run: ask`` asks before every
script; its ``derive: programs: [matlab]`` lets a script start MATLAB
through :mod:`rigoraudit.matlab` without asking. The script saves each
claim's values with :func:`rigoraudit.values.write_values` to
``derivations/output/values/<claim>.json``; a script that fails, leaves
out a key it promised, or saves a printed number as true, false, or text,
is sent back with what went wrong. A claim stated in words that cannot be
checked names its facet in ``cannot``. For each reported test the script
recomputes, the answer names the keys of its N, what one value is, and
each group's values (:class:`TestData`), which :mod:`rigoraudit.stats`
compares with the text and describes (decision 0015, items 6 and 11).
Accepted answers
are kept in ``work/derive/answers/``, and :func:`derived_observations` turns
them into the record's output and data observations.
"""

from __future__ import annotations

import ast
import datetime
import os
import re
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path, PurePosixPath
from typing import Literal

from pydantic import ConfigDict, Field, PositiveInt

from rigoraudit import decompose, docs, handoffs, instructions, materials, trace
from rigoraudit.codeindex import code_lines
from rigoraudit.decompose import read_printed
from rigoraudit.handoffs import AnswerError, Problem, Problems
from rigoraudit.paragraphs import PARAGRAPHS, Paragraph, read_paragraphs
from rigoraudit.schema import (
    ClaimId,
    CodeAnchor,
    DataAnchor,
    Derivation,
    Facet,
    Frozen,
    NonEmptyStr,
    Observation,
    Obtained,
    Source,
    Value,
)
from rigoraudit.settings import Settings
from rigoraudit.values import read_values
from rigoraudit.verify import shown_in
from rigoraudit.words import plural

STEP = "derive"
NOUNS = {
    "claims": "claim",
    "values": "value",
    "in_code": "entry in in_code",
    "cannot": "entry in cannot",
}
MAX_CLAIMS = 10
"""Claims per handoff."""
RUN_WARNING = (
    "A script is a program: running it could change or delete files on this "
    "computer. Before you agree, open it in any text editor and check that it "
    "only reads the materials and saves its values, or ask your assistant to "
    "explain what it does."
)
"""Said before running a script the assistant wrote."""


def concerns_text(concerns: Sequence[str]) -> str:
    """The script checks' findings, for the user; empty if none."""
    if not concerns:
        return ""
    return "The script checks found these for a person to look at:\n" + "".join(
        f"  {c}\n" for c in concerns
    )


SCRIPTS = PurePosixPath("derivations")
OUTPUTS = SCRIPTS / "output" / "values"
TIMEOUT = 60 * 60
"""Seconds a script may run before it is stopped."""
MAX_FILES = 300
"""Files of the materials listed in a handoff."""
PYTHON = re.compile(r"```python[^\n]*\n(.*?)```", re.DOTALL)
KEY = re.compile(r"^[^/\s]+(?:/[^/\s]+)*$")


class DerivedValue(Frozen):
    model_config = ConfigDict(frozen=True, extra="forbid", populate_by_name=True)

    for_: NonEmptyStr = Field(alias="for")
    """A stated value's label (``V1``), or a facet for a value not printed."""
    key: NonEmptyStr
    """Where the script saves it, e.g. ``accuracy/session_1``."""
    name: str | None = None
    """What it is, for a value not printed."""
    how: Literal["executed", "recomputed"]
    """Executed: the authors' code, run. Recomputed: the audit's own
    computation from the data."""
    source: NonEmptyStr
    """The file it comes from, or the folder of files, relative to
    ``materials/``."""
    derivation: NonEmptyStr
    """How it is obtained, in a few words."""


class InCode(Frozen):
    """A value the code sets rather than computes: a window, a bound."""

    model_config = ConfigDict(frozen=True, extra="forbid", populate_by_name=True)

    for_: NonEmptyStr = Field(alias="for")
    file: NonEmptyStr
    """Relative to the code's folder, as the task names it."""
    lines: tuple[PositiveInt, PositiveInt]
    """The first and last line that set it."""
    value: bool | int | float | str
    name: str | None = None
    """What it is, for a value not printed."""
    unit: str | None = None
    """When the code's unit differs from the paper's."""


class Cannot(Frozen):
    model_config = ConfigDict(frozen=True, extra="forbid", populate_by_name=True)

    for_: NonEmptyStr = Field(alias="for")
    reason: NonEmptyStr


UNITS = ("trial", "block", "session", "cell", "animal", "participant", "other")
"""The words for what one observation of a test is (decision 0015, item 6)."""


class StatedUnit(Frozen):
    """What one observation is, as the text states it."""

    says: NonEmptyStr
    """One of :data:`UNITS`."""
    quote: NonEmptyStr
    """The words that state it, in the claim's paragraph or the Methods."""


class TestData(Frozen):
    """What the script saves about one reported test it recomputes
    (decision 0015, items 6 and 11)."""

    test: PositiveInt
    """The test's number, as the task lists it, from 1."""
    n: NonEmptyStr
    """The key of the N behind the test."""
    unit: NonEmptyStr
    """The key of what one observation is, saved as one of :data:`UNITS`."""
    source: NonEmptyStr
    """The data file or folder, relative to ``materials/``."""
    groups: str | None = None
    """The key under which each group's values are saved as a list
    (``<groups>/<group>/0``, ...)."""
    bounds: tuple[float, float] | None = None
    """The lowest and highest the values can be, for proportions and counts."""
    stated_unit: StatedUnit | None = None
    """Only when the text states it."""


class ClaimValues(Frozen):
    claim: ClaimId
    values: tuple[DerivedValue, ...] = ()
    in_code: tuple[InCode, ...] = ()
    cannot: tuple[Cannot, ...] = ()
    tests: tuple[TestData, ...] = ()


class DeriveAnswer(Frozen):
    instructions: NonEmptyStr
    claims: tuple[ClaimValues, ...]


class Stated(Frozen):
    label: NonEmptyStr
    facet: Facet
    name: NonEmptyStr
    printed: NonEmptyStr
    subject: str | None = None


class ClaimTask(Frozen):
    claim: ClaimId
    quote: NonEmptyStr
    paragraph: NonEmptyStr
    """The paragraph's label."""
    facets: dict[Facet, str]
    """What the paragraph states about each facet."""
    stated: tuple[Stated, ...]
    """Labelled ``V1``, ``V2``, numbered through the handoff."""
    methods: tuple[str, ...]
    code: tuple[str, ...]
    """Each cited code passage, as Markdown."""
    tests: tuple[str, ...] = ()
    """Each test the claim reports, as printed, numbered from 1."""


class Handoff(Frozen):
    name: NonEmptyStr
    instructions: NonEmptyStr
    claims: tuple[ClaimTask, ...]
    paragraphs: dict[str, str]
    places: dict[str, str]
    notes: tuple[str, ...]
    """What the authors' documentation says about running the code."""
    materials: tuple[str, ...]


class Accepted(Frozen):
    handoff: NonEmptyStr
    claims: tuple[ClaimId, ...]
    drafted_by: NonEmptyStr
    imported: NonEmptyStr
    answer: DeriveAnswer
    script: str | None
    """The script, relative to the workspace; none if nothing is recomputed."""
    outputs: dict[ClaimId, str]
    """Each claim with values, and the file its values are saved in."""


def parse_answer(text: str) -> tuple[DeriveAnswer, str | None]:
    """The answer, and the script given with it in a ``python`` block."""
    script = PYTHON.search(text)
    rest = PYTHON.sub("", text)
    return handoffs.parse_reply(rest, DeriveAnswer, NOUNS), (
        script.group(1) if script else None
    )


def script_path(claims: Sequence[str]) -> Path:
    """The script for a handoff's claims: named for the first, or the first
    and last."""
    name = claims[0] if len(claims) == 1 else f"{claims[0]}_to_{claims[-1]}"
    return SCRIPTS / f"{name}.py"


def output_path(claim: str) -> Path:
    return OUTPUTS / f"{claim}.json"


def read_accepted(workspace: Path) -> list[Accepted]:
    return handoffs.read_answers(workspace, STEP, Accepted)


def pending_handoffs(workspace: Path) -> list[Handoff]:
    answered = {a.handoff for a in read_accepted(workspace)}
    return handoffs.read_pending(workspace, STEP, Handoff, answered)


def _materials(workspace: Path, settings: Settings) -> list[str]:
    """The materials' files with their sizes and what each data file holds,
    leaving out the code's documentation (read in the docs step)."""
    code = PurePosixPath(settings.code.path) if settings.code else None
    out = [
        materials.describe(f)
        for f in materials.list_files(workspace, settings)
        if not (
            code
            and f.kind == "documentation"
            and PurePosixPath(f.path).is_relative_to(code)
        )
    ]
    if len(out) > MAX_FILES:
        out = [*out[:MAX_FILES], f"... and {len(out) - MAX_FILES} more files"]
    return out


def stated_values(workspace: Path) -> dict[str, dict[str, Stated]]:
    """The numbers each claim prints, by claim and label, from every handoff."""
    return {
        c.claim: {s.label: s for s in c.stated}
        for h in handoffs.read_pending(workspace, STEP, Handoff, ())
        for c in h.claims
    }


def plan_handoffs(
    workspace: Path, settings: Settings, max_claims: int = MAX_CLAIMS
) -> list[Handoff]:
    """Handoffs for the decomposed claims no accepted answer covers yet, up
    to ``max_claims`` each, in reading order."""
    done = {c for a in read_accepted(workspace) for c in a.claims}
    paragraphs = {p.label: p for p in read_paragraphs(workspace / PARAGRAPHS)}
    where = {c.id: c for c in decompose.to_decompose(workspace)}
    traced = {c.id: c for a in trace.read_accepted(workspace) for c in a.answer.claims}
    notes = tuple(
        f"`{f.file}` ({n.heading}): “{n.quote}” — {n.states}"
        for a in docs.read_accepted(workspace)
        for f in a.answer.files
        for n in f.notes
    )
    files = tuple(_materials(workspace, settings))
    version = instructions.load(STEP).label
    todo = [
        c
        for a in decompose.read_accepted(workspace)
        for c in a.answer.claims
        if c.id not in done
    ]
    out = []
    for start in range(0, len(todo), max_claims):
        tasks, n = [], 0
        for c in todo[start : start + max_claims]:
            stated = []
            for f in c.facets:
                for v in f.values:
                    n += 1
                    stated.append(
                        Stated(
                            label=f"V{n}",
                            facet=f.facet,
                            name=v.name,
                            printed=v.printed,
                            subject=v.subject,
                        )
                    )
            t = traced.get(c.id)
            facets = t.facets if t else ()
            tasks.append(
                ClaimTask(
                    claim=c.id,
                    quote=where[c.id].quote,
                    paragraph=where[c.id].paragraph,
                    facets={f.facet: f.states for f in c.facets},
                    stated=tuple(stated),
                    methods=tuple(
                        f"{f.facet}: “{m.quote}” — {m.states}"
                        for f in facets
                        for m in f.methods
                    ),
                    code=tuple(
                        f"{f.facet}: `{k.file}`, lines {k.lines[0]}–{k.lines[1]} — "
                        f"{k.states}\n\n```\n{k.quote}\n```"
                        for f in facets
                        for k in f.code
                    ),
                    tests=tuple(
                        f"{t.named}: {t.quote}" if t.named else t.quote for t in c.tests
                    ),
                )
            )
        labels = list(dict.fromkeys(c.paragraph for c in tasks))
        out.append(
            Handoff(
                name=f"derive-{tasks[0].claim}",
                instructions=version,
                claims=tuple(tasks),
                paragraphs={lab: paragraphs[lab].text for lab in labels},
                places={lab: paragraphs[lab].place for lab in labels},
                notes=notes,
                materials=files,
            )
        )
    return out


def render_handoff(h: Handoff) -> str:
    body = []
    for label, text in h.paragraphs.items():
        body += ["", f"## Paragraph {label} ({h.places[label]})", "", text]
        for c in h.claims:
            if c.paragraph == label:
                body += _render_claim(c)
    body += ["", "## What the authors' documentation says", ""]
    body += [f"- {n}" for n in h.notes] or ["(no notes)"]
    body += ["", "## The materials (paths relative to `materials/`)", ""]
    body += [f"- {f}" for f in h.materials] or ["(none)"]
    body += [
        "",
        (
            f"What the code reads, and whether each file is there, is in "
            f"`{materials.LIST.as_posix()}`."
        ),
    ]
    claims = [c.claim for c in h.claims]
    body += [
        "",
        (
            "Save each claim's values to `derivations/output/values/<claim>.json` "
            f"(for example `{output_path(claims[0]).as_posix()}`); the tool saves "
            f"the script as `{script_path(claims).as_posix()}`."
        ),
    ]
    what = (
        f"claim `{claims[0]}`"
        if len(claims) == 1
        else f"the {len(claims)} claims below, in one script"
    )
    return handoffs.render(STEP, h.name, h.instructions, what, body)


def _render_claim(c: ClaimTask) -> list[str]:
    body = [
        "",
        f"### Claim `{c.claim}`",
        "",
        f"> {c.quote}",
        "",
        "What it states:",
        "",
        *(f"- {f}: {s}" for f, s in c.facets.items()),
        "",
        "The numbers it prints:",
        "",
    ]
    body += [
        f"- `{s.label}` ({s.facet}): {s.name} = {s.printed}"
        + (f", for {s.subject}" if s.subject else "")
        for s in c.stated
    ] or ["(none)"]
    body += ["", "What the Methods say:", ""]
    body += [f"- {m}" for m in c.methods] or ["(nothing found)"]
    body += ["", "The code behind it:", ""]
    body += [f"- {k}" for k in c.code] or ["(nothing found)"]
    if c.tests:
        body += ["", "The tests it reports:", ""]
        body += [f"- Test {n}: {t}" for n, t in enumerate(c.tests, 1)]
    return body


def write_handoffs(workspace: Path, settings: Settings) -> list[Path]:
    """Write the handoffs still needed; return the files to paste."""
    answered = {a.handoff for a in read_accepted(workspace)}
    return handoffs.write_handoffs(
        workspace,
        STEP,
        ((h.name, h, render_handoff(h)) for h in plan_handoffs(workspace, settings)),
        answered,
    )


def check_answer(
    answer: DeriveAnswer,
    script: str | None,
    h: Handoff,
    workspace: Path,
    settings: Settings,
) -> Problems:
    """Every problem with an answer, before its script is run."""
    problems = handoffs.version_problem(STEP, answer.instructions)
    tasks = {c.claim: c for c in h.claims}
    problems.extend(handoffs.claims_problems([c.claim for c in answer.claims], tasks))
    for c in answer.claims:
        if c.claim in tasks:
            problems.extend(_claim_problems(c, tasks[c.claim], workspace, settings))
    keys = [(c.claim, v.key) for c in answer.claims for v in c.values]
    for claim, k in sorted({k for k in keys if keys.count(k) > 1}):
        problems.add(
            "key-twice", f"Claim {claim} uses the key {k} for more than one value."
        )
    with_values = [c.claim for c in answer.claims if c.values or c.tests]
    if with_values and script is None:
        problems.add(
            "no-script",
            "The answer saves values but gives no script; add it in a ```python "
            "block after the JSON.",
        )
    elif with_values and script is not None:
        path = script_path([c.claim for c in h.claims])
        try:
            compile(script, path.name, "exec")
        except SyntaxError as e:
            problems.add(
                "script-syntax", f"The script is not valid Python (line {e.lineno}: "
                f"{e.msg})."
            )  # fmt: skip
        if "write_values" not in script:
            problems.add(
                "script-output",
                "The script must save each claim's values with write_values, to "
                "derivations/output/values/<claim>.json.",
            )
    return problems


def _claim_problems(
    answer: ClaimValues, h: ClaimTask, workspace: Path, settings: Settings
) -> Problems:
    """Problems with one claim's values."""
    problems = Problems()
    materials = workspace / "materials"
    labels = {s.label for s in h.stated}
    given = [v.for_ for v in (*answer.values, *answer.in_code, *answer.cannot)]
    for label in sorted(labels - set(given), key=lambda x: int(x[1:])):
        problems.add(
            "value-missing",
            f"Claim {h.claim}: {label} is in neither values nor cannot; say how it is "
            "recomputed, or why it cannot be.",
        )
    for label in sorted({g for g in given if given.count(g) > 1 and g in labels}):
        problems.add("value-twice", f"{label} is given more than once.")
    facets = {f.value for f in Facet}
    for v in answer.values:
        if v.for_ not in labels and v.for_ not in facets:
            problems.add(
                "unknown-value",
                f"Claim {h.claim}: values names {v.for_!r}, which is neither a number's label "
                f"({', '.join(sorted(labels)) or 'none here'}) nor a facet.",
            )
        elif v.for_ in facets and not v.name:
            problems.add(
                "name-missing",
                f"The value saved as {v.key} is not printed in the paragraph, so "
                "give it a name.",
            )
        if not KEY.match(v.key):
            problems.add("bad-key", f"{v.key!r} is not a key: use parts joined by '/'.")
        if not (materials / v.source).exists():
            problems.add(
                "no-such-file",
                f"The value saved as {v.key} comes from {v.source}, which is not "
                "in the materials.",
            )
    for s in answer.in_code:
        problems.extend(_in_code_problems(s, h, labels, workspace, settings))
    problems.extend(_tests_problems(answer, h, workspace))
    for c in answer.cannot:
        if c.for_ not in labels and c.for_ not in facets:
            problems.add(
                "unknown-value",
                f"Claim {h.claim}: cannot names {c.for_!r}, which is neither a "
                f"number's label ({', '.join(sorted(labels)) or 'none here'}) nor a "
                "facet.",
            )
    return problems


def _tests_problems(answer: ClaimValues, h: ClaimTask, workspace: Path) -> Problems:
    """Problems with what a claim's answer says about its tests."""
    problems = Problems()
    numbers = [t.test for t in answer.tests]
    for t in answer.tests:
        where = f"Claim {h.claim}, test {t.test}"
        if t.test > len(h.tests):
            problems.add(
                "unknown-test",
                f"{where}: the claim reports {plural(len(h.tests), 'test')}; number "
                "them as the task lists them.",
            )
        if numbers.count(t.test) > 1:
            problems.add("test-twice", f"{where} is given more than once.")
        for k in (t.n, t.unit, *([t.groups] if t.groups else [])):
            if not KEY.match(k):
                problems.add("bad-key", f"{k!r} is not a key: use parts joined by '/'.")
        if not (workspace / "materials" / t.source).exists():
            problems.add(
                "no-such-file",
                f"{where}: its data come from {t.source}, which is not in the materials.",
            )
        if t.bounds is not None and not t.bounds[0] < t.bounds[1]:
            problems.add(
                "bad-bounds", f"{where}: bounds are [lowest, highest], lowest first."
            )
        if t.stated_unit is not None:
            if t.stated_unit.says not in UNITS:
                problems.add(
                    "bad-unit",
                    f"{where}: stated_unit says {t.stated_unit.says!r}; use one of "
                    f"{', '.join(UNITS)}.",
                )
            if unit_paragraph(workspace, h.paragraph, t.stated_unit.quote) is None:
                problems.add(
                    "quote-not-found",
                    f"{where}: the stated unit's quote is not in the claim's paragraph "
                    "or the Methods, exactly once; copy it exactly, or make it longer.",
                )
    return problems


def unit_paragraph(
    workspace: Path, claim_paragraph: str, quote: str
) -> Paragraph | None:
    """The paragraph that holds a stated unit's quote: the claim's own, else
    the one Methods paragraph that holds it once."""
    paragraphs = read_paragraphs(workspace / PARAGRAPHS)
    own = next(p for p in paragraphs if p.label == claim_paragraph)
    if own.text.count(quote) == 1:
        return own
    found = [p for p in paragraphs if "method" in p.top.lower() and quote in p.text]
    if len(found) == 1 and found[0].text.count(quote) == 1:
        return found[0]
    return None


def _in_code_problems(
    s: InCode, h: ClaimTask, labels: set[str], workspace: Path, settings: Settings
) -> Problems:
    """Problems with a value the code sets: its lines must be there and show it."""
    problems = Problems()
    facets = {f.value for f in Facet}
    if s.for_ not in labels and s.for_ not in facets:
        problems.add(
            "unknown-value",
            f"Claim {h.claim}: in_code names {s.for_!r}, which is neither a number's "
            f"label ({', '.join(sorted(labels)) or 'none here'}) nor a facet.",
        )
    elif s.for_ in facets and not s.name:
        problems.add(
            "name-missing",
            f"Claim {h.claim}: the value in {s.file} is not printed in the paragraph, "
            "so give it a name.",
        )
    if settings.code is None:
        problems.add(
            "no-code", "The manifest gives no code, so in_code cannot be used."
        )
        return problems
    root = workspace / "materials" / settings.code.path
    lines = code_lines(root, s.file, settings.code.commit)
    first, last = s.lines
    if lines is None:
        problems.add(
            "no-such-file",
            f"Claim {h.claim}: {s.file} is not in the code; name it as the task's "
            "code passages do.",
        )
    elif not first <= last <= len(lines):
        problems.add(
            "bad-lines",
            f"Claim {h.claim}: {s.file} has {plural(len(lines), 'line')}, so lines "
            f"{first}–{last} cannot be quoted.",
        )
    elif not shown_in(_setting_value(s, None), "\n".join(lines[first - 1 : last])):
        problems.add(
            "not-in-code",
            f"Claim {h.claim}: lines {first}–{last} of {s.file} do not show "
            f"{s.value!r}; give the lines that set it, and the value as written there.",
        )
    return problems


def _setting_value(s: InCode, stated: Stated | None) -> Value:
    printed = read_printed(stated.printed) if stated else None
    return Value(
        name=stated.name if stated else s.name or s.for_,
        value=s.value,
        unit=s.unit or (printed.unit if printed else None),
        subject=stated.subject if stated else None,
    )


# --- What a script touches --------------------------------------------------

SAFE_MODULES = frozenset({
    "__future__", "bisect", "collections", "copy", "csv", "dataclasses",
    "datetime", "decimal", "enum", "fractions", "functools", "glob", "gzip",
    "h5py", "heapq", "io", "itertools", "tarfile", "zipfile", "json", "math", "numpy", "operator", "pathlib", "random", "re",
    "rigoraudit.values", "scipy", "statistics", "string", "textwrap", "typing",
    "warnings",
})  # fmt: skip
"""Modules a script may import without the user being asked: they read
files and compute, but do not start programs, delete files, or reach the
network."""
MODULE_RISKS = {
    "subprocess": "starts other programs",
    "os": "can start programs and change or delete files",
    "shutil": "can copy, move, or delete files",
    "socket": "can reach the network",
    "urllib": "can reach the network",
    "http": "can reach the network",
    "requests": "can reach the network",
    "rigoraudit.matlab": "starts MATLAB (settings: derive: programs: [matlab] "
    "in the manifest allows it)",
}
WRITES_TO_ITSELF = {"write_text", "write_bytes", "touch", "mkdir"}
"""Path methods that write where the path points."""
WRITES_TO_FIRST = {"write_values", "save", "savez", "savez_compressed", "savetxt",
                   "savemat", "tofile"}  # fmt: skip
"""Functions that write to the path given first."""
OPENS = {"open", "File", "ZipFile"}
"""Calls that open a file, for writing if their mode says so (h5py.File and
zipfile.ZipFile take the path first, then the mode, as open does)."""
OPENER_MODULES = {"gzip", "bz2", "lzma", "io", "tarfile", "codecs"}
"""Modules whose own open takes the path first, as the built-in open does."""
EXTRACTS = {"extract", "extractall"}
"""Archive methods that unpack files (reading one goes by extractfile)."""
DELETES = {"unlink", "rmdir", "rename", "symlink_to", "hardlink_to", "chmod"}
RUNS_TEXT = {"eval", "exec", "compile", "__import__"}
FULL_PATH = re.compile(r"^(/[\w.~-]|~[/\\]|[A-Za-z]:[\\/])")
UNKNOWN = "?"
"""A path part the check cannot read, such as a name made while running."""


def _module_concern(name: str, programs: Sequence[str] = ()) -> str | None:
    safe = SAFE_MODULES | {f"rigoraudit.{p}" for p in programs}
    if any(name == m or name.startswith(m + ".") for m in safe):
        return None
    why = next(
        (MODULE_RISKS[m] for m in (name, name.split(".")[0]) if m in MODULE_RISKS),
        "is not one of the modules the check knows to be safe",
    )
    return f"imports {name}, which {why}"


def _place(
    node: ast.expr, names: Mapping[str, ast.expr], depth: int = 0
) -> list[str] | None:
    """Where a path expression points, as parts from the script's folder
    (``..`` climbs out of it); None if the check cannot tell."""
    if depth > 50:
        return None

    def again(n: ast.expr) -> list[str] | None:
        return _place(n, names, depth + 1)

    if isinstance(node, ast.Name):
        if node.id == "__file__":
            return ["<script>"]
        return again(names[node.id]) if node.id in names else None
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        if FULL_PATH.match(node.value):
            return None
        return _walk([], node.value.replace("\\", "/").split("/"))
    if isinstance(node, ast.Attribute) and node.attr == "parent":
        base = again(node.value)
        return None if base is None else _walk(base, [".."])
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
        if node.func.attr in ("resolve", "absolute", "expanduser"):
            return again(node.func.value)
        if node.func.attr in ("with_name", "with_suffix", "with_stem"):
            base = again(node.func.value)
            return None if base is None else _walk(base, ["..", UNKNOWN])
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in ("Path", "PurePath")
        and len(node.args) == 1
    ):
        return again(node.args[0])
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        base = again(node.left)
        if base is None:
            return None
        right = node.right
        if isinstance(right, ast.Constant) and isinstance(right.value, str):
            if FULL_PATH.match(right.value):
                return None
            return _walk(base, right.value.replace("\\", "/").split("/"))
        return _walk(base, [UNKNOWN])
    return None


def _walk(parts: list[str], steps: Sequence[str]) -> list[str]:
    out = list(parts)
    for step in steps:
        if step in ("", "."):
            continue
        if step == ".." and out and out[-1] != "..":
            out.pop()
        else:
            out.append(step)
    return out


def script_concerns(script: str, programs: Sequence[str] = ()) -> list[str]:
    """What a person should look at in a script before it runs, line by
    line: imports beyond :data:`SAFE_MODULES` (and the modules that start
    the ``programs`` the manifest allows, such as :mod:`rigoraudit.matlab`),
    writing outside
    ``derivations/`` or to a place the check cannot tell, deleting or
    renaming files, running text as code, and paths outside the workspace.

    The check reads the script without running it. It catches mistakes, not
    a script written to get past it.
    """
    try:
        tree = ast.parse(script)
    except SyntaxError:
        return []  # it cannot run either; running it reports the error
    names: dict[str, ast.expr] = {}
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
        ):
            names[node.targets[0].id] = node.value
    docstrings = {
        id(n.value)
        for n in ast.walk(tree)
        if isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant)
    }
    found: dict[int, list[str]] = {}

    def add(node: ast.AST, what: str) -> None:
        line = getattr(node, "lineno", 0)
        if what not in found.setdefault(line, []):
            found[line].append(what)

    def writes(node: ast.AST, target: ast.expr | None) -> None:
        where = None if target is None else _place(target, names)
        if where is None:
            add(node, "writes to a file whose place the check cannot work out")
        elif where and where[0] == "..":
            add(node, "writes outside derivations/")

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if why := _module_concern(alias.name, programs):
                    add(node, why)
        elif isinstance(node, ast.ImportFrom):
            module = "." * node.level + (node.module or "")
            if node.level or _module_concern(module, programs):
                for alias in node.names:
                    if why := _module_concern(f"{module}.{alias.name}", programs):
                        add(node, why)
                        break
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            if id(node) not in docstrings and FULL_PATH.match(node.value):
                add(
                    node,
                    f"names a place on this computer by its full path ({node.value})",
                )
        elif isinstance(node, ast.Call):
            func = node.func
            name = (
                func.attr
                if isinstance(func, ast.Attribute)
                else getattr(func, "id", "")
            )
            if name in RUNS_TEXT and isinstance(func, ast.Name):
                add(node, f"runs text as code ({name})")
            elif name in DELETES and isinstance(func, ast.Attribute):
                add(node, f"deletes, renames, or changes a file ({name})")
            elif name in WRITES_TO_ITSELF and isinstance(func, ast.Attribute):
                writes(node, func.value)
            elif name in WRITES_TO_FIRST:
                writes(node, node.args[0] if node.args else None)
            elif name in EXTRACTS and isinstance(func, ast.Attribute):
                add(node, f"unpacks files from an archive ({name})")
            elif name in OPENS:
                # open(path, mode), gzip.open(path, mode), h5py.File(path,
                # mode), ...; or a path's own open(mode)
                own = (
                    name == "open"
                    and isinstance(func, ast.Attribute)
                    and not (
                        isinstance(func.value, ast.Name)
                        and func.value.id in OPENER_MODULES
                    )
                )
                at = 0 if own else 1
                mode = node.args[at] if len(node.args) > at else None
                for k in node.keywords:
                    mode = k.value if k.arg == "mode" else mode
                text = mode.value if isinstance(mode, ast.Constant) else "r"
                if not isinstance(text, str) or set(text) & set("wax+"):
                    target = func.value if own else (
                        node.args[0] if node.args else None)  # fmt: skip
                    writes(node, target)
        if isinstance(node, (ast.BinOp, ast.Attribute, ast.Call, ast.Name)):
            where = _place(node, names) if not isinstance(node, ast.Name) else None
            if where and where[:2] == ["..", ".."]:
                add(node, "reaches outside the audit's workspace")
    return [f"line {line}: {what}" for line in sorted(found) for what in found[line]]


def run_script(
    workspace: Path,
    path: Path,
    keys: Mapping[str, Sequence[str]],
    printed: Mapping[str, str] = {},
    tests: Mapping[str, Sequence[TestData]] = {},
) -> Problems:
    """Run a saved script (``path`` in the workspace); the problems with what
    it did, given the keys it promised for each claim. ``printed`` gives the
    label of the printed number a key stands for, which must be saved as a
    number; ``tests``, what it promised to save about each claim's tests."""
    problems = Problems()
    script = (workspace / path).absolute()  # run from its folder, so not relative
    try:
        done = subprocess.run(
            [sys.executable, str(script)],
            check=False,
            cwd=script.parent,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            env=os.environ | {"PYTHONUTF8": "1"},  # files read as UTF-8 on Windows too
            timeout=TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        problems.add(
            "script-timeout",
            f"The script ran for more than {TIMEOUT // 60} minutes and was stopped.",
        )
        return problems
    if done.returncode != 0:
        tail = "\n".join((done.stderr or done.stdout).strip().splitlines()[-30:])
        problems.add(
            "script-failed",
            f"The script stopped with an error (exit status {done.returncode}). "
            f"The end of what it printed:\n\n```\n{tail}\n```",
        )
        return problems
    for claim, wanted in keys.items():
        out = workspace / output_path(claim)
        if not out.is_file():
            problems.add(
                "no-output",
                f"The script ran but did not write {output_path(claim).as_posix()}.",
            )
            continue
        try:
            doc = read_values(out)
        except ValueError as e:
            problems.add("bad-output", str(e))
            continue
        if doc["script"] != path.as_posix():
            problems.add(
                "bad-output",
                f"{output_path(claim).as_posix()} names {doc['script']} as its "
                "script; pass script=Path(__file__) to write_values.",
            )
        missing = [k for k in wanted if k not in doc["values"]]
        if missing:
            problems.add(
                "key-not-saved",
                f"The script did not save {', '.join(missing)} for claim {claim}; "
                f"it saved {', '.join(sorted(doc['values'])) or 'nothing'}.",
            )
        for k in wanted:
            v = doc["values"].get(k)
            if k in printed and isinstance(v, bool | str):
                problems.add(
                    "not-a-number",
                    f"The script saved {v!r} as {k} for claim {claim}, but {k} "
                    f"stands for the printed number {printed[k]}; save a number.",
                )
        for t in tests.get(claim, ()):
            problems.extend(_test_output_problems(claim, t, doc["values"]))
    return problems


def _test_output_problems(claim: str, t: TestData, saved: Mapping) -> Problems:
    """Problems with what the script saved about one test."""
    problems = Problems()
    where = f"claim {claim}, test {t.test}"
    n, unit = saved.get(t.n), saved.get(t.unit)
    if n is not None and not (isinstance(n, int) and not isinstance(n, bool) and n > 0):
        problems.add(
            "not-a-count", f"For {where}, {t.n} is {n!r}; save N as a whole number."
        )
    if unit is not None and unit not in UNITS:
        problems.add(
            "bad-unit",
            f"For {where}, {t.unit} is {unit!r}; save one of {', '.join(UNITS)}.",
        )
    if t.groups is not None:
        found = group_values(saved, t.groups)
        if not found or any(
            isinstance(x, bool | str) for xs in found.values() for x in xs
        ):
            problems.add(
                "bad-groups",
                f"For {where}, save each group's values as a list of numbers under "
                f"{t.groups}/<group>.",
            )
    return problems


def group_values(saved: Mapping, prefix: str) -> dict[str, list]:
    """Each group's values saved under ``prefix`` (``<prefix>/<group>/<i>``,
    or ``<prefix>/<i>`` for one group, named ``""``), in order."""
    out: dict[str, dict[int, object]] = {}
    for k, v in saved.items():
        if not k.startswith(prefix + "/"):
            continue
        *group, i = k[len(prefix) + 1 :].split("/")
        if not i.isdigit():
            return {}
        out.setdefault("/".join(group), {})[int(i)] = v
    return {g: [xs[i] for i in sorted(xs)] for g, xs in out.items()}


def import_answer(
    workspace: Path,
    settings: Settings,
    reply: str,
    drafted_by: str,
    handoff: str | None = None,
    *,
    approve: Callable[[Path, Sequence[str]], bool],
    announce: Callable[[Path], None] = lambda path: None,
    today: datetime.date | None = None,
) -> tuple[Path | None, list[Problem]]:
    """Check a reply, run its script, and save it.

    A script runs without asking (``announce`` is told first) if the manifest
    says ``derive: run: auto`` and :func:`script_concerns` finds nothing.
    Otherwise ``approve`` is given the saved script and the concerns, and
    says whether to run it; if it does not, nothing is accepted and no
    problems are returned.
    """
    try:
        answer, script = parse_answer(reply)
    except AnswerError as e:
        return None, e.problems
    chosen = handoffs.choose(
        pending_handoffs(workspace),
        handoff,
        [c.claim for c in answer.claims],
        lambda h: [c.claim for c in h.claims],
        STEP,
    )
    if isinstance(chosen, Problem):
        return None, [chosen]
    problems = check_answer(answer, script, chosen, workspace, settings)
    if problems:
        return None, problems
    keys = {
        c.claim: [v.key for v in c.values] + [k for t in c.tests for k in (t.n, t.unit)]
        for c in answer.claims
        if c.values or c.tests
    }
    saved_script = None
    if keys:
        assert script is not None
        rel = script_path([c.claim for c in chosen.claims])
        path = workspace / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(script, encoding="utf-8")
        concerns = script_concerns(script, settings.derive_programs or ())
        if settings.derive_run == "ask" or concerns:
            if not approve(path, concerns):
                return None, []
        else:
            announce(path)
        printed = {
            v.key: v.for_
            for c in answer.claims
            for v in c.values
            if v.for_ not in {f.value for f in Facet}
        }
        tests = {c.claim: c.tests for c in answer.claims if c.tests}
        problems = run_script(workspace, rel, keys, printed, tests)
        if problems:
            return None, problems
        saved_script = rel.as_posix()
    record = Accepted(
        handoff=chosen.name,
        claims=tuple(c.claim for c in chosen.claims),
        drafted_by=drafted_by,
        imported=(today or datetime.date.today()).isoformat(),
        answer=answer,
        script=saved_script,
        outputs={c: output_path(c).as_posix() for c in keys},
    )
    return handoffs.save_answer(workspace, STEP, chosen.name, record), []


# --- Record observations ----------------------------------------------------


def derived_observations(
    workspace: Path, settings: Settings
) -> dict[str, dict[Facet, list[Observation]]]:
    """Each claim's recomputed values as observations, by claim and facet.

    A value from the authors' code, run, is an output observation; one the
    audit computed itself is a data observation. Each names the script and
    output that hold it, so the check reads it back. A value the code sets
    is a code observation quoting the lines that set it.
    """
    stated = stated_values(workspace)
    out: dict[str, dict[Facet, list[Observation]]] = {}
    claims = [(a, c) for a in read_accepted(workspace) for c in a.answer.claims]
    for _, c in claims:
        for k in c.in_code:
            s = stated.get(c.claim, {}).get(k.for_)
            obs = _in_code_observation(k, s, workspace, settings)
            facet = s.facet if s else Facet(k.for_)
            out.setdefault(c.claim, {}).setdefault(facet, []).append(obs)
    for a, c in claims:
        if a.script is None or c.claim not in a.outputs:
            continue
        output = a.outputs[c.claim]
        values = read_values(workspace / output)["values"]
        derivation = Derivation(script=a.script, output=output)
        for v in c.values:
            s = stated.get(c.claim, {}).get(v.for_)
            facet = s.facet if s else Facet(v.for_)
            printed = read_printed(s.printed) if s else None
            got = Value(
                name=s.name if s else v.name or v.key,
                value=values[v.key],
                unit=printed.unit if printed else None,
                subject=s.subject if s else None,
                key=v.key,
            )
            executed = v.how == "executed"
            out.setdefault(c.claim, {}).setdefault(facet, []).append(
                Observation(
                    source=Source.OUTPUT if executed else Source.DATA,
                    statement=f"{v.derivation}: {got.value!r}",
                    obtained=Obtained.EXECUTED if executed else Obtained.RECOMPUTED,
                    anchor=DataAnchor(
                        file=v.source,
                        derivation=v.derivation,
                        produced_by=derivation,
                        quote=f"{v.key} = {got.value!r}",
                    ),
                    values=(got,),
                )
            )
    return out


def _in_code_observation(
    k: InCode, stated: Stated | None, workspace: Path, settings: Settings
) -> Observation:
    if settings.code is None:
        raise ValueError("the manifest gives no code")
    root = workspace / "materials" / settings.code.path
    lines = code_lines(root, k.file, settings.code.commit) or []
    first, last = k.lines
    got = _setting_value(k, stated)
    return Observation(
        source=Source.CODE,
        statement=f"the code sets {got.name} to {got.value!r}",
        obtained=Obtained.READ,
        anchor=CodeAnchor(
            file=f"{settings.code.path}/{k.file.lstrip('/')}",
            line_start=first,
            line_end=last,
            commit=settings.code.commit,
            quote="\n".join(lines[first - 1 : last]),
        ),
        values=(got,),
    )


def cannot(workspace: Path) -> dict[str, dict[str, str]]:
    """Why each value that cannot be recomputed cannot, by claim and label."""
    return {
        c.claim: {x.for_: x.reason for x in c.cannot}
        for a in read_accepted(workspace)
        for c in a.answer.claims
    }
