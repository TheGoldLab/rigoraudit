# Copyright (c) 2026, Joshua I. Gold
# SPDX-License-Identifier: BSD-2-Clause
"""Display equations' numbers as printed, and keys for those without one.

An equation printed with a number is known by that number everywhere: in
``equations.json``, in the paragraphs' marks, and in the auditor's typed-in
versions. An equation printed without one gets a key from where it is: its
page and how far down it its top is, in points (``"p22@233"``). A key from
its place in the list would change whenever an equation above it was found
or lost; this one changes only if the equation itself does, and a typed key
still matches if the equation's top moves a little (:func:`match_typed`).
Without a page and place (an equation in the publisher's XML not found in
the PDF), the key is from the number before it: ``"A9+1"`` and ``"A9+2"``
for the first and second after A9, ``"0+1"`` before the first number.
``+`` and ``@`` are never part of a printed number, so a key cannot clash
with one.

A number read from a PDF's text can be wrong (``"(2)"`` at the end of a
formula, say). Numbers that do not go up in order with the rest are not
taken as numbers; the equation is listed without one, with a note saying
what was read. A gap in the numbers (A13, then A15) is noted, never filled:
a guessed number could be wrong and look right.

The auditor has the last word, in ``derivations/equation_numbers.yaml``: the
number printed, or ``null`` for none, by the equation's page and how far down
it its top is (its key, had it no number: the equations page shows it for
each), matched like a typed key, within :data:`NEAR` points::

    p26@412: A14
    p22@233: null
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path, PurePosixPath

import yaml

NUMBER = r"(?:[A-Z]\.?)?\d{1,3}(?:\.\d{1,3})?[a-z]?"
"""A printed equation number, without brackets: ``"3"``, ``"3a"``, ``"A12"``,
``"A.12"``, ``"2.1"``, ``"S3"``."""
_PARTS = re.compile(r"([A-Z]?)\.?(\d+)(?:\.(\d+))?([a-z]?)")
CORRECTIONS = PurePosixPath("derivations/equation_numbers.yaml")
PLACE = re.compile(r"p(\d+)@(\d+)")
"""A key from an equation's page and place on it: ``"p22@233"``."""
Corrections = Mapping[str, str | None]
"""The auditor's numbers (:func:`read_corrections`), by place: ``"p22@233"``."""
NEAR = 10
"""How far (points) an equation's top can move and still match a typed key."""


@dataclass(frozen=True)
class Item:
    """An equation as listed: its page and the number read for it."""

    page: int | None
    read: str | None
    """The number read from the PDF's text or the publisher's XML."""
    trusted: bool = False
    """Read from the publisher's XML, so not checked for order."""
    down: float | None = None
    """How far its top is below the top of its page, in points."""


@dataclass(frozen=True)
class Numbered:
    """An equation's number (as printed, if it has one) and key."""

    number: str | None
    key: str
    note: str = ""


def _parts(number: str) -> tuple[str, int, int, str]:
    m = _PARTS.fullmatch(number)
    if m is None:
        raise ValueError(f"not an equation number: {number!r}")
    family, major, minor, letter = m.groups()
    return family, int(major), int(minor) if minor else -1, letter


def _in_order(numbers: Sequence[str | None], fixed: set[int]) -> set[int]:
    """Indices of the numbers kept: every one in ``fixed``, and of the
    others, the longest run that goes up in the order listed, a family of
    numbers (``A1``, ``A2``, …) after the families before it. A family the
    run has one number of is kept only if that is its first (``1``, ``A1``,
    ``2.1``), or a plain number that is the equation's place in the list
    (``3`` on the third): one alone is more likely part of a formula, but
    not one that fits where it is. Fixed numbers are
    the auditor's or the publisher's, so they are not checked; they do not
    count against the others, but a family with one backs up its others."""
    at = [i for i, n in enumerate(numbers) if n is not None and i not in fixed]
    parts = {i: _parts(numbers[i]) for i in at}  # type: ignore[arg-type]
    order: dict[str, int] = {}
    for i in at:
        order.setdefault(parts[i][0], len(order))
    rank = {i: (order[parts[i][0]], *parts[i][1:]) for i in at}
    best: dict[int, tuple[int, int | None]] = {}  # run length, previous
    for i in at:
        prev = max(
            (j for j in best if rank[j] < rank[i]),
            key=lambda j: best[j][0],
            default=None,
        )
        best[i] = (1 + (best[prev][0] if prev is not None else 0), prev)
    end = max(best, key=lambda j: best[j][0], default=None)
    run = []
    while end is not None:
        run.append(end)
        end = best[end][1]
    families: dict[str, list[int]] = {}
    for i in run:
        families.setdefault(parts[i][0], []).append(i)
    backed = {_parts(numbers[i])[0] for i in fixed if numbers[i] is not None}  # type: ignore[arg-type]
    kept = set(fixed)
    for family, members in families.items():
        _, major, minor, _ = parts[members[0]]
        if (
            len(members) > 1
            or family in backed
            or (minor if minor >= 0 else major) == 1
            or (not family and minor < 0 and major == members[0] + 1)
        ):
            kept.update(members)
    return kept


def _corrected(items: Sequence[Item], corrections: Corrections) -> dict[int, str]:
    """The correction for each item that has one, by index, matched by where
    it is (:func:`match_typed`)."""
    places = {
        f"p{it.page}@{round(it.down)}": i
        for i, it in enumerate(items)
        if it.page is not None and it.down is not None
    }
    return {places[k]: c for c, k in match_typed(list(places), corrections).items()}


def settle(
    items: Sequence[Item], corrections: Mapping[str, str | None] = {}
) -> list[Numbered]:
    """Each equation's number and key (see the module's description), with
    the auditor's ``corrections`` (:func:`read_corrections`)."""
    corrected = _corrected(items, corrections)
    numbers: list[str | None] = []
    notes: list[str] = []
    fixed: set[int] = set()
    for i, it in enumerate(items):
        if i in corrected:
            number = corrections[corrected[i]]
            fixed.add(i)
            read = f"“({it.read})”" if it.read else "no number"
            notes.append(f"Number from {CORRECTIONS}; read {read}.")
        else:
            number = it.read
            if it.trusted and number is not None:
                fixed.add(i)
            notes.append("")
        numbers.append(number)
    kept = _in_order(numbers, fixed)
    used: dict[str, int] = {}
    out: list[Numbered] = []
    last = "0"
    count = 0
    for i, (number, note) in enumerate(zip(numbers, notes, strict=True)):
        if number is not None and i not in kept:
            note = (
                f"Read “({number})” here, but it is out of order with the "
                "numbers around it, so it is not taken as this equation's number."
            )
            number = None
        if number is None:
            count += 1
            it = items[i]
            key = (
                f"p{it.page}@{round(it.down)}"
                if it.page is not None and it.down is not None
                else f"{last}+{count}"
            )
            used[key] = used.get(key, 0) + 1
            if used[key] > 1:
                key = f"{key}~{used[key]}"
        else:
            used[number] = used.get(number, 0) + 1
            key = number if used[number] == 1 else f"{number}~{used[number]}"
            if used[number] > 1:
                note = (note + " " if note else "") + (
                    f"Number {number} is printed more than once; this is "
                    f"number {used[number]}."
                )
            last, count = key, 0
        out.append(Numbered(number, key, note))
    return out


def match_typed(keys: Sequence[str], typed: Iterable[str]) -> dict[str, str]:
    """The typed keys that match the listed ``keys``, each mapped to the
    listed key it matches: the same key, or for a key from a place
    (``"p22@233"``), the listed one nearest it on the same page, within
    :data:`NEAR` points, that no typed key has exactly."""
    listed = set(keys)
    out = {t: t for t in typed if t in listed}
    taken = set(out.values())
    for t in typed:
        if t in out or not (m := PLACE.fullmatch(t)):
            continue
        page, down = m.groups()
        near = [
            (abs(int(n.group(2)) - int(down)), k)
            for k in keys
            if k not in taken
            and (n := PLACE.fullmatch(k))
            and n.group(1) == page
            and abs(int(n.group(2)) - int(down)) <= NEAR
        ]
        if near:
            out[t] = min(near)[1]
            taken.add(out[t])
    return out


def gaps(numbers: Sequence[str | None]) -> list[str]:
    """Notes on numbers missing from the sequence: ``"A14 not found
    (between A13 and A15)"``. Only whole numbers (A13, A15) and their
    decimal parts (2.1, 2.3) are counted; lettered ones (3a) are not."""
    out = []
    shown = [n for n in numbers if n is not None]
    for a, b in pairwise(shown):
        fa, ma, na, la = _parts(a)
        fb, mb, nb, lb = _parts(b)
        if fa != fb or la or lb:
            continue
        if na < 0 and nb < 0 and mb - ma > 1:
            prefix = a[: len(a) - len(str(ma))]
            missing = [f"{prefix}{k}" for k in range(ma + 1, mb)]
        elif na >= 0 and nb >= 0 and ma == mb and nb - na > 1:
            prefix = a[: len(a) - len(str(na))]
            missing = [f"{prefix}{k}" for k in range(na + 1, nb)]
        else:
            continue
        names = ", ".join(missing[:5]) + (", …" if len(missing) > 5 else "")
        out.append(f"{names} not found (between {a} and {b})")
    return out


def unused(items: Sequence[Item], corrections: Corrections) -> list[str]:
    """Corrections that name no listed equation, e.g. ``"p22@233"``."""
    used = set(_corrected(items, corrections).values())
    return [c for c in corrections if c not in used]


def read_corrections(path: Path) -> dict[str, str | None]:
    """The auditor's numbers (see the module's description), by place
    (:data:`Corrections`); none if there is no file.

    Raises ``ValueError`` naming an entry that is not a place and a number
    (in quotes if YAML would read it as a decimal: ``"2.10"``) or ``null``.
    """
    if not path.is_file():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    out: dict[str, str | None] = {}
    bad = f"{path}: give each equation as p<page>@<points down>: number (or null)"

    def number(where: str, value: object) -> str | None:
        if isinstance(value, float):
            raise ValueError(  # noqa: TRY004
                f"{path}: {where}: put quotes around {value!r}, or YAML reads "
                "it as a decimal"
            )
        if isinstance(value, int) and not isinstance(value, bool):
            value = str(value)
        if value is None or isinstance(value, str) and re.fullmatch(NUMBER, value):
            return value
        raise ValueError(f"{bad}; {where}")

    # mistakes in the file, not in the code, so ValueError throughout
    if not isinstance(data, dict):
        raise ValueError(bad)  # noqa: TRY004
    for key, value in data.items():
        if not (isinstance(key, str) and PLACE.fullmatch(key)):
            raise ValueError(f"{bad}; {key!r}")
        out[key] = number(key, value)
    return out
