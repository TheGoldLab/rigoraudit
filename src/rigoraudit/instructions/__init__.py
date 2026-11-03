# Copyright (c) 2026, Joshua I. Gold
# SPDX-License-Identifier: BSD-2-Clause
"""Written instructions for the steps that need judgment (decision 0011).

Each step's instructions are a Markdown file in this package, given to
whichever assistant does the step: a website assistant, a model the tool
calls, or a coding assistant. The file starts with a short header naming
the step and its version::

    ---
    step: segment
    version: 1
    ---

An answer names the version it followed (``"segment v1"``), so the record
can say which instructions produced each item (decision 0010).
"""

from __future__ import annotations

from dataclasses import dataclass
from importlib.resources import files


@dataclass(frozen=True)
class Instructions:
    step: str
    version: int
    text: str
    """The instructions, without the header."""

    @property
    def label(self) -> str:
        """How an answer names these instructions, e.g. ``"segment v1"``."""
        return f"{self.step} v{self.version}"


def load(step: str) -> Instructions:
    """The current instructions for ``step``."""
    raw = (files(__package__) / f"{step}.md").read_text(encoding="utf-8")
    _, header, text = raw.split("---\n", 2)
    fields = dict(line.split(":", 1) for line in header.strip().splitlines())
    fields = {k.strip(): v.strip() for k, v in fields.items()}
    if fields.get("step") != step:
        raise ValueError(f"{step}.md names step {fields.get('step')!r}")
    return Instructions(step=step, version=int(fields["version"]), text=text.lstrip())
