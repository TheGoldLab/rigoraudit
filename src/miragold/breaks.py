# Copyright (c) 2026, Joshua I. Gold
# SPDX-License-Identifier: BSD-2-Clause
"""Check the doubtful paragraph breaks of a paper read from its PDF.

Without the publisher's XML, :mod:`miragold.extract` cuts paragraphs by
the page layout, and a few breaks are wrong: two paragraphs run together,
or one split in two. This optional step hands an assistant only the places
where a break is in doubt (*spots*), each with the text around it, and
asks one question of each: does a new paragraph start here? The answer
holds no text, so no word of the paper can change; the tool makes the
splits and joins.

A spot is either

- a break the tool made where the paragraph before does not end a sentence
  or the next one does not start one, or
- a place inside a paragraph the extract step marked as doubtful (a
  paragraph's ``doubts``): a sentence after a short line, or after a figure
  or page break.

Breaks in the front matter (title, authors, affiliations) are not asked
about, nor the one after a legend's title, which the tool always splits off.

:func:`write_handoffs` writes one handoff, ``work/breaks/handoffs/breaks``,
and :func:`import_answer` checks a reply and applies it to
``work/extract/paragraphs.json``. Claim IDs are built from paragraph
numbers, so the step runs before segment, and not once segment has an
accepted answer.
"""

from __future__ import annotations

import datetime
import hashlib
import json
from collections import Counter
from pathlib import Path

from miragold import handoffs, instructions, segment
from miragold.extract import ENDS_SENTENCE, FRONT, STARTS_SENTENCE
from miragold.handoffs import AnswerError, Problem, Problems
from miragold.paragraphs import PARAGRAPHS, join_page_starts, split_page_starts
from miragold.schema import Frozen, NonEmptyStr
from miragold.words import plural

STEP = "breaks"
NAME = "breaks"
CONTEXT = 200
"""Characters shown on each side of a spot."""
NOUNS = {"decisions": "decision"}
LEGENDS = (" legend", " caption")
"""How the sections of figure legends and table captions end."""
ROUGH = 0.4
"""More spots than this per paragraph: the PDF's layout came out rough (in
the test set, the papers whose paragraphs were worst)."""


class Spot(Frozen):
    id: NonEmptyStr
    """``B1``, ``B2``, ... in reading order."""
    index: int
    """The paragraph in the paragraphs file: for a break the tool made, the
    one after it."""
    offset: int
    """Where in that paragraph the spot is; 0 for a break the tool made."""
    place: NonEmptyStr
    before: str
    after: str

    @property
    def broken(self) -> bool:
        """Whether the paragraphs file has a break here now."""
        return self.offset == 0


class Handoff(Frozen):
    name: NonEmptyStr
    instructions: NonEmptyStr
    paragraphs: NonEmptyStr
    """SHA-256 of the paragraphs file the spots were found in."""
    spots: tuple[Spot, ...]


class Decision(Frozen):
    spot: NonEmptyStr
    new_paragraph: bool


class BreaksAnswer(Frozen):
    instructions: NonEmptyStr
    """The instructions the answer followed, e.g. ``"breaks v2"``."""
    decisions: tuple[Decision, ...]


class Accepted(Frozen):
    handoff: NonEmptyStr
    drafted_by: NonEmptyStr
    imported: NonEmptyStr
    """Date the answer was accepted, ``YYYY-MM-DD``."""
    split: int
    """Paragraphs split in two."""
    joined: int
    """Pairs of paragraphs joined."""
    answer: BreaksAnswer


def parse_answer(text: str) -> BreaksAnswer:
    """Read an answer: bare JSON, or the first fenced block in a reply."""
    return handoffs.parse_reply(text, BreaksAnswer, NOUNS)


def _place(entry: dict) -> str:
    return f"{entry['section']} ¶{entry['paragraph']}"


def find_spots(entries: list[dict]) -> list[Spot]:
    """The places in the paragraphs file where a break is in doubt."""
    spots: list[Spot] = []

    def add(index: int, offset: int, before: str, after: str) -> None:
        spots.append(
            Spot(
                id=f"B{len(spots) + 1}",
                index=index,
                offset=offset,
                place=_place(entries[index]),
                before=before[-CONTEXT:],
                after=after[:CONTEXT],
            )
        )

    for i, entry in enumerate(entries):
        if not entry.get("approximate") or entry["section"] == FRONT:
            continue
        before = entries[i - 1] if i else None
        title = entry["section"].endswith(LEGENDS) and entry["paragraph"] == 2
        if (
            before is not None
            and not title
            and before.get("approximate")
            and before["section"] == entry["section"]
            and not (
                ENDS_SENTENCE.search(before["text"].rstrip())
                and STARTS_SENTENCE.match(entry["text"])
            )
        ):
            add(i, 0, before["text"], entry["text"])
        text = entry["text"]
        for offset in entry.get("doubts", []):
            add(i, offset, text[:offset].rstrip(), text[offset:])
    return spots


def rough_note(workspace: Path) -> str:
    """A warning if the paragraphs have many spots in doubt, else ``""``."""
    entries = json.loads((workspace / PARAGRAPHS).read_text(encoding="utf-8"))
    n = sum(bool(e.get("approximate")) and e["section"] != FRONT for e in entries)
    spots = len(find_spots(entries))
    if not n or spots <= ROUGH * n:
        return ""
    return (
        f"This PDF did not come out cleanly: the tool is unsure about "
        f"{plural(spots, 'paragraph break')} in {n} paragraphs, more than "
        "usual, and in papers like this some text can also come out of order. "
        "Finding the article's XML file is worth the effort here."
    )


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_accepted(workspace: Path) -> list[Accepted]:
    return handoffs.read_answers(workspace, STEP, Accepted)


def plan_handoffs(workspace: Path) -> list[Handoff]:
    """The handoff still needed: none once answered, or once segment has begun."""
    path = workspace / PARAGRAPHS
    if read_accepted(workspace) or segment.read_accepted(workspace):
        return []
    spots = find_spots(json.loads(path.read_text(encoding="utf-8")))
    if not spots:
        return []
    return [
        Handoff(
            name=NAME,
            instructions=instructions.load(STEP).label,
            paragraphs=_digest(path),
            spots=tuple(spots),
        )
    ]


def render_handoff(handoff: Handoff) -> str:
    """The text to paste: the instructions, then each spot with its text."""
    body = ["", "## Places"]
    for s in handoff.spots:
        body += ["", f"### {s.id} ({s.place})", "", f"> …{s.before} ‖ {s.after}…"]
    what = f"the {plural(len(handoff.spots), 'place')} below"
    return handoffs.render(STEP, handoff.name, handoff.instructions, what, body)


def write_handoffs(workspace: Path) -> list[Path]:
    """Write the handoff if one is needed; return the file to paste."""
    planned = plan_handoffs(workspace)
    return handoffs.write_handoffs(
        workspace,
        STEP,
        ((h.name, h, render_handoff(h)) for h in planned),
        answered={a.handoff for a in read_accepted(workspace)},
    )


def pending_handoffs(workspace: Path) -> list[Handoff]:
    answered = {a.handoff for a in read_accepted(workspace)}
    return handoffs.read_pending(workspace, STEP, Handoff, answered)


def check_answer(answer: BreaksAnswer, handoff: Handoff) -> Problems:
    """Everything wrong with an answer: every place decided exactly once."""
    problems = handoffs.version_problem(STEP, answer.instructions)
    given = Counter(d.spot for d in answer.decisions)
    ids = [s.id for s in handoff.spots]
    for spot in sorted(set(given) - set(ids)):
        problems.add("unknown-spot", f"There is no place {spot} in this task.")
    for spot in ids:
        if not given[spot]:
            problems.add("missing-spot", f"Place {spot} has no decision.")
        elif given[spot] > 1:
            problems.add("repeated-spot", f"Place {spot} has more than one decision.")
    return problems


def apply(entries: list[dict], spots: tuple[Spot, ...], new: dict[str, bool]):
    """The paragraphs with the decided breaks made; also how many were split
    and joined. Paragraphs are numbered again within each section, and the
    doubts, now decided, are dropped."""
    cuts: dict[int, list[int]] = {}
    joins: set[int] = set()
    for s in spots:
        if s.broken and not new[s.id]:
            joins.add(s.index)
        elif not s.broken and new[s.id]:
            cuts.setdefault(s.index, []).append(s.offset)
    out: list[dict] = []
    for i, entry in enumerate(entries):
        entry = {k: v for k, v in entry.items() if k != "doubts"}
        text, pieces, start = entry["text"], [], 0
        page_starts = entry.pop("page_starts", [])
        for offset in sorted(cuts.get(i, [])):
            head, page_starts = split_page_starts(page_starts, offset - start)
            pieces.append((text[start:offset].rstrip(), head))
            start = offset
        pieces.append((text[start:], page_starts))
        for n, (piece, starts) in enumerate(pieces):
            if n == 0 and i in joins:
                last = out[-1]
                at = len(last["text"].rstrip()) + 1
                last["text"] = f"{last['text'][: at - 1]} {piece}"
                last["pages"] = sorted(
                    {*last.get("pages", []), *entry.get("pages", [])}
                )
                first = (last.get("pages") or [None])[0]
                then = (entry.get("pages") or [None])[0]
                if first is not None and then is not None:
                    joined = join_page_starts(
                        last.get("page_starts") or [[0, first]],
                        starts or [[0, then]],
                        at,
                    )
                    if len(joined) > 1:
                        last["page_starts"] = joined
            else:
                out.append(
                    {
                        **entry,
                        "text": piece,
                        **({"page_starts": starts} if len(starts) > 1 else {}),
                    }
                )
    count: Counter[str] = Counter()
    for entry in out:
        count[entry["section"]] += 1
        entry["paragraph"] = count[entry["section"]]
    return out, sum(len(c) for c in cuts.values()), len(joins)


def import_answer(
    workspace: Path,
    reply: str,
    drafted_by: str,
    handoff: str | None = None,
    today: datetime.date | None = None,
) -> tuple[Path | None, list[Problem]]:
    """Check a reply and, if it has no problems, apply it and save it.

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
                "No handoff is waiting for an answer; run miragold handoff breaks.",
            )
        ]
    chosen = pending[0]
    path = workspace / PARAGRAPHS
    if segment.read_accepted(workspace):
        return None, [
            Problem(
                "segment-begun",
                "Segment already has accepted answers, whose claim IDs follow the "
                "paragraph numbers, so the paragraphs can no longer change here.",
            )
        ]
    if _digest(path) != chosen.paragraphs:
        return None, [
            Problem(
                "paragraphs-changed",
                f"{PARAGRAPHS} has changed since the handoff was written; run "
                "miragold handoff breaks again and give the assistant the new file.",
            )
        ]
    problems = check_answer(answer, chosen)
    if problems:
        return None, problems
    entries = json.loads(path.read_text(encoding="utf-8"))
    new = {d.spot: d.new_paragraph for d in answer.decisions}
    entries, split, joined = apply(entries, chosen.spots, new)
    path.write_text(
        json.dumps(entries, indent=1, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    record = Accepted(
        handoff=chosen.name,
        drafted_by=drafted_by,
        imported=(today or datetime.date.today()).isoformat(),
        split=split,
        joined=joined,
        answer=answer,
    )
    return handoffs.save_answer(workspace, STEP, chosen.name, record), []
