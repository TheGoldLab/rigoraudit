# Copyright (c) 2026, Joshua I. Gold
# SPDX-License-Identifier: BSD-2-Clause
"""Wording shared by the messages the tool writes."""


def plural(n: int, noun: str) -> str:
    """``"1 claim"``, ``"2 claims"``."""
    return f"{n} {noun}{'s' if n != 1 else ''}"
