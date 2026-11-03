# Copyright (c) 2026, Joshua I. Gold
# SPDX-License-Identifier: BSD-2-Clause

import json

from rigoraudit import codeindex


def test_python_functions_and_first_assignments():
    lines = [
        "# setup = ignored",
        "import numpy as np",
        "rate = 0.5",
        "def fit(x):",
        "    y, z = x, 2",
        "    rate = 1",
        "    if y == z:",
        "class Model:",
        "    total += 1",
    ]
    f = codeindex.index_lines("a/fit.py", lines)
    assert f.functions == (("fit", 4), ("Model", 8))
    assert f.first_set == (("rate", 3), ("y", 5), ("z", 5), ("total", 9))


def test_matlab_functions_structs_and_multiple_outputs():
    lines = [
        "function [m, s] = summarize(x)",
        "% m = comment",
        "cfg.window = [0 1];",
        "[m, ~, s] = stats(x);",
        "counts(3) = 4;",
        "if m == s",
        "function helper",
    ]
    f = codeindex.index_lines("summarize.m", lines)
    assert f.functions == (("summarize", 1), ("helper", 7))
    assert f.first_set == (("cfg", 3), ("m", 4), ("s", 4), ("counts", 5))


def test_r_functions_and_assignments():
    f = codeindex.index_lines(
        "fit.R", ["fit.model <- function(d) {", "  n <- nrow(d)", "k = 3", "x == 1"]
    )
    assert f.functions == (("fit.model", 1),)
    assert f.first_set == (("n", 2), ("k", 3))


def test_other_files_are_counted_by_folder(tmp_path):
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "trials.json").write_text("[]")
    (tmp_path / "README.txt").write_text("x")
    (tmp_path / "run.py").write_text("n = 1\n")
    index = codeindex.build_index(tmp_path, None)
    assert [f.file for f in index.files] == ["run.py"]
    assert index.other == {".": 1, "data": 1}
    text = "\n".join(codeindex.render_index(index))
    assert "### `run.py` (1 line)" in text
    assert "Other files, not indexed: 2, in ./ (1), data/ (1)." in text


def _notebook(cells, language="python"):
    return json.dumps(
        {
            "metadata": {"language_info": {"name": language}},
            "cells": [
                {"cell_type": kind, "source": source.splitlines(keepends=True)}
                for kind, source in cells
            ],
        }
    )


def test_a_notebook_is_read_as_its_code_cells(tmp_path):
    book = _notebook(
        [
            ("markdown", "# Fits\nrate = 9"),
            ("code", "import numpy as np\nrate = 0.5"),
            ("code", "def fit(x):\n    return x"),
        ]
    )
    (tmp_path / "fits.ipynb").write_text(book)
    lines = codeindex.code_lines(tmp_path, "fits.ipynb", None)
    assert lines == [
        "# Code cells of a Jupyter notebook in python",
        "# code cell 1",
        "import numpy as np",
        "rate = 0.5",
        "# code cell 2",
        "def fit(x):",
        "    return x",
    ]
    index = codeindex.build_index(tmp_path, None)
    assert index.files[0].functions == (("fit", 6),)
    assert index.files[0].first_set == (("rate", 4),)
    assert index.other == {}


def test_a_notebooks_text_is_kept_apart_from_its_code(tmp_path):
    book = _notebook(
        [
            ("markdown", "# Fits\nRun after loading."),
            ("code", "rate = 0.5"),
            ("markdown", "## Plots"),
            ("markdown", "Slow."),
            ("code", "plot(rate)"),
            ("markdown", "# Versions"),
        ]
    )
    assert codeindex.notebook_lines(book)[3] == "# code cell 2"
    assert codeindex.notebook_text(book) == (
        "Text cell 1, before line 2:\n# Fits\nRun after loading.\n\n"
        "Text cell 2, before line 4:\n## Plots\n\n"
        "Text cell 3, before line 4:\nSlow.\n\n"
        "Text cell 4, after the last code cell:\n# Versions"
    )
    (tmp_path / "fits.ipynb").write_text(book)
    [f] = codeindex.build_index(tmp_path, None).files
    assert f.sections == (("Fits", 2), ("Plots", 4))
    text = "\n".join(codeindex.render_index(codeindex.build_index(tmp_path, None)))
    assert "- sections of its text: Fits (2), Plots (4)" in text


def test_a_notebook_in_an_unknown_language_is_counted_not_indexed(tmp_path):
    (tmp_path / "a.ipynb").write_text(_notebook([("code", "x = 1")], "scala"))
    (tmp_path / "b.ipynb").write_text("not a notebook")
    index = codeindex.build_index(tmp_path, None)
    assert index.files == ()
    assert index.other == {".": 2}


def test_a_matlab_notebook_uses_matlab_comments():
    lines = codeindex.notebook_lines(_notebook([("code", "x = 1;")], "matlab"))
    assert lines[:2] == [
        "% Code cells of a Jupyter notebook in matlab",
        "% code cell 1",
    ]
    assert codeindex.index_lines("a.ipynb", lines).first_set == (("x", 3),)
