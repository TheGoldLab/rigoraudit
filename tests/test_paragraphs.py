# Copyright (c) 2026, Joshua I. Gold
# SPDX-License-Identifier: BSD-2-Clause

import json

import pytest

from rigoraudit.paragraphs import (
    in_scope,
    join_page_starts,
    read_paragraphs,
    split_page_starts,
)


def write(tmp_path, entries):
    path = tmp_path / "paragraphs.json"
    path.write_text(json.dumps(entries))
    return path


def test_labels_are_made_from_sections_when_not_given(tmp_path):
    path = write(tmp_path, [
        {"section": "Methods › Task", "paragraph": 1, "text": "m"},
        {"section": "Results › First", "paragraph": 1, "text": "a"},
        {"section": "Results › First", "paragraph": 2, "text": "b"},
        {"section": "Results › Second", "paragraph": 1, "text": "c"},
        {"section": "Figure 1 legend", "paragraph": 1, "text": "d", "key": "F1.1"},
    ])  # fmt: skip
    paras = read_paragraphs(path)
    assert [p.label for p in paras] == ["M1.1", "R1.1", "R1.2", "R2.1", "F1.1"]
    assert paras[2].top == "Results"
    assert paras[2].place == "Results › First ¶2"


def test_duplicate_labels_are_an_error(tmp_path):
    path = write(tmp_path, [
        {"section": "Results", "paragraph": 1, "text": "a", "key": "R1.1"},
        {"section": "Results", "paragraph": 2, "text": "b", "key": "R1.1"},
    ])  # fmt: skip
    with pytest.raises(ValueError, match="used twice"):
        read_paragraphs(path)


def test_transcribed_paragraphs_are_marked(tmp_path):
    path = write(tmp_path, [
        {"section": "Figure 1 legend", "paragraph": 1, "text": "a"},
        {"section": "Figure 1B (panel)", "paragraph": 1, "text": "p = 0.01",
         "transcribed": True},
    ])  # fmt: skip
    assert [p.transcribed for p in read_paragraphs(path)] == [False, True]


def test_the_audited_sections_are_patterns_matched_at_the_start():
    scope = ("Results", r"Figure \d+ legend$")
    assert in_scope("Results › Learning", scope)
    assert in_scope("Figure 2 legend", scope)
    assert not in_scope("Figure 2—figure supplement 1 legend", scope)
    assert not in_scope("Methods › Results of pilot", scope)


def test_a_quote_takes_the_page_it_starts_on(tmp_path):
    path = write(tmp_path, [{"section": "Results", "paragraph": 1, "text": "a b c",
                             "pages": [4, 5], "page_starts": [[0, 4], [2, 5]]}])  # fmt: skip
    [p] = read_paragraphs(path)
    assert [p.page_at(i) for i in range(5)] == [4, 4, 5, 5, 5]


def test_page_starts_follow_a_split_and_a_join():
    head, tail = split_page_starts([[0, 4], [10, 5]], 6)
    assert (head, tail) == ([[0, 4]], [[0, 4], [4, 5]])
    assert join_page_starts([[0, 4]], [[0, 4], [4, 5]], 7) == [[0, 4], [11, 5]]
