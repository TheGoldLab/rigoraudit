# Copyright (c) 2026, Joshua I. Gold
# SPDX-License-Identifier: BSD-2-Clause

import json
import re
import subprocess

import pytest

from miragold import cli, docs, instructions, settings

README = """# Dwell analysis

Run main.py, then plots.py.
Requires Python 3.11 and
numpy.
"""
MAIN = '''"""Fits dwell times.

Writes results/table2.csv.
"""
import numpy
'''
MATLAB = """function out = smooth_rates(x)
% SMOOTH_RATES  Smooths firing rates.
% Needs the Signal Processing Toolbox.
out = x;
"""


def git(cwd, *args):
    return subprocess.run(
        ["git", "-c", "user.name=T", "-c", "user.email=t@example.org", *args],
        cwd=cwd, check=True, capture_output=True, text=True,
    ).stdout.strip()  # fmt: skip


@pytest.fixture
def ws(tmp_path):
    code = tmp_path / "materials" / "code"
    (code / "lib").mkdir(parents=True)
    (code / "README.md").write_text(README, encoding="utf-8")
    (code / "main.py").write_text(MAIN, encoding="utf-8")
    (code / "lib" / "smooth_rates.m").write_text(MATLAB, encoding="utf-8")
    (code / "requirements.txt").write_text("numpy==2.1\n", encoding="utf-8")
    (code / "fig_rates.pdf").write_bytes(b"%PDF figure output")
    git(code, "init", "-q")
    git(code, "add", ".")
    git(code, "commit", "-q", "-m", "c")
    commit = git(code, "rev-parse", "HEAD")
    data = tmp_path / "materials" / "data"
    data.mkdir()
    (data / "codebook.md").write_text("Column dwell is in ms.\n", encoding="utf-8")
    (data / "trials.txt").write_text("1 2 3\n", encoding="utf-8")
    paper = tmp_path / "materials" / "manuscript"
    paper.mkdir()
    (paper / "paper.pdf").write_bytes(b"%PDF")
    (paper / "notes.md").write_text(
        "Reviewer notes, not code documentation.\n", encoding="utf-8"
    )
    (tmp_path / "audit.yaml").write_text(
        "materials:\n  manuscript:\n    path: manuscript/paper.pdf\n"
        f"  code:\n    path: code\n    commit: {commit}\n"
        "settings:\n  run:\n    scripts: [code/main.py]\n",
        encoding="utf-8",
    )
    return tmp_path


def test_documentation_is_found_and_figures_and_the_paper_are_not(ws):
    found = docs.list_documentation(ws, settings.load(ws), ["code/lib/smooth_rates.m"])
    assert [(d.file, d.kind) for d in found] == [
        ("code/README.md", docs.Kind.PROSE),
        ("code/lib/smooth_rates.m (opening comment)", docs.Kind.HEADER),
        ("code/main.py (opening comment)", docs.Kind.HEADER),
        ("code/requirements.txt", docs.Kind.DEPENDENCIES),
        ("data/codebook.md", docs.Kind.PROSE),
    ]
    headers = {d.file: d.text for d in found if d.kind is docs.Kind.HEADER}
    assert headers["code/main.py (opening comment)"].endswith(
        'Writes results/table2.csv.\n"""'
    )
    assert headers["code/lib/smooth_rates.m (opening comment)"] == (
        "% SMOOTH_RATES  Smooths firing rates.\n% Needs the Signal Processing Toolbox."
    )


def test_a_notebooks_text_cells_are_documentation(ws):
    code = ws / "materials" / "code"
    (code / "figures.ipynb").write_text(json.dumps({"cells": [
        {"cell_type": "markdown", "source": ["# Figures\n", "Unpack data/ first."]},
        {"cell_type": "code", "source": ["x = 1"]},
    ]}), encoding="utf-8")  # fmt: skip
    old = git(code, "rev-parse", "HEAD")
    git(code, "add", ".")
    git(code, "commit", "-q", "-m", "notebook")
    manifest = ws / "audit.yaml"
    manifest.write_text(
        manifest.read_text(encoding="utf-8").replace(
            old, git(code, "rev-parse", "HEAD")
        ),
        encoding="utf-8",
    )
    found = docs.list_documentation(ws, settings.load(ws))
    [book] = [d for d in found if d.kind is docs.Kind.NOTEBOOK]
    assert book.file == "code/figures.ipynb (text cells)"
    assert book.text == "Text cell 1, before line 2:\n# Figures\nUnpack data/ first."


def test_the_code_is_read_at_the_commit(ws):
    (ws / "materials" / "code" / "README.md").write_text(
        "Changed later.\n", encoding="utf-8"
    )
    [readme] = [
        d
        for d in docs.list_documentation(ws, settings.load(ws))
        if d.file == "code/README.md"
    ]
    assert readme.text.startswith("# Dwell analysis")


def notes(file, *pairs, nothing=()):
    return {
        "file": file,
        "notes": [{"heading": h, "quote": q, "states": "s"} for h, q in pairs],
        "says_nothing": list(nothing),
    }


ALL = [h.value for h in docs.Heading]


def good_answer():
    return {
        "instructions": "docs v1",
        "files": [
            # the quote spans a line break in the file
            notes("code/README.md", ("run", "Run main.py, then plots.py."),
                  ("software", "Requires Python 3.11 and numpy."),
                  nothing=["data", "settings", "outputs", "problems"]),
            notes("code/main.py (opening comment)", ("outputs", "Writes results/table2.csv."),
                  nothing=[h for h in ALL if h != "outputs"]),
            notes("code/requirements.txt", ("software", "numpy==2.1"),
                  nothing=[h for h in ALL if h != "software"]),
            notes("data/codebook.md", ("data", "Column dwell is in ms."),
                  nothing=[h for h in ALL if h != "data"]),
        ],
    }  # fmt: skip


def test_every_file_must_be_read_before_a_run(ws, capsys):
    s = settings.load(ws)
    assert len(docs.unread(ws, s)) == 4
    cli.main(["handoff", "docs", str(ws)])
    [md] = (ws / "work" / "docs" / "handoffs").glob("*.md")
    text = md.read_text(encoding="utf-8")
    assert "### `code/README.md` (documentation)" in text and "numpy==2.1" in text

    reply = ws / "reply.txt"
    reply.write_text(json.dumps(good_answer()), encoding="utf-8")
    cli.main(["import", "docs", str(reply), str(ws), "--by", "t"])
    assert "Accepted docs-1-" in capsys.readouterr().out
    assert docs.unread(ws, s) == []

    # a file that changes, or a new one, has to be read again
    (ws / "materials" / "data" / "codebook.md").write_text(
        "Column dwell is in s.\n", encoding="utf-8"
    )
    assert [d.file for d in docs.unread(ws, s)] == ["data/codebook.md"]


def test_headings_quotes_and_files_are_checked(ws):
    s = settings.load(ws)
    docs.write_handoffs(ws, s)
    answer = good_answer()
    answer["files"][0] = notes(
        "code/README.md", ("run", "Run plots.py first."), nothing=ALL
    )
    answer["files"].pop()
    answer["disagreements"] = [{"file": "code/other.md", "quote": "x", "states": "s"}]
    _, problems = docs.import_answer(ws, json.dumps(answer), "t")
    assert problems == [
        "data/codebook.md has no answer; give every heading for it.",
        "code/README.md: run has notes and is also listed as saying nothing; keep one.",
        (
            "In code/README.md, run: the quote is not in code/README.md word for "
            "word: 'Run plots.py first.'"
        ),
        "Disagreement 1 names code/other.md, which was not given.",
    ]
    answer = good_answer()
    answer["files"][3]["says_nothing"] = []
    problems = docs.import_answer(ws, json.dumps(answer), "t")[1]
    assert len(problems) == len(docs.Heading) - 1  # it has a data note
    assert problems[0].startswith("data/codebook.md: say what it says about run")


def test_a_documentation_pdf_is_listed_but_not_checked(ws, capsys):
    (ws / "materials" / "data" / "User_Guide.pdf").write_bytes(b"%PDF guide")
    s = settings.load(ws)
    docs.write_handoffs(ws, s)
    [md] = (ws / "work" / "docs" / "handoffs").glob("*.md")
    assert "This is a PDF: attach the file" in md.read_text(encoding="utf-8")
    answer = good_answer()
    answer["files"].append(notes("data/User_Guide.pdf", ("data", "anything"),
                                 nothing=[h for h in ALL if h != "data"]))  # fmt: skip
    reply = ws / "reply.txt"
    reply.write_text(json.dumps(answer), encoding="utf-8")
    cli.main(["import", "docs", str(reply), str(ws), "--by", "t"])
    assert "(1 PDF not checked)" in capsys.readouterr().out


def test_the_example_in_the_instructions_passes_the_check():
    text = instructions.load("docs").text
    example = json.loads(re.search(r"```json\n(.*?)```", text, re.DOTALL).group(1))
    given = [
        docs.DocFile(file="code/README.md", kind=docs.Kind.PROSE, sha256="x",
                     text="Run main.py, then plots.py.\nRequires Python 3.11 and numpy."),
        docs.DocFile(file="code/main.py (opening comment)", kind=docs.Kind.HEADER,
                     sha256="y", text='"""Writes results/table2.csv."""'),
    ]  # fmt: skip
    answer = docs.DocsAnswer.model_validate(example)
    assert docs.check_answer(answer, given) == []
