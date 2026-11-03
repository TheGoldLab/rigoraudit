# Copyright (c) 2026, Joshua I. Gold
# SPDX-License-Identifier: BSD-2-Clause

from rigoraudit.clipboard import Clipboard


def test_text_goes_on_the_clipboard_and_comes_back(tmp_path):
    held = tmp_path / "held.txt"  # stands in for the clipboard
    clip = Clipboard(["sh", "-c", f"cat > '{held}'"], ["cat", str(held)])
    assert clip.copy("Accuracy was 80% — in block A.\n")
    assert clip.paste() == "Accuracy was 80% — in block A.\n"


def test_a_clipboard_that_cannot_be_used_says_so(tmp_path):
    clip = Clipboard(["no-such-command"], ["no-such-command"])
    assert not clip.copy("text")
    assert clip.paste() is None
