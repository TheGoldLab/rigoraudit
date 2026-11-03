# Copyright (c) 2026, Joshua I. Gold
# SPDX-License-Identifier: BSD-2-Clause

import json
import shutil
from pathlib import Path

import pytest

from rigoraudit import header, report, settings

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "example-audit"


@pytest.fixture
def ws(tmp_path):
    """The example audit without its own header."""
    ws = tmp_path / "example-audit"
    shutil.copytree(EXAMPLE, ws, ignore=shutil.ignore_patterns("review", "__pycache__"))
    (ws / report.HEADER).unlink()
    return ws


def answer(**change):
    return json.dumps({
        "instructions": "header v1",
        "heading": "Example (2026)",
        "title": "Tone discrimination learning in mice",
        "covers": "The Results <b>only</b>.",
        "materials": [
            {"name": "Manuscript", "text": "materials/manuscript.txt"},
            {"name": "Code", "text": "materials/code/analysis.py"},
        ],
        **change,
    })  # fmt: skip


def test_the_header_is_drafted_from_the_manifest_and_first_page(ws):
    s = settings.load(ws)
    (path,) = header.write_handoffs(ws, s)
    text = path.read_text(encoding="utf-8")
    assert "Give a line for each of: Manuscript, Code." in text
    assert "# Tone discrimination learning in mice" in text  # the first page
    assert "audit:\n  title:" in text  # the manifest

    saved, problems = header.import_answer(ws, answer(), "test")
    assert problems == [] and saved is not None
    page = (ws / report.HEADER).read_text(encoding="utf-8")
    assert "<h1>Example (2026)</h1>" in page
    assert "The Results &lt;b&gt;only&lt;/b&gt;." in page  # no markup gets through
    assert "<dt>Code</dt><dd>materials/code/analysis.py</dd>" in page
    assert report.render(ws)[0].count("<h1>Example (2026)</h1>") == 1
    assert header.plan_handoffs(ws, s) == []


def test_a_title_not_on_the_first_page_and_a_missing_material_are_sent_back(ws):
    header.write_handoffs(ws, settings.load(ws))
    reply = answer(
        title="Tone learning in mice",
        materials=[
            {"name": "Manuscript", "text": "a"},
            {"name": "Manuscript", "text": "b"},
        ],
    )
    saved, problems = header.import_answer(ws, reply, "test")
    assert saved is None and not (ws / report.HEADER).exists()
    assert [p.kind for p in problems] == [
        "title-not-found",
        "material-missing",
        "material-twice",
    ]


def test_a_header_written_by_hand_is_left_alone(ws):
    (ws / report.HEADER).write_text("<h1>Mine</h1>", encoding="utf-8")
    assert header.write_handoffs(ws, settings.load(ws)) == []
