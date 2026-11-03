# Copyright (c) 2026, Joshua I. Gold
# SPDX-License-Identifier: BSD-2-Clause
"""The computer's clipboard, so a task and its reply can be carried to and
from a chat in the browser without saving files.

Uses the commands each system has: ``pbcopy`` and ``pbpaste`` on a Mac,
PowerShell on Windows, and ``wl-copy``, ``xclip``, or ``xsel`` on Linux.
:func:`find` gives ``None`` where there are none, and the guide falls back
to files.
"""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass

COMMANDS: tuple[tuple[Sequence[str], Sequence[str]], ...] = (
    (["pbcopy"], ["pbpaste"]),
    (
        ["powershell", "-NoProfile", "-Command", "$input | Set-Clipboard"],
        ["powershell", "-NoProfile", "-Command", "Get-Clipboard -Raw"],
    ),
    (["wl-copy"], ["wl-paste", "--no-newline"]),
    (["xclip", "-selection", "clipboard"], ["xclip", "-selection", "clipboard", "-o"]),
    (["xsel", "--clipboard", "--input"], ["xsel", "--clipboard", "--output"]),
)


@dataclass(frozen=True)
class Clipboard:
    copy_command: Sequence[str]
    paste_command: Sequence[str]

    def copy(self, text: str) -> bool:
        """Put ``text`` on the clipboard; whether that worked."""
        try:
            done = subprocess.run(
                self.copy_command, input=text, text=True, encoding="utf-8",
                capture_output=True, timeout=10, check=False,
            )  # fmt: skip
        except (OSError, subprocess.TimeoutExpired):
            return False
        return done.returncode == 0

    def paste(self) -> str | None:
        """What is on the clipboard; ``None`` if it cannot be read."""
        try:
            done = subprocess.run(
                self.paste_command, text=True, encoding="utf-8",
                capture_output=True, timeout=10, check=False,
            )  # fmt: skip
        except (OSError, subprocess.TimeoutExpired):
            return None
        return done.stdout if done.returncode == 0 else None


def find() -> Clipboard | None:
    """The clipboard commands this computer has, if any."""
    for copy, paste in COMMANDS:
        if shutil.which(copy[0]) and shutil.which(paste[0]):
            return Clipboard(copy, paste)
    return None
