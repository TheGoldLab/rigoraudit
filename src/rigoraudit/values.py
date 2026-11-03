# Copyright (c) 2026, Joshua I. Gold
# SPDX-License-Identifier: BSD-2-Clause
"""Machine-readable outputs of audit derivations (decision 0007).

A derivation writes its values once, as JSON, with the script that produced
them and a checksum of every input it read::

    {"script": "derivations/behavior.py",
     "script_sha256": "<sha256>",
     "inputs": {"derivations/output/trials_B.csv": "<sha256>"},
     "values": {"durations/B/mean": 312.47, ...}}

Lists become numbered keys (``"onsets": [3, 5]`` gives ``onsets/0`` and
``onsets/1``), so the record still cites one value at a time. True and false
are kept as they are, for exact comparisons only.

Observations in the record cite a value by its key. ``rigoraudit.verify``
reads it back, and reports the output as stale if the script or an input
has changed since.
"""

from __future__ import annotations

import hashlib
import json
import math
import numbers
import os
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

Scalar = bool | int | float | str


def sha256(path: Path) -> str:
    """Hex SHA-256 of a file, read in chunks."""
    digest = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(1 << 20):
            digest.update(chunk)
    return digest.hexdigest()


def _scalar(key: str, value: Any) -> Scalar:
    """Convert numpy and other numeric scalars to JSON-safe Python values."""
    if value is None:
        raise TypeError(f"{key}: value is None; record why it is missing instead")
    if isinstance(value, bool | str):
        return value
    if isinstance(value, numbers.Integral):
        return int(value)
    if isinstance(value, numbers.Real):
        x = float(value)
        if not math.isfinite(x):
            raise ValueError(f"{key}: value is {x}; record why it is missing instead")
        return x
    raise TypeError(
        f"{key}: values are numbers, strings, or true/false, got {type(value).__name__}"
    )


def _put(flat: dict[str, Scalar], key: str, value: Any) -> None:
    """Add ``value`` under ``key``, expanding mappings and lists."""
    if hasattr(value, "tolist"):  # numpy scalars and arrays
        value = value.tolist()
    if isinstance(value, Mapping):
        flat.update(flatten(value, f"{key}/"))
    elif isinstance(value, list | tuple):
        if not value:
            raise ValueError(f"{key}: empty list; record why it is missing instead")
        for i, item in enumerate(value):
            _put(flat, f"{key}/{i}", item)
    else:
        flat[key] = _scalar(key, value)


def flatten(values: Mapping[str, Any], prefix: str = "") -> dict[str, Scalar]:
    """Flatten nested mappings and lists into ``/``-separated keys.

    List items are numbered from 0, e.g. ``{"a": [3, 5]}`` gives ``a/0`` and
    ``a/1``.
    """
    flat: dict[str, Scalar] = {}
    for name, value in values.items():
        if "/" in name or not name:
            raise ValueError(
                f"key parts must be non-empty and contain no '/': {name!r}"
            )
        _put(flat, f"{prefix}{name}", value)
    return flat


def write_values(
    path: Path,
    values: Mapping[str, Any],
    *,
    script: Path,
    inputs: Sequence[Path],
    workspace: Path,
) -> None:
    """Write a derivation's values, with its script and input checksums.

    Paths are recorded relative to ``workspace``, as they are reached from
    it: a file in a linked folder (``materials/data`` linked to another
    disk) keeps its path in the workspace. Values may be nested mappings and
    lists; they are stored under flattened ``/``-separated keys.
    """

    def rel(p: Path) -> str:
        for a, b in ((p, workspace), (p.resolve(), workspace.resolve())):
            try:
                return (
                    Path(os.path.abspath(a)).relative_to(os.path.abspath(b)).as_posix()
                )
            except ValueError:
                pass
        raise ValueError(
            f"{p} is not in the workspace {workspace}. Read only files in the "
            "workspace (put or link the file in materials/), and give their "
            "paths from the workspace."
        )

    doc = {
        "script": rel(script),
        "script_sha256": sha256(script),
        "inputs": {rel(p): sha256(p) for p in inputs},
        "values": flatten(values),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(doc, indent=1, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def read_values(path: Path) -> dict[str, Any]:
    """Read a derivation output written by :func:`write_values`."""
    doc = json.loads(path.read_text(encoding="utf-8"))
    if not {"script", "script_sha256", "inputs", "values"} <= doc.keys():
        raise ValueError(
            f"{path} is not a derivation output (script, script_sha256, inputs, values)"
        )
    return doc
