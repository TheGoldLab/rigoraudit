# Copyright (c) 2026, Joshua I. Gold
# SPDX-License-Identifier: BSD-2-Clause

import importlib.util
import json
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent.parent / "scripts" / "check_no_audit_content.py"
spec = importlib.util.spec_from_file_location("check_no_audit_content", SCRIPT)
check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check)

PAPER = (
    "Participants pressed the left key whenever the striped grating "
    "tilted clockwise within the cued window."
)


@pytest.fixture
def root(tmp_path, monkeypatch):
    space = tmp_path / "2025_Example"
    (space / "work" / "extract").mkdir(parents=True)
    (space / "audit.yaml").write_text("paper: {}\n", encoding="utf-8")
    (space / "work" / "extract" / "published.txt").write_text(PAPER, encoding="utf-8")
    (space / "release_terms.txt").write_text(
        "# comment\nZorblatt\nsubject Q7\n", encoding="utf-8"
    )
    monkeypatch.setenv("RIGORAUDIT_PRIVATE_ROOTS", str(tmp_path))
    return tmp_path


def private(root: Path):
    roots = check.private_roots()
    spaces = check.workspaces(roots)
    return check.read_terms(roots, spaces), check.private_runs(spaces)


def test_terms_are_whole_words_and_case_sensitive(root):
    terms, seen = private(root)
    assert terms == ["Zorblatt", "subject Q7"]
    found = check.text_problems(
        "f.md", "Zorblatt et al.\nzorblatt\nsubject Q70\n", terms, seen
    )
    assert found == ["f.md:1: term 'Zorblatt'"]


def test_copied_text_is_found_across_line_breaks_and_case(root):
    terms, seen = private(root)
    text = "As shown, PARTICIPANTS pressed the left key\nwhenever the striped grating tilted."
    [problem] = check.text_problems("f.md", text, terms, seen)
    assert "participants pressed the left key whenever the striped grating" in problem


def test_short_overlaps_are_allowed(root):
    terms, seen = private(root)
    assert (
        check.text_problems("f.md", "the left key whenever the striped", terms, seen)
        == []
    )


def test_runs_of_single_digits_and_letters_are_not_compared(root):
    space = root / "2025_Example" / "work" / "extract"
    (space / "values.txt").write_text(
        "0 1 1 1 1 1 2 2 2 1 and x = a + b y c d e f\n", encoding="utf-8"
    )
    terms, seen = private(root)
    text = 'keys = ["0+1", "1", "1+1", "1+2", "2", "2+1"]; x = a + b y c d e f'
    assert check.text_problems("f.py", text, terms, seen) == []
    # distinctive values are still compared
    (space / "values.txt").write_text(
        "n 18,236 mean 412.6 sd 33.1 range 12 to 97\n", encoding="utf-8"
    )
    terms, seen = private(root)
    text = "n 18,236 mean 412.6 sd 33.1 range 12 to 97"
    assert check.text_problems("f.py", text, terms, seen)


def test_record_keys_are_not_compared(root):
    space = root / "2025_Example"
    (space / "record").mkdir()
    (space / "record" / "record.json").write_text(
        '{"file": "m.pdf", "section": "Results", "paragraph": 1, "char_start": 0,'
        ' "char_end": 9, "page": 2, "quote": "short quote"}',
        encoding="utf-8",
    )
    terms, seen = private(root)
    snippet = (
        'file="m.pdf", section="Results", paragraph=1, char_start=0, char_end=9, page=2'
    )
    assert check.text_problems("t.py", snippet, terms, seen) == []


def test_the_tools_notes_in_equations_are_not_compared(root):
    space = root / "2025_Example" / "work" / "extract"
    note = "the number read here is out of order with the numbers around it"
    formula = "the made up rate grows with the made up dose over time"
    (space / "equations.json").write_text(
        json.dumps([{"note": note, "text": formula}]), encoding="utf-8"
    )
    terms, seen = private(root)
    assert check.text_problems("n.py", note, terms, seen) == []
    assert check.text_problems("n.py", formula, terms, seen) != []


def test_the_tools_wording_in_its_findings_is_not_compared(root):
    space = root / "2025_Example"
    (space / "record").mkdir()
    message = "the text does not say how the made up groups were formed"
    quote = "each made up group held the volunteers who arrived on one day"
    finding = {"summary": message, "drafted_by": {"kind": "tool"},
               "observations": [{"statement": message, "anchor": {"quote": quote}}]}  # fmt: skip
    model = {"summary": PAPER, "drafted_by": {"kind": "model"}}
    (space / "record" / "record.json").write_text(
        json.dumps(
            {
                "findings": [finding, model],
                "context": [{"assumes": message, "data": PAPER}],
            }
        ),
        encoding="utf-8",
    )
    terms, seen = private(root)
    assert check.text_problems("s.py", message, terms, seen) == []
    assert check.text_problems("s.py", quote, terms, seen) != []
    assert check.text_problems("s.py", PAPER, terms, seen) != []


def test_material_files_are_refused():
    assert check.file_problems("data/x.mat", b"")
    assert check.file_problems("paper.PDF", b"")
    assert check.file_problems("notes.md", b"x" * (check.MAX_BYTES + 1))
    assert check.file_problems("notes.md", b"text") == []


def test_no_workspaces_means_file_checks_only(tmp_path, monkeypatch):
    monkeypatch.setenv("RIGORAUDIT_PRIVATE_ROOTS", str(tmp_path))
    assert check.workspaces(check.private_roots()) == []
