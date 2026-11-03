# Copyright (c) 2026, Joshua I. Gold
# SPDX-License-Identifier: BSD-2-Clause

import json

from rigoraudit.sections import (
    Heading,
    Place,
    Sections,
    headings_from_text,
    load_outline,
    standard_kind,
)

OUTLINE = (
    Heading("A study of things", 0, 1),
    Heading("Introduction", 1, 1),
    Heading("Results", 1, 2),
    Heading("Subjects learn", 2, 2),
    Heading("Responses change with the cue over many trials", 2, 3),
    Heading("Discussion", 1, 3),
)
PAGES = (
    "A study of things\nIntroduction\nWe preview the task (Figure 2A).\n",
    (
        "Results\nWe report results.\nSubjects learn\nBehavior changed (Figure 2B).\n"
        "Figure 2. Behavior.\nA, the task.\n"
    ),
    (
        "As Figure 2C shows.\nResponses change with the cue\nover many trials\n"
        "Rates fell (Figure 3).\nDiscussion\nThe results (Figure 3) mean much.\n"
    ),
)


def sections() -> Sections:
    return Sections(OUTLINE, PAGES)


def test_major_sections_are_below_a_single_root_title():
    s = sections()
    assert s.majors == ["Introduction", "Results", "Discussion"]
    assert s.subsections[1] == [
        "Subjects learn",
        "Responses change with the cue over many trials",
    ]


def test_anchor_sections_are_placed_by_name():
    s = sections()
    assert s.place("Results") == Place(1, 0)
    assert s.place("Results › Responses change with the cue over many trials") == Place(
        1, 2
    )
    assert s.place("Discussion") == Place(2, 0)


def test_heading_wrapped_across_lines_is_located():
    s = sections()
    # "As Figure 2C shows" sits above the wrapped heading, so it is in subsection 1
    assert s.at(3, 0) == Place(1, 1)
    assert s.at(3, 3) == Place(1, 2)


def test_run_in_heading_is_located():
    # the paragraph's text runs on after the heading, on its last line
    outline = (
        Heading("A study", 0, 1),
        Heading("Results", 1, 1),
        Heading("Rates fell over the made-up trials.", 2, 1),
    )
    page = (
        "Results\nText that names rates fell over\nthe made-up trials.\n"
        "Rates fell over the\nmade-up trials. Then text.\nMore.\n"
    )
    s = Sections(outline, (page,))
    assert [(p, i) for p, i, _ in s.headings] == [(1, 0), (1, 3)]


def test_numbered_heading_is_located():
    # the outline's titles keep their numbers; the printed lines set them apart
    outline = (
        Heading("A study", 0, 1),
        Heading("1 INTRODUCTION", 1, 1),
        Heading("1.1 Made-up things", 2, 1),
    )
    page = "A running head\nText before.\n1 | INTRODUCTION\nText.\n1.1 | Made-up things\nMore.\n"
    s = Sections(outline, (page,))
    assert [(p, i) for p, i, _ in s.headings] == [(1, 2), (1, 4)]


def test_figures_go_where_they_are_cited_most():
    s = sections()
    # Figure 2: once in Introduction, twice in "Subjects learn"; the legend's own
    # title line does not count
    assert len(s.citations(2)) == 3
    assert s.place("Figure 2 legend") == Place(1, 1)
    assert s.place("Figure 2C (text in panel)") == Place(1, 1)
    # Figure 3: once in subsection 2 and once in Discussion; the earliest wins the tie
    assert s.place("Figure 3 legend") == Place(1, 2)


def test_figures_cited_in_results_stay_in_results():
    outline = (*OUTLINE, Heading("Methods", 1, 4))
    pages = (
        *PAGES,
        "Methods\nFigure 3 shows a fit. The fit in Figure 3 used a filter.\n",
        "For Figure 4, we averaged.\n",
    )
    s = Sections(outline, pages)
    # Figure 3: once in Results, once in Discussion, twice in Methods
    assert s.place("Figure 3 legend") == Place(1, 2)
    # Figure 4 is cited only in Methods, so its legend goes there
    assert s.place("Figure 4 legend") == Place(3, 0)


def test_unknown_sections_fall_back_to_their_page():
    s = sections()
    assert s.place("Supplementary note", page=3) == Place(1, 1)
    assert s.title(s.place("Supplementary note")) == "Other"


def test_flat_outline_uses_its_top_level(tmp_path):
    path = tmp_path / "outline.json"
    path.write_text(json.dumps({"headings": [
        {"title": "Abstract", "level": 0, "page": 1},
        {"title": "Methods", "level": 0, "page": 1},
    ]}), encoding="utf-8")  # fmt: skip
    s = Sections(load_outline(path), ("Abstract\nText.\nMethods\nMore.\n",))
    assert s.majors == ["Abstract", "Methods"]
    assert s.at(1, 3) == Place(1, 0)


def test_outline_entries_for_figures_and_misplaced_sections():
    outline = (
        Heading("Introduction", 0, 1),
        Heading("Methods", 0, 1),
        Heading("Task", 1, 1),
        Heading("Results", 1, 1),  # put under Methods by mistake
        Heading("Accuracy", 1, 1),
        Heading("Figure\u2122 1 A made-up figure", 1, 1),
    )
    s = Sections(outline, ("Introduction\nMethods\nTask\nResults\nAccuracy\n",))
    assert s.majors == ["Introduction", "Methods", "Results"]
    assert s.subsections == [[], ["Task"], ["Accuracy"]]


def test_outline_entries_holding_passages_of_text():
    refs = " ".join(
        f"Author{n}A. A made-up title. J. Ex. {n}, 1-9 20{n:02d}" for n in range(9)
    )
    thanks = "We thank the made-up lab for comments on a draft. " * 4
    outline = (
        Heading("Methods", 0, 1),
        Heading("Analysis", 1, 1),
        Heading(refs, 0, 1),
        Heading(thanks, 0, 1),
        Heading("Acknowledgements", 0, 1),
    )
    pages = (
        "Methods\nAnalysis\nWe fit.\nReferences\n1. Author0, A.\nAcknowledgements\n",
    )
    s = Sections(outline, pages)
    assert s.majors == ["Methods", "References", "Acknowledgements"]
    assert s.headings[2][:2] == (1, 3)


# --- Fallback without an outline ------------------------------------------------


def test_standard_kinds_cover_common_variants():
    assert standard_kind("Materials and Methods") == "Methods"
    assert standard_kind("2. Experimental procedures") == "Methods"
    assert standard_kind("STAR★METHODS") == "Methods"
    assert standard_kind("IV. RESULTS AND DISCUSSION") == "Results"
    assert standard_kind("Appendix B") == "Appendices"
    assert standard_kind("Acknowledgments") == "Other"
    assert standard_kind("Subjects learn") is None


TEXT_PAGES = (
    "Abstract\nWe studied things.\n1. Introduction\nThings matter (Figure 1).\n",
    "Results p. 2\n2. Results\nThings happened (Figure 2).\nResults\n",
    "Materials and\nMethods\nWe did things.\nReferences\nSmith, 2020.\n",
)


def test_headings_are_found_in_text_once_each():
    found = headings_from_text(TEXT_PAGES)
    # A repeated "Results" line adds nothing; "Results p. 2" is not a heading line
    assert [(h.title, h.page) for h in found] == [
        ("Abstract", 1), ("Introduction", 1), ("Results", 2),
        ("Materials and Methods", 3), ("References", 3),
    ]  # fmt: skip


def test_sections_fall_back_to_text_headings():
    s = Sections((), TEXT_PAGES)
    assert s.source == "text"
    assert s.majors[3] == "Materials and Methods"
    # Anchors are matched by kind when the names differ
    assert s.place("Methods › Fitting") == Place(3, 0)
    assert s.place("Figure 2 legend") == Place(2, 0)
    assert s.at(3, 4) == Place(4, 0)
