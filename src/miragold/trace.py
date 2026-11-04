# Copyright (c) 2026, Joshua I. Gold
# SPDX-License-Identifier: BSD-2-Clause
"""Trace each facet to the Methods and the code (decisions 0009, 0011).

After decomposing, each new-result claim's facets are handed to an
assistant with the Methods paragraphs and a link to the authors' code
repository at the commit the manifest records (``miragold/instructions/
trace.md``); a coding assistant, which reads the workspace itself, gets the
Methods once in :data:`METHODS` instead. For each facet the answer cites the Methods passages that
describe it and the code lines that compute it, each quoted exactly.

Procedure claims are not split into facets; each is traced whole (decision
0017). The answer copies the numbers the claim states, as printed, and
cites the Methods passages and the code lines that carry it out, each code
passage with the values it sets. :func:`procedure_observations` turns these
into the claim's own observation, with its values, and its Methods and code
observations.

:func:`check_answer` checks every citation against the workspace's own
copy: Methods quotes against the extracted paragraphs, and code quotes
against the cited lines of the local copy of the code, at the commit when
that copy is a git repository. So the assistant browses the public
repository, but nothing it reports enters the record unless the local
materials show it. Accepted answers are kept in ``work/trace/answers/``;
:func:`trace_observations` turns them into the record's Methods and code
observations.

When there is no public repository, when the manifest's settings ask for
it (``code_access: index``), when the code holds a Jupyter notebook (whose
lines are counted in its code cells, not in the file a browser shows; see
``miragold.codeindex``), or when an assistant answers that it cannot
open the repository (``no_access``), the handoff carries an index of the
code instead (``miragold.codeindex``). The assistant answers with the
lines it wants to read (``requests``); the next handoff shows them, with
line numbers, and the assistant may then cite only lines it was shown.
Each request is kept in ``work/trace/asked/``, so a stopped audit picks up
at the right round.
"""

from __future__ import annotations

import datetime
from collections.abc import Sequence
from enum import StrEnum
from fractions import Fraction
from pathlib import Path, PurePosixPath

from pydantic import Field, model_validator

from miragold import codeindex, decompose, handoffs, instructions, segment
from miragold.codeindex import code_lines
from miragold.handoffs import AnswerError, Problem, Problems
from miragold.paragraphs import PARAGRAPHS, Paragraph, read_paragraphs
from miragold.schema import (
    ClaimId,
    ClaimType,
    CodeAnchor,
    Facet,
    Frozen,
    ManuscriptAnchor,
    NonEmptyStr,
    Observation,
    Obtained,
    Relation,
    Source,
    Value,
)
from miragold.settings import Code, Settings
from miragold.words import plural

STEP = "trace"
MAX_CLAIMS = 8
"""New-result claims per handoff; each handoff also carries all of the Methods."""
MAX_PROCEDURES = 15
"""Procedure claims per handoff; each is traced whole, so more fit."""
SCALES = {
    "ms": ("time", Fraction(1, 1000)), "s": ("time", Fraction(1)),
    "min": ("time", Fraction(60)), "h": ("time", Fraction(3600)),
    "Hz": ("frequency", Fraction(1)), "kHz": ("frequency", Fraction(1000)),
    "%": ("proportion", Fraction(1, 100)), "fraction": ("proportion", Fraction(1)),
}  # fmt: skip
"""Units a procedure's value is converted between, when the code works in
another unit than the claim: each unit's kind and its size in that kind."""
METHODS = PurePosixPath("work") / STEP / "methods.md"
"""The Methods, written once for a coding assistant instead of in every task."""
MAX_LINES = 60
"""Longest code passage one citation may cover."""
MAX_REQUEST_LINES = 2000
"""Most new lines of code one request may ask for."""
MAX_ROUNDS = 4
"""Handoffs in one chain of requests, counting the first."""
ASKED = PurePosixPath("work", STEP, "asked")
NOUNS = {
    "claims": "claim",
    "facets": "facet",
    "methods": "Methods passage",
    "code": "code passage",
    "requests": "request",
    "tests": "test",
    "settings": "setting",
    "assumptions": "assumption",
    "values": "value",
}


class MethodsCite(Frozen):
    paragraph: NonEmptyStr
    quote: NonEmptyStr
    states: NonEmptyStr


class CodeCite(Frozen):
    file: NonEmptyStr
    lines: tuple[int, int]
    quote: NonEmptyStr
    states: NonEmptyStr

    @model_validator(mode="after")
    def _ordered(self) -> CodeCite:
        first, last = self.lines
        if first < 1 or last < first:
            raise ValueError("lines must be [first, last], with 1 <= first <= last")
        return self


class FacetTrace(Frozen):
    facet: Facet
    methods: tuple[MethodsCite, ...] = ()
    code: tuple[CodeCite, ...] = ()
    notes: str | None = None


class Setting(StrEnum):
    """A setting of a statistical test that the text and the code can both
    state (decision 0015, items 5, 7, and 8)."""

    DESIGN = "design"
    TAILS = "tails"
    EQUAL_VARIANCES = "equal_variances"
    CORRECTION = "correction"
    RESAMPLES = "resamples"
    RESAMPLED = "resampled"
    CI_METHOD = "ci_method"
    SEED = "seed"


SAYS: dict[Setting, tuple[str, ...] | None] = {
    Setting.DESIGN: ("independent", "paired", "one-sample"),
    Setting.TAILS: ("1", "2"),
    Setting.EQUAL_VARIANCES: ("assumed", "not_assumed"),
    Setting.CORRECTION: (
        "none",
        "bonferroni",
        "holm",
        "sidak",
        "fdr",
        "tukey",
        "other",
    ),
    Setting.RESAMPLES: None,
    Setting.RESAMPLED: ("trials", "sessions", "subjects", "cells", "animals", "other"),
    Setting.CI_METHOD: ("percentile", "bca", "basic", "normal", "other"),
    Setting.SEED: ("set", "not_set"),
}
"""The words each setting is stated in; ``None`` for a number, as printed."""


class Assumption(StrEnum):
    NORMALITY = "normality"
    EQUAL_VARIANCES = "equal_variances"


CHECKS = (
    "shapiro_wilk", "kolmogorov_smirnov", "anderson_darling", "dagostino", "levene",
    "bartlett", "brown_forsythe", "plot", "reason", "other",
)  # fmt: skip
"""The words a check of an assumption is named in; ``reason`` for a stated
reason for the choice of test, ``plot`` for a figure of the values."""


class MethodsSays(MethodsCite):
    says: NonEmptyStr


class CodeSays(CodeCite):
    says: NonEmptyStr


class SettingTrace(Frozen):
    setting: Setting
    methods: MethodsSays | None = None
    code: CodeSays | None = None


class AssumptionTrace(Frozen):
    assumption: Assumption
    methods: tuple[MethodsSays, ...] = ()
    code: tuple[CodeSays, ...] = ()


class TestTrace(Frozen):
    """Where the Methods and the code state the settings of one reported
    test, and any check of its assumptions."""

    test: int
    """The test's number, as the task lists it, from 1."""
    settings: tuple[SettingTrace, ...] = ()
    assumptions: tuple[AssumptionTrace, ...] = ()


class CodeValue(decompose.StatedValue):
    unit: str | None = None
    """The code's unit, when it differs from the claim's, e.g. ``s`` for a
    claim in ms; one of :data:`SCALES`."""


class ProcedureCode(CodeCite):
    values: tuple[CodeValue, ...] = ()
    """Each value these lines set that the claim states, as the code prints it."""


class ClaimTrace(Frozen):
    id: ClaimId
    facets: tuple[FacetTrace, ...] = ()
    tests: tuple[TestTrace, ...] = ()
    values: tuple[decompose.StatedValue, ...] = ()
    """For a procedure, traced whole: each number the claim states, as printed."""
    methods: tuple[MethodsCite, ...] = ()
    """For a procedure: the Methods passages that describe it."""
    code: tuple[ProcedureCode, ...] = ()
    """For a procedure: the code lines that carry it out."""
    notes: str | None = None


class CodeRequest(Frozen):
    file: NonEmptyStr
    lines: tuple[int, int] | None = None
    """``[first, last]``, or the whole file if not given."""

    @model_validator(mode="after")
    def _ordered(self) -> CodeRequest:
        if self.lines is not None and not 1 <= self.lines[0] <= self.lines[1]:
            raise ValueError("lines must be [first, last], with 1 <= first <= last")
        return self


class TraceAnswer(Frozen):
    instructions: NonEmptyStr
    claims: tuple[ClaimTrace, ...] = ()
    requests: tuple[CodeRequest, ...] = ()
    """Code the assistant wants to read, when it was given an index."""
    no_access: str | None = None
    """Why the assistant could not open the repository, if it could not."""
    task: str | None = None
    """The task's name, which a request or ``no_access`` answer gives, since it
    names no claims."""


def parse_answer(text: str) -> TraceAnswer:
    return handoffs.parse_reply(text, TraceAnswer, NOUNS)


# --- The local copy of the code ---------------------------------------------


def _same_lines(quote: str, cited: Sequence[str]) -> bool:
    """Whether ``quote`` is the cited lines, ignoring indentation and blank lines."""

    def norm(lines):
        return [line.strip() for line in lines if line.strip()]

    return norm(quote.split("\n")) == norm(cited)


def _first_difference(quote: str, cited: Sequence[str], first: int) -> str:
    """Where ``quote`` first differs from the cited lines, said in words."""
    quoted = [line.strip() for line in quote.split("\n") if line.strip()]
    numbered = [(first + i, line.strip()) for i, line in enumerate(cited)]
    numbered = [(n, line) for n, line in numbered if line]
    for (n, line), q in zip(numbered, quoted):
        if line != q:
            return f"line {n} there is {line!r}, but the quote has {q!r}"
    if len(quoted) > len(numbered):
        return f"the quote goes on past line {first + len(cited) - 1}: {quoted[len(numbered)]!r}"
    n, line = numbered[len(quoted)]
    return f"the quote stops before line {n}: {line!r}"


# --- Checking ---------------------------------------------------------------


class ShownCode(Frozen):
    file: NonEmptyStr
    first: int
    lines: tuple[str, ...]

    @property
    def last(self) -> int:
        return self.first + len(self.lines) - 1


class Handoff(Frozen):
    name: NonEmptyStr
    instructions: NonEmptyStr
    base: NonEmptyStr
    """The first handoff's name, shared by every round of its requests."""
    round: int = 1
    link: str | None
    """The repository at the commit, for the assistant to browse; ``None`` when
    the handoff carries the index instead."""
    index: str | None = None
    shown: tuple[ShownCode, ...] = ()
    """Code sent because the assistant asked for it."""
    claims: dict[str, str]
    facets: dict[str, dict[str, str]]
    """Claim ID to facet to what the Results state about it."""
    procedures: dict[str, str] = Field(default_factory=dict)
    """Procedure claim ID to its paragraph's label; each is traced whole."""
    tests: dict[str, tuple[str, ...]] = Field(default_factory=dict)
    """Claim ID to the tests it reports, as printed, in order."""
    methods: dict[str, str]
    """Methods paragraph label to text."""
    places: dict[str, str]


def check_answer(
    answer: TraceAnswer, handoff: Handoff, code_root: Path, commit: str | None
) -> Problems:
    """Everything wrong with ``answer``, as sentences; empty if nothing is."""
    problems = handoffs.version_problem(STEP, answer.instructions)
    answered = [c.id for c in answer.claims]
    for claim_id in sorted({i for i in answered if answered.count(i) > 1}):
        problems.add("claim-repeated", f"Claim {claim_id} is answered more than once.")
    for claim_id in sorted(set(answered) - set(handoff.claims)):
        problems.add(
            "claim-not-given",
            f"Claim {claim_id} was not given; answer only the claims given.",
        )
    for claim_id in [i for i in handoff.claims if i not in answered]:
        problems.add(
            "claim-missing", f"Claim {claim_id} has no answer; give every facet of it."
        )

    for c in answer.claims:
        if c.id in handoff.procedures:
            _check_procedure(problems, c, handoff, code_root, commit)
            continue
        expected = handoff.facets.get(c.id)
        if expected is None:
            continue
        if c.values or c.methods or c.code:
            problems.add(
                "not-whole",
                f"Claim {c.id} is split into facets: give its Methods passages and "
                "code under each facet, not for the claim as a whole.",
            )
        given = [f.facet.value for f in c.facets]
        for facet in sorted({f for f in given if given.count(f) > 1}):
            problems.add(
                "facet-repeated",
                f"Claim {c.id} gives the {facet} facet more than once.",
            )
        for facet in sorted(set(given) - set(expected)):
            problems.add(
                "facet-unknown",
                f"Claim {c.id} has no {facet} facet; give only its facets "
                f"({', '.join(expected)}).",
            )
        for facet in [f for f in expected if f not in given]:
            problems.add("facet-missing", f"Claim {c.id} is missing its {facet} facet.")
        for f in c.facets:
            where = f"claim {c.id}, {f.facet.value}"
            for m in f.methods:
                _check_methods(problems, where, m, handoff)
            for k in f.code:
                _check_code(problems, where, k, handoff, code_root, commit)
        _check_tests(problems, c, handoff, code_root, commit)
    return problems


def _check_procedure(
    problems: Problems,
    c: ClaimTrace,
    handoff: Handoff,
    code_root: Path,
    commit: str | None,
) -> None:
    """Problems with a procedure, traced whole: no facets or tests, and every
    value printed in its claim or its code passage, as one number."""
    if c.facets or c.tests:
        problems.add(
            "whole",
            f"Claim {c.id} is a procedure, traced whole: give its values, Methods "
            "passages, and code for the claim itself, with no facets or tests.",
        )
    _check_values(problems, f"claim {c.id}", c.values, handoff.claims[c.id], "claim")
    for m in c.methods:
        _check_methods(problems, f"claim {c.id}", m, handoff)
    for k in c.code:
        where = f"claim {c.id}"
        _check_code(problems, where, k, handoff, code_root, commit)
        _check_values(problems, where, k.values, k.quote, "code passage")
        for v in k.values:
            if v.unit is not None and v.unit not in SCALES:
                problems.add(
                    "unit-unknown",
                    f"In {where}: the unit {v.unit!r} of {v.name} is not one the "
                    f"tool converts ({', '.join(SCALES)}); leave it out.",
                )


def _check_values(
    problems: Problems,
    where: str,
    values: Sequence[decompose.StatedValue],
    quote: str,
    what: str,
) -> None:
    for v in values:
        if v.printed not in quote:
            problems.add(
                "value-not-in-quote",
                f"In {where}: the value {v.printed!r} ({v.name}) is not in the "
                f"{what} word for word.",
            )
        elif decompose.read_printed(v.printed) is None:
            problems.add(
                "value-not-a-number",
                f"In {where}: the value {v.printed!r} ({v.name}) is not a single "
                "number as printed; copy just the number with its unit, e.g. "
                "'500 ms' or '0.01'. Give a version or a name in notes instead.",
            )


def _check_methods(
    problems: Problems, where: str, m: MethodsCite, handoff: Handoff
) -> None:
    text = handoff.methods.get(m.paragraph)
    if text is None:
        problems.add(
            "unknown-paragraph",
            f"In {where}: {m.paragraph} is not a Methods paragraph given.",
        )
    elif (n := text.count(m.quote)) != 1:
        problems.add(
            "quote-not-found" if n == 0 else "quote-not-unique",
            f"In {where}: the Methods quote "
            + (
                f"is not in paragraph {m.paragraph} word for word"
                if n == 0
                else f"appears {n} times in paragraph {m.paragraph}; make it "
                "longer so it appears once"
            )
            + f": {m.quote!r}",
        )


def _check_code(
    problems: Problems,
    where: str,
    k: CodeCite,
    handoff: Handoff,
    code_root: Path,
    commit: str | None,
) -> None:
    lines = code_lines(code_root, k.file, commit)
    first, last = k.lines
    if lines is None:
        problems.add(
            "file-not-found",
            f"In {where}: {k.file} is not in the repository at this version.",
        )
    elif last > len(lines):
        problems.add(
            "lines-past-end",
            f"In {where}: {k.file} has only {len(lines)} lines, not {last}.",
        )
    elif last - first + 1 > MAX_LINES:
        problems.add(
            "too-many-lines",
            f"In {where}: lines {first}–{last} of {k.file} are too many to "
            f"cite at once; cite at most {MAX_LINES} lines per place.",
        )
    elif handoff.link is None and not _was_shown(handoff, k.file, first, last):
        problems.add(
            "lines-not-shown",
            f"In {where}: lines {first}–{last} of {k.file} were not sent to "
            "you; cite only lines you were shown, or ask for these with "
            "requests.",
        )
    elif not _same_lines(k.quote, lines[first - 1 : last]):
        problems.add(
            "lines-do-not-match",
            f"In {where}: the quote is not lines {first}–{last} of {k.file} "
            f"at this version; {_first_difference(k.quote, lines[first - 1 : last], first)}.",
        )


def _check_says(problems: Problems, where: str, says: str, allowed) -> None:
    if allowed is None:
        if decompose.read_printed(says) is None:
            problems.add(
                "says-not-a-number",
                f"In {where}: says must be the number as printed, not {says!r}.",
            )
    elif says not in allowed:
        problems.add(
            "says-unknown",
            f"In {where}: says must be one of {', '.join(allowed)}, not {says!r}.",
        )


def _check_tests(
    problems: Problems,
    c: ClaimTrace,
    handoff: Handoff,
    code_root: Path,
    commit: str | None,
) -> None:
    """Problems with a claim's tests: one entry for each test the task lists,
    each setting and assumption once, every quote found, every word allowed."""
    count = len(handoff.tests.get(c.id, ()))
    given = [t.test for t in c.tests]
    for n in sorted({n for n in given if given.count(n) > 1}):
        problems.add("test-repeated", f"Claim {c.id} gives test {n} more than once.")
    for n in sorted({n for n in given if not 1 <= n <= count}):
        problems.add(
            "test-unknown",
            f"Claim {c.id} has no test {n}; "
            + (f"its tests are 1 to {count}." if count else "it reports no test."),
        )
    for n in [n for n in range(1, count + 1) if n not in given]:
        problems.add(
            "test-missing",
            f"Claim {c.id} has no entry for test {n}; give one, with empty lists "
            "if the Methods and the code state none of its settings.",
        )
    for t in c.tests:
        for named in (
            [s.setting.value for s in t.settings],
            [a.assumption.value for a in t.assumptions],
        ):
            for what in sorted({x for x in named if named.count(x) > 1}):
                problems.add(
                    "test-part-repeated",
                    f"Claim {c.id}, test {t.test} gives {what} more than once.",
                )
        for s in t.settings:
            where = f"claim {c.id}, test {t.test}, {s.setting.value}"
            if s.methods is None and s.code is None:
                problems.add(
                    "setting-empty",
                    f"In {where}: give where the Methods or the code state it, or "
                    "leave the setting out.",
                )
            for cite in [x for x in (s.methods, s.code) if x is not None]:
                _check_says(problems, where, cite.says, SAYS[s.setting])
            if s.methods is not None:
                _check_methods(problems, where, s.methods, handoff)
            if s.code is not None:
                _check_code(problems, where, s.code, handoff, code_root, commit)
        for a in t.assumptions:
            where = f"claim {c.id}, test {t.test}, {a.assumption.value}"
            for m in a.methods:
                _check_says(problems, where, m.says, CHECKS)
                _check_methods(problems, where, m, handoff)
            for k in a.code:
                _check_says(problems, where, k.says, CHECKS)
                _check_code(problems, where, k, handoff, code_root, commit)


def _clean(file: str) -> str:
    return PurePosixPath(file.lstrip("/")).as_posix()


def _was_shown(handoff: Handoff, file: str, first: int, last: int) -> bool:
    return any(
        s.file == _clean(file) and s.first <= first and last <= s.last
        for s in handoff.shown
    )


def _ranges(
    requests: Sequence[CodeRequest], code_root: Path, commit: str | None
) -> dict[str, list[tuple[int, int]]]:
    """Requested lines by file, merged, for the files that exist."""
    spans: dict[str, list[tuple[int, int]]] = {}
    for r in requests:
        lines = code_lines(code_root, r.file, commit)
        if lines is None:
            continue
        first, last = r.lines or (1, len(lines))
        spans.setdefault(_clean(r.file), []).append((first, min(last, len(lines))))
    merged = {}
    for file, pairs in spans.items():
        out: list[tuple[int, int]] = []
        for first, last in sorted(pairs):
            if out and first <= out[-1][1] + 1:
                out[-1] = (out[-1][0], max(out[-1][1], last))
            else:
                out.append((first, last))
        merged[file] = out
    return merged


def check_requests(
    answer: TraceAnswer, handoff: Handoff, code_root: Path, commit: str | None
) -> Problems:
    """Everything wrong with a request for code, as sentences."""
    problems = handoffs.version_problem(STEP, answer.instructions)
    if handoff.link is not None:
        problems.add(
            "requests-with-link",
            "This task gave a link to the repository, so there is no code to ask "
            "for; read it there, or answer with no_access if the link does not "
            "open.",
        )
        return problems
    if answer.claims:
        problems.add(
            "requests-and-claims",
            "Send either requests for code or your answer for the claims, not both.",
        )
    if handoff.round >= MAX_ROUNDS:
        problems.add(
            "no-more-rounds",
            "No more code can be sent for these claims. Answer with what you have "
            "been shown, leaving the code list empty where you found nothing.",
        )
    for r in answer.requests:
        lines = code_lines(code_root, r.file, commit)
        if lines is None:
            problems.add(
                "file-not-found",
                f"{r.file} is not in the index; ask only for files listed there.",
            )
        elif r.lines is not None and r.lines[1] > len(lines):
            problems.add(
                "lines-past-end",
                f"{r.file} has only {len(lines)} lines, not {r.lines[1]}.",
            )
    new = _new_lines(answer.requests, handoff, code_root, commit)
    if new > MAX_REQUEST_LINES:
        problems.add(
            "request-too-long",
            f"That is {new} new lines of code; ask for at most {MAX_REQUEST_LINES} "
            "at a time, choosing the functions you need from the index.",
        )
    if not answer.requests and not problems:
        problems.add(
            "empty-answer", "The answer asks for no code and answers no claims."
        )
    return problems


def _new_lines(
    requests: Sequence[CodeRequest],
    handoff: Handoff,
    code_root: Path,
    commit: str | None,
) -> int:
    return sum(
        1
        for file, spans in _ranges(requests, code_root, commit).items()
        for first, last in spans
        for line in range(first, last + 1)
        if not _was_shown(handoff, file, line, line)
    )


# --- Handoffs and import ----------------------------------------------------


class Accepted(Frozen):
    handoff: NonEmptyStr
    claims: tuple[str, ...]
    commit: str | None
    """The commit the code was checked at, or ``None`` for the working tree."""
    drafted_by: NonEmptyStr
    imported: NonEmptyStr
    answer: TraceAnswer


class Asked(Frozen):
    """An answer that asked for code, or said the repository would not open."""

    handoff: NonEmptyStr
    base: NonEmptyStr
    round: int
    claims: tuple[str, ...]
    no_access: str | None = None
    requests: tuple[CodeRequest, ...] = ()
    drafted_by: NonEmptyStr
    imported: NonEmptyStr


def read_accepted(workspace: Path) -> list[Accepted]:
    return handoffs.read_answers(workspace, STEP, Accepted)


def read_asked(workspace: Path) -> list[Asked]:
    folder = workspace / ASKED
    if not folder.is_dir():
        return []
    return [
        Asked.model_validate_json(p.read_text(encoding="utf-8"))
        for p in sorted(folder.glob("*.json"))
    ]


def _answered(workspace: Path) -> set[str]:
    return {a.handoff for a in read_accepted(workspace)} | {
        a.handoff for a in read_asked(workspace)
    }


def pending_handoffs(workspace: Path) -> list[Handoff]:
    return handoffs.read_pending(workspace, STEP, Handoff, _answered(workspace))


def _is_methods(p: Paragraph) -> bool:
    return "method" in p.top.lower()


def _methods(workspace: Path) -> list[Paragraph]:
    return [p for p in read_paragraphs(workspace / PARAGRAPHS) if _is_methods(p)]


def _code(workspace: Path, settings: Settings) -> tuple[Code, Path]:
    """The manifest's code entry and the local copy's folder."""
    if settings.code is None:
        raise ValueError("the manifest gives no code (materials › code › path)")
    return settings.code, workspace / "materials" / settings.code.path


def _round_name(base: str, n: int) -> str:
    return base if n == 1 else f"{base}-round{n}"


def plan_handoffs(
    workspace: Path,
    settings: Settings,
    max_claims: int = MAX_CLAIMS,
    max_procedures: int = MAX_PROCEDURES,
) -> list[Handoff]:
    """Handoffs for the decomposed claims and the procedure claims no
    accepted trace covers yet, each kind batched on its own.

    Claims whose earlier handoff asked for code get the next round of that
    chain; the rest are batched afresh, with the repository link or the index
    as the settings and manifest allow.
    """
    code, code_root = _code(workspace, settings)
    link = code.link()
    if settings.code_access == "repository" and link is None:
        raise ValueError(
            "the manifest gives no code repository and commit "
            "(materials › code › repository and commit)"
        )
    use_link = link is not None and (
        settings.code_access == "repository"
        or (
            settings.code_access == "auto"
            and not any(
                PurePosixPath(f).suffix.lower() == codeindex.NOTEBOOK
                for f in codeindex.list_files(code_root, code.commit)
            )
        )
    )
    done = {i for a in read_accepted(workspace) for i in a.claims}
    answered = _answered(workspace)
    quotes = {c.id: c.quote for c in decompose.to_decompose(workspace)}
    procedures = {c.id: c for c in segment.claims_of(workspace, ClaimType.PROCEDURE)}
    quotes |= {i: c.quote for i, c in procedures.items()}
    facets = {
        c.id: {f.facet.value: f.states for f in c.facets}
        for a in decompose.read_accepted(workspace)
        for c in a.answer.claims
    }
    tests = {
        c.id: tuple(f"{t.named}, {t.quote}" if t.named else t.quote for t in c.tests)
        for a in decompose.read_accepted(workspace)
        for c in a.answer.claims
        if c.tests
    }
    methods = _methods(workspace)
    version = instructions.load(STEP).label
    index_text: list[str] = []

    def index() -> str:
        if not index_text:
            built = codeindex.build_index(code_root, code.commit)
            index_text.append("\n".join(codeindex.render_index(built)).strip())
        return index_text[0]

    def handoff(name, base, n, claims, link=None, shown=()) -> Handoff:
        return Handoff(
            name=name,
            instructions=version,
            base=base,
            round=n,
            link=link,
            index=None if link else index(),
            shown=shown,
            claims={i: quotes[i] for i in claims},
            facets={i: facets[i] for i in claims if i in facets},
            procedures={i: procedures[i].paragraph for i in claims if i in procedures},
            tests={i: tests[i] for i in claims if i in tests},
            methods={p.label: p.text for p in methods},
            places={p.label: p.place for p in methods},
        )

    planned = []
    chains: dict[str, list[Asked]] = {}
    for a in read_asked(workspace):
        chains.setdefault(a.base, []).append(a)
    in_chain: set[str] = set()
    for base, rounds in chains.items():
        rounds.sort(key=lambda a: a.round)
        last = rounds[-1]
        in_chain |= set(last.claims)
        n = last.round + 1
        claims = [
            i for i in last.claims if i not in done and (i in facets or i in procedures)
        ]
        if not claims or _round_name(base, n) in answered:
            continue
        requests = [r for a in rounds for r in a.requests]
        shown = tuple(
            ShownCode(file=file, first=first, lines=tuple(lines[first - 1 : last_]))
            for file, spans in _ranges(requests, code_root, code.commit).items()
            if (lines := code_lines(code_root, file, code.commit)) is not None
            for first, last_ in spans
        )
        planned.append(handoff(_round_name(base, n), base, n, claims, shown=shown))
    for todo, size in (
        ([i for i in quotes if i in facets], max_claims),
        (list(procedures), max_procedures),
    ):
        todo = [i for i in todo if i not in done | in_chain]
        for batch in (todo[k : k + size] for k in range(0, len(todo), size)):
            name = f"trace-{batch[0]}"
            planned.append(handoff(name, name, 1, batch, link if use_link else None))
    return planned


def render_methods(h: Handoff) -> list[str]:
    body = ["## Methods"]
    for label, text in h.methods.items():
        body += ["", f"### Paragraph `{label}` ({h.places[label]})", "", text]
    return body


def render_handoff(h: Handoff, methods_file: Path | None = None) -> str:
    """The task to paste; with ``methods_file``, it names that file instead of
    repeating the Methods."""
    if h.link is not None:
        body = ["", f"The authors' code, at the version the paper used: {h.link}", ""]
    else:
        body = [
            "",
            "The authors' code is not given as a link. An index of it is at the end; "
            "ask for the lines you need (see *Asking for code*)."
            + (
                f" This is round {h.round}; you may ask for code until round "
                f"{MAX_ROUNDS}."
                if h.round < MAX_ROUNDS
                else " This is the last round: answer with what you have been shown."
            ),
            "",
        ]
    if h.facets:
        body += ["## Claims and their facets", ""]
    for i, quote in h.claims.items():
        if i not in h.facets:
            continue
        body.append(f"- `{i}`: {quote}")
        body += [f"  - {facet}: {states}" for facet, states in h.facets[i].items()]
        body += [
            f"  - test {n}: {shown}" for n, shown in enumerate(h.tests.get(i, ()), 1)
        ]
    if h.procedures:
        body += ["", "## Procedures, each traced whole", ""]
        body += [
            f"- `{i}` (paragraph `{label}`): {h.claims[i]}"
            for i, label in h.procedures.items()
        ]
    if methods_file is None:
        body += ["", *render_methods(h)]
    else:
        body += [
            "",
            "## Methods",
            "",
            (
                f"The Methods are in `{methods_file.as_posix()}`, the same for "
                "every trace task: read it once."
            ),
        ]
    if h.shown:
        body += ["", "## Code you asked for"]
        for s in h.shown:
            width = len(str(s.last))
            body += ["", f"### `{s.file}`, lines {s.first}–{s.last}", "", "```"]
            body += [
                f"{s.first + k:>{width}}  {line}" for k, line in enumerate(s.lines)
            ]
            body.append("```")
    if h.index is not None:
        body += ["", "## Index of the code", "", h.index]
    what = f"the {plural(len(h.claims), 'claim')} below"
    return handoffs.render(STEP, h.name, h.instructions, what, body)


def write_handoffs(
    workspace: Path,
    settings: Settings,
    max_claims: int = MAX_CLAIMS,
    max_procedures: int = MAX_PROCEDURES,
    *,
    shared_methods: bool = False,
) -> list[Path]:
    """Write the handoffs still needed; return the files to paste. With
    ``shared_methods``, for an assistant that reads the workspace itself, the
    Methods go once into :data:`METHODS` rather than into every task."""
    planned = plan_handoffs(workspace, settings, max_claims, max_procedures)
    shared = METHODS if shared_methods and planned else None
    if shared is not None:
        (workspace / shared).parent.mkdir(parents=True, exist_ok=True)
        text = "\n".join(["# The paper's Methods", "", *render_methods(planned[0])])
        (workspace / shared).write_text(text + "\n", encoding="utf-8")
    return handoffs.write_handoffs(
        workspace,
        STEP,
        ((h.name, h, render_handoff(h, shared)) for h in planned),
        _answered(workspace),
    )


def import_answer(
    workspace: Path,
    settings: Settings,
    reply: str,
    drafted_by: str,
    handoff: str | None = None,
    today: datetime.date | None = None,
) -> tuple[Path | None, list[Problem]]:
    """Check a reply and, if it has no problems, save it.

    An answer for the claims is saved as accepted (``work/trace/answers/``); a
    request for code, or word that the repository would not open, is saved in
    ``work/trace/asked/``, and the next :func:`write_handoffs` writes the
    handoff that answers it.
    """
    try:
        answer = parse_answer(reply)
    except AnswerError as e:
        return None, e.problems
    pending = pending_handoffs(workspace)
    named = {c.id for c in answer.claims}
    if handoff is not None or answer.task is not None:
        fits = [h for h in pending if h.name in (handoff, answer.task)]
    elif len(pending) == 1:
        fits = pending
    else:
        fits = [h for h in pending if named and named <= set(h.claims)]
    if len(fits) != 1:
        if not pending:
            return None, [
                Problem(
                    "no-handoff-waiting",
                    "No handoff is waiting for an answer; run miragold handoff trace.",
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
    code, code_root = _code(workspace, settings)
    commit = code.commit
    imported = (today or datetime.date.today()).isoformat()

    if answer.no_access is not None or answer.requests:
        if answer.no_access is not None:
            if chosen.link is None:
                return None, [
                    Problem(
                        "no-access-with-index",
                        "This task gives the code in an index, not a link; ask for "
                        "the lines you need with requests.",
                    )
                ]
            if settings.code_access == "repository":
                return None, [
                    Problem(
                        "no-access",
                        f"The assistant could not open the repository "
                        f"({answer.no_access}). The settings ask for the repository "
                        "only (code_access: repository); change that to auto to "
                        "give the assistant an index of the code instead.",
                    )
                ]
            problems = handoffs.version_problem(STEP, answer.instructions)
        else:
            problems = check_requests(answer, chosen, code_root, commit)
        if problems:
            return None, problems
        asked = Asked(
            handoff=chosen.name,
            base=chosen.base,
            round=chosen.round,
            claims=tuple(chosen.claims),
            no_access=answer.no_access,
            requests=answer.requests,
            drafted_by=drafted_by,
            imported=imported,
        )
        path = workspace / ASKED / f"{chosen.name}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(asked.model_dump_json(indent=1) + "\n", encoding="utf-8")
        return path, []

    problems = check_answer(answer, chosen, code_root, commit)
    if problems:
        return None, problems
    record = Accepted(
        handoff=chosen.name,
        claims=tuple(chosen.claims),
        commit=commit,
        drafted_by=drafted_by,
        imported=imported,
        answer=answer,
    )
    return handoffs.save_answer(workspace, STEP, chosen.name, record), []


# --- Record observations ----------------------------------------------------


def trace_observations(
    workspace: Path, settings: Settings
) -> dict[str, dict[Facet, list[Observation]]]:
    """Each traced facet's Methods and code observations, by claim and facet.

    Code observations quote the lines of the local copy, not the assistant's
    copy of them, and carry the commit they were checked at.
    """
    cite = Citations(workspace, settings)
    out: dict[str, dict[Facet, list[Observation]]] = {}
    for a in read_accepted(workspace):
        for c in a.answer.claims:
            for f in c.facets:
                found = out.setdefault(c.id, {}).setdefault(f.facet, [])
                found += [cite.methods(m) for m in f.methods]
                found += [cite.code(k, a.commit) for k in f.code]
    return out


def procedure_observations(
    workspace: Path, settings: Settings
) -> dict[str, list[Observation]]:
    """Each traced procedure's observations, by claim: first the claim itself,
    with the values it states (from the Methods or the Results, wherever the
    claim is), then the Methods passages and the code that carry it out, the
    code with the values it sets."""
    claims = {c.id: c for c in segment.claims_of(workspace, ClaimType.PROCEDURE)}
    paragraphs = {p.label: p for p in read_paragraphs(workspace / PARAGRAPHS)}
    cite = Citations(workspace, settings)
    out: dict[str, list[Observation]] = {}
    for a in read_accepted(workspace):
        for c in a.answer.claims:
            if c.id not in claims:
                continue
            p = paragraphs[claims[c.id].paragraph]
            start, quote = p.locate(claims[c.id].quote)
            own = Observation(
                source=Source.METHODS if _is_methods(p) else Source.RESULTS,
                statement=quote,
                obtained=Obtained.QUOTED,
                anchor=ManuscriptAnchor(
                    file=settings.manuscript,
                    section=p.section,
                    paragraph=p.number,
                    char_start=start,
                    char_end=start + len(quote),
                    page=p.page_at(start),
                    quote=quote,
                ),
                values=tuple(
                    _value(v, printed)
                    for v, printed in zip(
                        c.values, decompose.read_stated(c.values, quote)
                    )
                ),
            )
            out[c.id] = [
                own,
                *_converted(own, c),
                *(cite.methods(m) for m in c.methods),
                *(
                    cite.code(k, a.commit).model_copy(
                        update={"values": tuple(_value(v, code=True) for v in k.values)}
                    )
                    for k in c.code
                ),
            ]
    return out


def _converted(own: Observation, c: ClaimTrace) -> list[Observation]:
    """The claim's values in the code's units, where the code works in another
    unit of the same kind, so they can be compared (decision 0017)."""
    stated = {v.name: v for v in own.values}
    out = []
    for k in c.code:
        for v in k.values:
            s = stated.get(v.name)
            if v.unit is None or s is None or s.unit not in SCALES or s.unit == v.unit:
                continue
            (kind, size), (code_kind, code_size) = SCALES[s.unit], SCALES[v.unit]
            if kind != code_kind:
                continue
            x = float(Fraction(repr(s.value)) * size / code_size)
            out.append(
                own.model_copy(
                    update={
                        "statement": f"{s.name} {s.printed()} is {x:g} {v.unit}.",
                        "obtained": Obtained.COMPUTED,
                        "values": (
                            Value(name=s.name, value=x, unit=v.unit, subject=s.subject),
                        ),
                    }
                )
            )
    return list({o.statement: o for o in out}.values())


def _value(
    v: decompose.StatedValue,
    printed: decompose.Printed | None = None,
    code: bool = False,
) -> Value:
    """A value read from its printed text, unless ``printed`` gives it already
    read; one the code sets is plain (=, no decimals), as an obtained value is."""
    printed = printed or decompose.read_printed(v.printed)
    if printed is None:
        raise ValueError(f"{v.printed!r} is not a number")
    return Value(
        name=v.name,
        value=printed.value,
        unit=(v.unit if isinstance(v, CodeValue) else None) or printed.unit,
        subject=v.subject,
        relation=Relation.EQ if code else printed.relation,
        decimals=None if code else printed.decimals,
    )


class Citations:
    """Observations from an accepted answer's citations."""

    def __init__(self, workspace: Path, settings: Settings):
        self.workspace = workspace
        self.settings = settings
        self.paragraphs = {p.label: p for p in _methods(workspace)}

    def methods(self, m: MethodsCite, statement: str | None = None) -> Observation:
        p = self.paragraphs[m.paragraph]
        start, quote = p.locate(m.quote)
        return Observation(
            source=Source.METHODS,
            statement=statement or m.states,
            obtained=Obtained.QUOTED,
            anchor=ManuscriptAnchor(
                file=self.settings.manuscript,
                section=p.section,
                paragraph=p.number,
                char_start=start,
                char_end=start + len(quote),
                page=p.page_at(start),
                quote=quote,
            ),
        )

    def code(
        self, k: CodeCite, commit: str | None, statement: str | None = None
    ) -> Observation:
        code = self.settings.code
        if code is None:
            raise ValueError("the manifest gives no code")
        root = self.workspace / "materials" / code.path
        lines = code_lines(root, k.file, commit) or []
        first, last = k.lines
        return Observation(
            source=Source.CODE,
            statement=statement or k.states,
            obtained=Obtained.READ,
            anchor=CodeAnchor(
                file=f"{code.path}/{k.file.lstrip('/')}",
                line_start=first,
                line_end=last,
                commit=commit,
                quote="\n".join(lines[first - 1 : last]),
            ),
        )
