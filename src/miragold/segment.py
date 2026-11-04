# Copyright (c) 2026, Joshua I. Gold
# SPDX-License-Identifier: BSD-2-Clause
"""Check an answer to the segment instructions (decisions 0002, 0011).

The segment step splits the audited paragraphs into claims. An assistant
is given the instructions (``miragold/instructions/segment.md``) and the
paragraphs, each under a short label such as ``R1.2``, and answers with
JSON: the claims, each with an ID and a verbatim quote, and the text it
left out on purpose, each with a reason.

:func:`parse_answer` reads that JSON, and :func:`check_answer` lists
everything wrong with it, in sentences that can be pasted back to the
assistant: quotes that are not word for word in their paragraph or appear
more than once, IDs that do not follow the paragraph's label, overlapping
claims, references to claims that do not exist, and sentences whose
numbers or comparison words nothing covers (:mod:`miragold.coverage`).
An answer with no problems can enter the record.

:func:`write_handoffs` prepares what the assistant is given: files in
``work/segment/handoffs/``, each the instructions followed by a batch of
paragraphs small enough to paste into a chat. Results paragraphs come
first; legends and tables follow once every Results paragraph has an
accepted answer, and list the Results claims they may restate.

:func:`import_answer` matches a reply to its handoff, checks it, and saves
it in ``work/segment/answers/``, one per handoff, with who or what drafted
it (decision 0010). Paragraphs with an accepted answer are not handed off
again. :func:`record_claims` turns every accepted answer into record
claims, anchored to the manuscript by character offsets.
"""

from __future__ import annotations

import datetime
import re
from collections.abc import Collection, Mapping, Sequence
from itertools import pairwise
from pathlib import Path

from pydantic import Field

from miragold import handoffs, instructions
from miragold.coverage import Exclusion, check
from miragold.handoffs import AnswerError, Problem, Problems
from miragold.paragraphs import PARAGRAPHS, Paragraph, in_scope, read_paragraphs
from miragold.schema import (
    Claim,
    ClaimId,
    ClaimType,
    Frozen,
    ManuscriptAnchor,
    NonEmptyStr,
    check_claims,
)
from miragold.settings import DEFAULT_SCOPE
from miragold.words import plural

STEP = "segment"
MAX_CHARS = 12_000
"""Paragraph text per handoff; small enough to paste into most chats."""
NOUNS = {"claims": "claim", "left_out": "left-out item"}


class SegmentClaim(Frozen):
    id: ClaimId
    paragraph: NonEmptyStr
    """The paragraph's label, e.g. ``R1.2``."""
    quote: NonEmptyStr
    type: ClaimType
    citations: tuple[NonEmptyStr, ...] = ()
    """References as printed in the paragraph, e.g. ``"Lee et al., 2019"``."""
    depends_on: tuple[ClaimId, ...] = ()
    restates: ClaimId | None = None


class LeftOut(Frozen):
    paragraph: NonEmptyStr
    quote: NonEmptyStr
    reason: NonEmptyStr
    restates: ClaimId | None = None


class SegmentAnswer(Frozen):
    instructions: NonEmptyStr
    """The instructions the answer followed, e.g. ``"segment v1"``."""
    claims: tuple[SegmentClaim, ...] = ()
    left_out: tuple[LeftOut, ...] = ()


def parse_answer(text: str) -> SegmentAnswer:
    """Read an answer: bare JSON, or the first fenced block in a reply."""
    return handoffs.parse_reply(text, SegmentAnswer, NOUNS)


def _id_letters(claim_id: str, label: str) -> bool:
    return re.fullmatch(rf"{re.escape(label)}\.[a-z]+", claim_id) is not None


CITED = {ClaimType.REFERENCED_RESULT, ClaimType.COMPARISON}


def _type_problems(c: SegmentClaim, referable: Collection[str]) -> Problems:
    """What is missing or wrong for the claim's type (decision 0002)."""
    out = Problems()
    if c.type in CITED and not c.citations:
        out.add(
            "needs-citations",
            f"Claim {c.id} is a {c.type.value}, so it needs citations.",
        )
    if c.type is ClaimType.NO_STATED_SUPPORT and (c.citations or c.depends_on):
        out.add(
            "no-support-with-citations",
            f"Claim {c.id} is no_stated_support, so it cannot have citations or "
            "depends_on; choose another type, or remove them.",
        )
    for other in c.depends_on:
        if other == c.id:
            out.add("depends-on-itself", f"Claim {c.id} cannot depend on itself.")
        elif other not in referable:
            out.add(
                "depends-on-unknown",
                f"Claim {c.id} depends on {other}, which is not a known claim.",
            )
    return out


def check_answer(
    answer: SegmentAnswer,
    paragraphs: Mapping[str, str],
    known_claims: Collection[str] = (),
) -> Problems:
    """Everything wrong with ``answer``, as sentences; empty if nothing is.

    ``paragraphs`` maps each label given to the assistant to the paragraph's
    text. ``known_claims`` are the IDs of claims already in the record, which
    the answer may name in ``restates``.
    """
    problems = handoffs.version_problem(STEP, answer.instructions)

    ids = [c.id for c in answer.claims]
    referable = set(known_claims) | set(ids)
    for claim_id in sorted({i for i in ids if ids.count(i) > 1}):
        problems.add(
            "duplicate-id", f"The ID {claim_id} is used for more than one claim."
        )
    for claim_id in sorted(set(ids) & set(known_claims)):
        problems.add(
            "id-taken", f"The ID {claim_id} is already used by a claim in the record."
        )

    spans: dict[str, list[tuple[int, int, str]]] = {}
    for c in answer.claims:
        if c.restates is not None and c.restates not in referable:
            problems.add(
                "restates-unknown",
                f"Claim {c.id} restates {c.restates}, which is not a known claim.",
            )
        elif c.restates == c.id:
            problems.add("restates-itself", f"Claim {c.id} cannot restate itself.")
        problems += _type_problems(c, referable)
        text = paragraphs.get(c.paragraph)
        if text is None:
            problems.add(
                "unknown-paragraph",
                f"Claim {c.id} names paragraph {c.paragraph}, which was not given.",
            )
            continue
        problems += [
            Problem(
                "citation-not-found",
                f"The citation {ref!r} for claim {c.id} is not in paragraph "
                f"{c.paragraph} word for word.",
            )
            for ref in c.citations
            if ref not in text
        ]
        if not _id_letters(c.id, c.paragraph):
            problems.add(
                "id-pattern",
                f"Claim {c.id} is in paragraph {c.paragraph}, so its ID should be "
                f"{c.paragraph} followed by a letter ({c.paragraph}.a, {c.paragraph}.b, ...).",
            )
        n = text.count(c.quote)
        if n == 0:
            problems.add(
                "quote-not-found",
                f"The quote for claim {c.id} is not in paragraph {c.paragraph} "
                f"word for word: {c.quote!r}",
            )
            continue
        if n > 1:
            problems.add(
                "quote-not-unique",
                f"The quote for claim {c.id} appears {n} times in paragraph "
                f"{c.paragraph}; make it longer so it appears once: {c.quote!r}",
            )
            continue
        start = text.index(c.quote)
        spans.setdefault(c.paragraph, []).append((start, start + len(c.quote), c.id))

    for label, found in spans.items():
        found.sort()
        for (_, end_a, a), (start_b, _, b) in pairwise(found):
            if start_b < end_a:
                problems.add(
                    "claims-overlap",
                    f"Claims {a} and {b} overlap in paragraph {label}.",
                )

    exclusions = []
    for i, e in enumerate(answer.left_out, start=1):
        text = paragraphs.get(e.paragraph)
        if text is None:
            problems.add(
                "unknown-paragraph",
                f"Left-out item {i} names paragraph {e.paragraph}, which was not given.",
            )
        elif e.quote not in text:
            problems.add(
                "quote-not-found",
                f"The quote for left-out item {i} is not in paragraph {e.paragraph} "
                f"word for word: {e.quote!r}",
            )
        else:
            exclusions.append(
                Exclusion(paragraph=e.paragraph, quote=e.quote, reason=e.reason)
            )
        if e.restates is not None and e.restates not in referable:
            problems.add(
                "restates-unknown",
                f"Left-out item {i} restates {e.restates}, which is not a known claim.",
            )

    report = check(
        paragraphs,
        {label: [(a, b) for a, b, _ in found] for label, found in spans.items()},
        (),
        exclusions,
    )
    for gap in report.gaps:
        listed = ", ".join(i.text for i in gap.items)
        problems.add(
            "text-not-covered",
            f"In paragraph {gap.paragraph}, this sentence has text that no claim or "
            f"left-out item covers ({listed}): {gap.sentence!r}",
        )
    return problems


# --- Handoffs ---------------------------------------------------------------


class Handoff(Frozen):
    """One batch of paragraphs for the assistant, with the claims it may name."""

    name: NonEmptyStr
    instructions: NonEmptyStr
    paragraphs: dict[str, str]
    """Label to text, in reading order."""
    places: dict[str, str]
    """Label to where the paragraph is, e.g. ``"Results › Learning ¶2"``."""
    known_claims: dict[str, str] = Field(default_factory=dict)
    """Claims already accepted that ``restates`` may name: ID to quote."""


class Accepted(Frozen):
    """An answer that passed :func:`check_answer`, as saved in ``work/segment/answers/``."""

    handoff: NonEmptyStr
    paragraphs: tuple[str, ...]
    """Labels of the paragraphs the handoff gave."""
    drafted_by: NonEmptyStr
    """Who or what wrote the answer, e.g. a person, or a model and version."""
    imported: NonEmptyStr
    """Date the answer was accepted, ``YYYY-MM-DD``."""
    answer: SegmentAnswer


def read_accepted(workspace: Path) -> list[Accepted]:
    """Every accepted answer in the workspace, by handoff name."""
    return handoffs.read_answers(workspace, STEP, Accepted)


def exclusions(workspace: Path) -> tuple[Exclusion, ...]:
    """The left-out items of every accepted answer, as coverage exclusions."""
    return tuple(
        Exclusion(
            paragraph=e.paragraph, quote=e.quote, reason=e.reason, restates=e.restates
        )
        for a in read_accepted(workspace)
        for e in a.answer.left_out
    )


def plan_handoffs(
    paragraphs: Sequence[Paragraph],
    accepted: Sequence[Accepted] = (),
    scope: Sequence[str] = DEFAULT_SCOPE,
    max_chars: int = MAX_CHARS,
) -> list[Handoff]:
    """The handoffs still needed for the audited sections (``scope``):
    Results first, then the others.

    A paragraph is done once an accepted answer covers it. A paragraph longer
    than ``max_chars`` gets a handoff of its own.
    """
    done = {label for a in accepted for label in a.paragraphs}
    todo = [p for p in paragraphs if in_scope(p.section, scope) and p.label not in done]
    results = [p for p in todo if p.top == "Results"]
    batch, known = results, {}
    if not results:
        batch = todo
        in_results = {p.label for p in paragraphs if p.top == "Results"}
        known = {
            c.id: c.quote
            for a in accepted
            for c in a.answer.claims
            if c.paragraph in in_results
        }
    groups: list[list[Paragraph]] = []
    for p in batch:
        if groups and sum(len(q.text) for q in groups[-1]) + len(p.text) <= max_chars:
            groups[-1].append(p)
        else:
            groups.append([p])
    label = instructions.load(STEP).label
    return [
        Handoff(
            name=f"segment-{g[0].label}",
            instructions=label,
            paragraphs={p.label: p.text for p in g},
            places={p.label: p.place for p in g},
            known_claims=known,
        )
        for g in groups
    ]


def render_handoff(handoff: Handoff) -> str:
    """The text to paste into a chat: the instructions, then the task."""
    body = []
    if handoff.known_claims:
        body += ["", "## Results claims you can name in `restates` or `depends_on`", ""]
        body += [f"- {i}: {q}" for i, q in handoff.known_claims.items()]
    body += ["", "## Paragraphs"]
    for label, text in handoff.paragraphs.items():
        body += ["", f"### Paragraph `{label}` ({handoff.places[label]})", "", text]
    what = f"the {plural(len(handoff.paragraphs), 'paragraph')} below"
    return handoffs.render(STEP, handoff.name, handoff.instructions, what, body)


def write_handoffs(
    workspace: Path,
    scope: Sequence[str] = DEFAULT_SCOPE,
    max_chars: int = MAX_CHARS,
) -> list[Path]:
    """Write the handoffs still needed; return the paths of the files to paste.

    Each handoff is written twice: ``<name>.md`` to paste, and ``<name>.json``
    for the tool to check the answer against. Handoffs left from an earlier
    run without an accepted answer are replaced.
    """
    paragraphs = read_paragraphs(workspace / PARAGRAPHS)
    accepted = read_accepted(workspace)
    planned = plan_handoffs(paragraphs, accepted, scope, max_chars)
    return handoffs.write_handoffs(
        workspace,
        STEP,
        ((h.name, h, render_handoff(h)) for h in planned),
        answered={a.handoff for a in accepted},
    )


# --- Import -----------------------------------------------------------------


def pending_handoffs(workspace: Path) -> list[Handoff]:
    """Handoffs written and not yet answered."""
    answered = {a.handoff for a in read_accepted(workspace)}
    return handoffs.read_pending(workspace, STEP, Handoff, answered)


def _match(answer: SegmentAnswer, pending: Sequence[Handoff]) -> Handoff | Problem:
    """The handoff ``answer`` replies to, or why none could be chosen."""
    named = {c.paragraph for c in answer.claims} | {
        e.paragraph for e in answer.left_out
    }
    fits = (
        [h for h in pending if named <= set(h.paragraphs)] if named else list(pending)
    )
    if len(fits) == 1:
        return fits[0]
    if not pending:
        return Problem(
            "no-handoff-waiting",
            "No handoff is waiting for an answer; run miragold handoff segment.",
        )
    if not fits:
        return Problem(
            "which-handoff",
            f"The answer names paragraphs ({', '.join(sorted(named))}) that are not "
            "all in any one handoff waiting for an answer.",
        )
    return Problem(
        "which-handoff",
        "The answer could belong to more than one handoff "
        f"({', '.join(h.name for h in fits)}); say which with --handoff.",
    )


def import_answer(
    workspace: Path,
    reply: str,
    drafted_by: str,
    handoff: str | None = None,
    today: datetime.date | None = None,
) -> tuple[Path | None, list[Problem]]:
    """Check a reply and, if it has no problems, save it as accepted.

    Returns the saved file, or ``None`` and the problems to give back to the
    assistant.
    """
    try:
        answer = parse_answer(reply)
    except AnswerError as e:
        return None, e.problems
    pending = pending_handoffs(workspace)
    if handoff is not None:
        chosen = next((h for h in pending if h.name == handoff), None)
        if chosen is None:
            return None, [
                Problem(
                    "no-handoff-waiting",
                    f"No handoff named {handoff} is waiting for an answer.",
                )
            ]
    else:
        found = _match(answer, pending)
        if isinstance(found, Problem):
            return None, [found]
        chosen = found
    accepted = read_accepted(workspace)
    taken = {c.id for a in accepted for c in a.answer.claims}
    problems = check_answer(
        answer, chosen.paragraphs, known_claims=taken | set(chosen.known_claims)
    )
    if problems:
        return None, problems
    record = Accepted(
        handoff=chosen.name,
        paragraphs=tuple(chosen.paragraphs),
        drafted_by=drafted_by,
        imported=(today or datetime.date.today()).isoformat(),
        answer=answer,
    )
    return handoffs.save_answer(workspace, STEP, chosen.name, record), []


# --- Record claims ----------------------------------------------------------


def claims_of(workspace: Path, *types: ClaimType) -> list[SegmentClaim]:
    """The accepted claims of the given types, in reading order."""
    paragraphs = read_paragraphs(workspace / PARAGRAPHS)
    order = {p.label: i for i, p in enumerate(paragraphs)}
    found = [
        c for a in read_accepted(workspace) for c in a.answer.claims if c.type in types
    ]
    return sorted(found, key=lambda c: (order[c.paragraph], c.id))


def record_claims(workspace: Path, manuscript: str) -> tuple[Claim, ...]:
    """The claims of every accepted answer, as record claims, in reading order.

    ``manuscript`` is the manuscript file the paragraphs were extracted from,
    relative to ``materials/``. Each claim is anchored by the character span
    of its quote in its paragraph as now extracted
    (:meth:`~miragold.paragraphs.Paragraph.locate`). The claims are checked together, so a
    ``restates`` or ``depends_on`` naming a claim no answer has is an error.
    Every claim's trace is pending; tracing sets it.
    """
    paragraphs = {p.label: p for p in read_paragraphs(workspace / PARAGRAPHS)}
    order = {label: i for i, label in enumerate(paragraphs)}
    found = [c for a in read_accepted(workspace) for c in a.answer.claims]
    found.sort(
        key=lambda c: (order[c.paragraph], paragraphs[c.paragraph].locate(c.quote)[0])
    )
    claims = []
    for c in found:
        p = paragraphs[c.paragraph]
        start, quote = p.locate(c.quote)
        claims.append(
            Claim(
                id=c.id,
                type=c.type,
                anchor=ManuscriptAnchor(
                    file=manuscript,
                    section=p.section,
                    paragraph=p.number,
                    char_start=start,
                    char_end=start + len(quote),
                    page=p.page_at(start),
                    quote=quote,
                ),
                depends_on=c.depends_on,
                citations=c.citations,
                restates=c.restates,
            )
        )
    check_claims(tuple(claims))
    return tuple(claims)
