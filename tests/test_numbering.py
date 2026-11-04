# Copyright (c) 2026, Joshua I. Gold
# SPDX-License-Identifier: BSD-2-Clause
import json

import pytest

from miragold import equations, numbering
from miragold.extract import EQUATION_NUMBER, EQUATIONS_FILE
from miragold.numbering import Item, gaps, read_corrections, settle, unused
from miragold.paragraphs import EQUATION_MARK


def read(*numbers, page=1, trusted=False):
    return [Item(page, n, trusted) for n in numbers]


def keys(items):
    return [n.key for n in settle(items)]


def test_unnumbered_keys_are_where_they_are():
    items = [Item(2, "1", down=100), Item(2, None, down=300.4), Item(3, None, down=80)]
    assert keys(items) == ["1", "p2@300", "p3@80"]
    # without a place, from the number before
    assert keys([Item(2, "1"), Item(None, None)]) == ["1", "1+1"]
    # two at the same height, side by side
    assert keys([Item(2, None, down=90), Item(2, None, down=90)]) == [
        "p2@90", "p2@90~2",
    ]  # fmt: skip


def test_typed_keys_match_a_little_away():
    listed = ["1", "p2@300", "p2@330", "p4@80"]
    typed = ["1", "p2@306", "p2@330", "p4@95", "p3@300"]
    # an exact match is kept; a near one goes to the nearest left over;
    # too far, or on another page, matches nothing
    assert numbering.match_typed(listed, typed) == {
        "1": "1", "p2@330": "p2@330", "p2@306": "p2@300",
    }  # fmt: skip


def test_unnumbered_keys_count_from_the_number_before():
    assert keys(read(None, "1", None, None, "2", None)) == [
        "0+1", "1", "1+1", "1+2", "2", "2+1",
    ]  # fmt: skip


def test_numbers_out_of_order_are_not_taken():
    out = settle(read("A1", "A2", "K4", "A3", "2", "A4", "2"))
    assert [n.number for n in out] == ["A1", "A2", None, "A3", None, "A4", None]
    assert [n.key for n in out] == ["A1", "A2", "A2+1", "A3", "A3+1", "A4", "A4+1"]
    assert out[2].note.startswith("Read “(K4)” here, but it is out of order")
    assert out[0].note == ""


def test_a_lone_number_is_taken_only_if_it_starts_its_family():
    assert [n.number for n in settle(read("1", "2", "A1"))] == ["1", "2", "A1"]
    assert [n.number for n in settle(read("1", "2", "A7"))] == ["1", "2", None]


def test_a_lone_number_is_taken_where_it_fits():
    # the first two printed numbers were not read; the third is in its place
    assert [n.number for n in settle(read(None, None, "3"))] == [None, None, "3"]
    assert [n.number for n in settle(read(None, "3"))] == [None, None]


def test_section_numbers_and_letters_keep_their_order():
    out = settle(read("2.1", "2.2", "0.5", "2.3", "3a", "3b", "4"))
    assert [n.number for n in out] == ["2.1", "2.2", None, "2.3", "3a", "3b", "4"]


def test_corrections_override_what_was_read():
    items = [Item(3, "4", down=100), Item(3, None, down=200), Item(3, "6", down=300)]
    out = settle(items, {"p3@200": "5", "p3@300": None})
    assert [n.number for n in out] == ["4", "5", None]
    assert [n.key for n in out] == ["4", "5", "p3@300"]
    assert out[1].note.startswith(f"Number from {numbering.CORRECTIONS}; read no")
    assert "read “(6)”" in out[2].note
    # a corrected number is kept even when out of order, and does not
    # count against the numbers read around it
    items = [Item(1, n, down=100 * k) for k, n in enumerate(("1", "2", "3"))]
    assert [n.number for n in settle(items, {"p1@0": "9"})] == ["9", "2", "3"]


def test_numbers_from_the_publishers_xml_are_not_checked():
    out = settle(read("3", "1", "3", trusted=True))
    assert [n.number for n in out] == ["3", "1", "3"]
    assert [n.key for n in out] == ["3", "1", "3~2"]
    assert "printed more than once" in out[2].note


def test_gaps_are_noted_not_filled():
    assert gaps(["A13", None, "A15"]) == ["A14 not found (between A13 and A15)"]
    assert gaps(["2.1", "2.3", "3.1"]) == ["2.2 not found (between 2.1 and 2.3)"]
    assert gaps(["1", "9"]) == ["2, 3, 4, 5, 6, … not found (between 1 and 9)"]
    assert gaps(["3a", "3c", "A1", "B4", "1", "2"]) == []


def test_corrections_by_where_they_are():
    items = [Item(4, "1", down=100), Item(4, "(x)", down=300), Item(4, "3", down=500)]
    # the nearest within ten points; one found or lost above does not shift it
    fixes = {"p4@306": "2", "p4@560": None}
    assert [n.number for n in settle(items, fixes)] == ["1", "2", "3"]
    assert [n.number for n in settle(items[1:], fixes)] == ["2", "3"]
    assert unused(items, fixes) == ["p4@560"]


def test_read_corrections(tmp_path):
    path = tmp_path / "numbers.yaml"
    assert read_corrections(path) == {}
    path.write_text("p26@412: A14\np26@530: null\np21@233: 4\n", encoding="utf-8")
    assert read_corrections(path) == {"p26@412": "A14", "p26@530": None, "p21@233": "4"}
    for text, message in [
        ("p26@40: 2.10\n", "p26@40: put quotes"),
        ("p26@40: see above\n", "p26@40"),
        ("26:\n  2: A14\n", "points down"),
        ("- 26\n", "points down"),
        ("eq 3: '3'\n", "'eq 3'"),
    ]:
        path.write_text(text, encoding="utf-8")
        with pytest.raises(ValueError, match=message):
            read_corrections(path)


@pytest.mark.parametrize(
    ("line", "number"),
    [
        ("y = a + b x (3)", "3"),
        ("(A12)", "A12"),
        ("[S3]", "S3"),
        ("y = p(K4)", "K4"),  # read, then not taken: out of order
        ("x ~ N(0, 0.4)", None),  # a value, not a number
        ("x = 1 (0.4)", None),
    ],
)
def test_equation_number_at_the_end_of_a_line(line, number):
    m = EQUATION_NUMBER.search(line)
    assert (m.group(1) if m else None) == number


def test_marks_take_the_same_numbers():
    assert EQUATION_MARK.fullmatch("[Equation A.12]").group(1) == "A.12"
    assert EQUATION_MARK.fullmatch("[Equation 2.1]").group(1) == "2.1"


def test_equations_page_applies_corrections(tmp_path):
    listed = [
        {"page": 2, "number": "1", "read": "1", "section": "", "picture": None},
        {"page": 2, "number": None, "read": None, "down": 400, "section": "",
         "picture": None},
        {"page": 3, "number": "3", "read": "3", "down": 80, "section": "",
         "picture": None},
    ]  # fmt: skip
    (tmp_path / EQUATIONS_FILE).parent.mkdir(parents=True)
    (tmp_path / EQUATIONS_FILE).write_text(json.dumps(listed), encoding="utf-8")
    out = equations.write_page(tmp_path)
    assert "2 not found (between 1 and 3)" in out
    (tmp_path / numbering.CORRECTIONS).parent.mkdir()
    (tmp_path / numbering.CORRECTIONS).write_text("p2@400: '2'\n", encoding="utf-8")
    out = equations.write_page(tmp_path)
    assert "not found" not in out
    saved = json.loads((tmp_path / EQUATIONS_FILE).read_text(encoding="utf-8"))
    assert [r["key"] for r in saved] == ["1", "2", "3"]
    page = (tmp_path / equations.PAGE).read_text(encoding="utf-8")
    assert "Number from" in page
    assert "page 3 · place p3@80" in page


def test_equations_page_matches_a_typed_key_a_little_away(tmp_path):
    listed = [
        {"page": 2, "number": None, "read": None, "down": 300, "section": "",
         "picture": None},
    ]  # fmt: skip
    (tmp_path / EQUATIONS_FILE).parent.mkdir(parents=True)
    (tmp_path / EQUATIONS_FILE).write_text(json.dumps(listed), encoding="utf-8")
    (tmp_path / equations.TYPED).parent.mkdir()
    (tmp_path / equations.TYPED).write_text("p2@296: 'y = a + b'\n", encoding="utf-8")
    text, count, done, unmatched = equations.page(tmp_path)
    assert (count, done, unmatched) == (1, 1, [])
    assert "Equation p2@300" in text and "typed in as p2@296" in text
