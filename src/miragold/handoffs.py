# Copyright (c) 2026, Joshua I. Gold
# SPDX-License-Identifier: BSD-2-Clause
"""What every step done by an assistant shares (decision 0011).

A step hands the assistant a file to paste (a *handoff*): the step's
written instructions (:mod:`miragold.instructions`), then the material
for one task. The assistant replies with JSON. The step checks the reply
and, if it has no problems, saves it as accepted. The files live under
``work/<step>/``:

- ``handoffs/<name>.md``, to paste, and ``handoffs/<name>.json``, what was
  handed off, for the check;
- ``answers/<name>.json``, the accepted reply, with who or what drafted it
  and when (decision 0010).

The steps (:mod:`miragold.segment`, :mod:`miragold.decompose`) define
what a handoff holds and how a reply is checked; this module reads replies,
describes unreadable ones in words, and keeps the files.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Collection, Iterable, Mapping, Sequence
from pathlib import Path
from typing import Self

from pydantic import BaseModel, ValidationError

from miragold import instructions

FENCE = re.compile(r"```(?:json)?\s*\n(.*?)```", re.DOTALL)


class Problem(str):
    """A problem with an answer: plain words to paste back to the assistant,
    and a fixed ``kind`` (``quote-not-found``) for feedback reports, which
    count kinds and never carry the words (decision 0012)."""

    kind: str

    def __new__(cls, kind: str, text: str) -> Self:
        problem = super().__new__(cls, text)
        problem.kind = kind
        return problem


class Problems(list[Problem]):
    def add(self, kind: str, text: str) -> None:
        self.append(Problem(kind, text))


def kind(problem: str) -> str:
    """A problem's kind; ``other`` for one given as plain words only."""
    return getattr(problem, "kind", "other")


class AnswerError(ValueError):
    """A reply that could not be read; ``problems`` says why."""

    def __init__(self, problems: list[Problem]) -> None:
        super().__init__("\n".join(problems))
        self.problems = problems


def parse_reply[M: BaseModel](
    text: str, model: type[M], nouns: Mapping[str, str] = {}
) -> M:
    """Read a reply as ``model``: bare JSON, or the first fenced block in it.

    ``nouns`` names the items of a list field for error messages, e.g.
    ``{"claims": "claim"}`` turns ``claims[2].quote`` into "claim 3, quote".
    """
    m = FENCE.search(text)
    body = m.group(1) if m else text
    try:
        data = json.loads(body)
    except json.JSONDecodeError as e:
        raise AnswerError(
            [
                Problem(
                    "not-json",
                    f"The answer is not valid JSON (line {e.lineno}: {e.msg}).",
                )
            ]
        ) from None
    try:
        return model.model_validate(data)
    except ValidationError as e:
        raise AnswerError([_describe(err, nouns) for err in e.errors()]) from None


def _describe(err: dict, nouns: Mapping[str, str]) -> Problem:
    """A pydantic error as a sentence."""
    parts, loc = [], list(err["loc"])
    while loc:
        key = loc.pop(0)
        if key in nouns and loc and isinstance(loc[0], int):
            parts.append(f"{nouns[key]} {loc.pop(0) + 1}")
        else:
            parts.append(str(key))
    where = ", ".join(parts) or "the answer"
    return Problem(
        f"format-{err['type'].replace('_', '-')}", f"In {where}: {err['msg']}."
    )


def version_problem(step: str, named: str) -> Problems:
    """A problem if a reply names other instructions than the current ones.

    The checks start from this list and add to it.
    """
    problems = Problems()
    current = instructions.load(step).label
    if named != current:
        problems.add(
            "old-instructions",
            f"The answer names instructions {named!r}; the current instructions "
            f"are {current!r}.",
        )
    return problems


def claims_problems(answered: Sequence[str], task: Collection[str]) -> Problems:
    """Problems with the claims an answer covers: each of the task's, once."""
    problems = Problems()
    for c in [c for c in task if c not in answered]:
        problems.add("claim-missing", f"The answer has nothing for claim {c}.")
    for c in dict.fromkeys(c for c in answered if c not in task):
        problems.add("unknown-claim", f"Claim {c} is not in this task.")
    for c in dict.fromkeys(c for c in answered if answered.count(c) > 1):
        problems.add("claim-twice", f"Claim {c} is given more than once.")
    return problems


def choose[H](
    pending: Sequence[H],
    name: str | None,
    answered: Collection[str],
    claims_of: Callable[[H], Collection[str]],
    step: str,
) -> H | Problem:
    """The waiting handoff an answer is for: the one named, or else the one
    holding the claims it answers."""
    if name is not None:
        found = [h for h in pending if h.name == name]
        missing = f"No handoff named {name} is waiting for an answer."
    else:
        found = [h for h in pending if answered and set(answered) <= set(claims_of(h))]
        missing = (
            "The answer's claims are not all in any one handoff waiting for an "
            f"answer; run miragold handoff {step}, or say which handoff it "
            "answers with --handoff."
        )
    if not found:
        return Problem("no-handoff-waiting", missing)
    return found[0]


def handoff_dir(workspace: Path, step: str) -> Path:
    return workspace / "work" / step / "handoffs"


def answer_dir(workspace: Path, step: str) -> Path:
    return workspace / "work" / step / "answers"


def read_answers[M: BaseModel](workspace: Path, step: str, model: type[M]) -> list[M]:
    """Every accepted answer for ``step``, by handoff name."""
    return [
        model.model_validate_json(p.read_text(encoding="utf-8"))
        for p in sorted(answer_dir(workspace, step).glob("*.json"))
    ]


def old_answers(workspace: Path, step: str) -> dict[str, str]:
    """Accepted answers for ``step`` that followed older instructions than the
    current ones: handoff name → the instructions the answer names.

    Only new replies are checked against the current instructions; answers
    accepted before a change stay in use until someone deletes them.
    """
    current = instructions.load(step).label
    old = {}
    for p in sorted(answer_dir(workspace, step).glob("*.json")):
        named = json.loads(p.read_text(encoding="utf-8"))["answer"]["instructions"]
        if named != current:
            old[p.stem] = named
    return old


def read_pending[M: BaseModel](
    workspace: Path, step: str, model: type[M], answered: Collection[str]
) -> list[M]:
    """Handoffs for ``step`` written and not yet answered."""
    return [
        model.model_validate(json.loads(p.read_text(encoding="utf-8")))
        for p in sorted(handoff_dir(workspace, step).glob("*.json"))
        if p.stem not in answered
    ]


def write_handoffs(
    workspace: Path,
    step: str,
    handoffs: Iterable[tuple[str, BaseModel, str]],
    answered: Collection[str],
) -> list[Path]:
    """Write ``(name, handoff, text to paste)`` triples; return the files to paste.

    Handoffs left from an earlier run without an accepted answer are removed
    first, so the folder holds only the answered ones and the new ones.
    """
    folder = handoff_dir(workspace, step)
    folder.mkdir(parents=True, exist_ok=True)
    for old in folder.glob("*.*"):
        if old.stem not in answered and old.suffix in (".md", ".json"):
            old.unlink()
    written = []
    for name, handoff, text in handoffs:
        (folder / f"{name}.json").write_text(
            handoff.model_dump_json(indent=1) + "\n", encoding="utf-8"
        )
        md = folder / f"{name}.md"
        md.write_text(text, encoding="utf-8")
        written.append(md)
    return written


def save_answer(workspace: Path, step: str, name: str, accepted: BaseModel) -> Path:
    """Save an accepted answer as ``answers/<name>.json``."""
    path = answer_dir(workspace, step) / f"{name}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(accepted.model_dump_json(indent=1) + "\n", encoding="utf-8")
    return path


def render(step: str, name: str, version: str, what: str, body: list[str]) -> str:
    """The text to paste: the step's instructions, then the task.

    ``what`` says what the task covers ("the 3 paragraphs below"); ``body``
    is the task's material, as Markdown lines.
    """
    lines = [
        instructions.load(step).text.rstrip(),
        "",
        "---",
        "",
        f"# Your task: {name}",
        "",
        f"Follow the instructions above ({version}) for {what}.",
        *body,
    ]
    return "\n".join(lines) + "\n"


def paste_back(problems: Sequence[str]) -> str:
    """The block of problems for the user to paste back to the assistant."""
    rule = "-" * 72
    return "\n".join(
        [
            rule,
            "Please correct these problems and send your whole answer again:",
            "",
            *(f"- {p}" for p in problems),
            rule,
        ]
    )
