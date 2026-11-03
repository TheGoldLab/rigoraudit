# Copyright (c) 2026, Joshua I. Gold
# SPDX-License-Identifier: BSD-2-Clause

import datetime
import json

import pytest

from rigoraudit import cli, feedback

RESULTS = "Mean dwell time was 412 ms in the bright arena."
SECRET = "bright arena"


@pytest.fixture
def ws(tmp_path):
    (tmp_path / "audit.yaml").write_text(
        "materials:\n  manuscript:\n    path: materials/secret_title.pdf\n",
        encoding="utf-8",
    )
    extract = tmp_path / "work" / "extract" / "paragraphs.json"
    extract.parent.mkdir(parents=True)
    extract.write_text(
        json.dumps([{"section": "Results", "paragraph": 1, "text": RESULTS}]),
        encoding="utf-8",
    )
    return tmp_path


def run(ws, *args):
    try:
        cli.main([*args])
    except SystemExit as e:
        return e.code
    return 0


def answer(ws, quote):
    claim = {"id": "R1.1.a", "paragraph": "R1.1", "type": "new_result", "quote": quote}
    path = ws / "reply.txt"
    path.write_text(
        json.dumps({"instructions": "segment v2", "claims": [claim]}), encoding="utf-8"
    )
    return path


def test_runs_are_reported_by_kind_without_the_materials(ws, capsys):
    assert run(ws, "handoff", "segment", str(ws)) == 0
    bad = answer(ws, "Mean dwell time was 412 ms in the bright room")
    assert run(ws, "import", "segment", str(bad), str(ws), "--by", "t") == 1
    good = answer(ws, RESULTS.rstrip("."))
    assert run(ws, "import", "segment", str(good), str(ws), "--by", "t") == 0
    # a failure: the trace step needs code in the manifest
    with pytest.raises(SystemExit, match="no code"):
        cli.main(["handoff", "trace", str(ws)])

    text = (ws / feedback.REPORT).read_text(encoding="utf-8")
    assert "| handoff | segment | segment v2 | wrote 1 |" in text
    assert "| sent back |" in text and "quote-not-found ×1" in text
    assert "| accepted |" in text
    assert "- segment: 2" in text  # tries for the one accepted answer
    assert "- handoff trace: ValueError at rigoraudit/trace.py:" in text
    # the summary says the same in words
    assert "- Steps worked on: segment, trace." in text
    assert "- The assistant's answers: 1 accepted, 1 sent back to be fixed." in text
    assert "1 of the accepted answers needed more than one try (at most 2)" in text
    assert "- Why answers were sent back: quote not found (once); text" in text
    assert "- The tool itself broke once" in text
    assert "This is worth sending: the tool broke" in text
    for private in (SECRET, "412", "secret_title", "R1.1", str(ws), "no code"):
        assert private not in text, private


def test_your_words_and_added_material_are_kept(ws, capsys):
    run(ws, "handoff", "segment", str(ws))
    report = ws / feedback.REPORT
    report.write_text(
        report.read_text(encoding="utf-8").replace(
            feedback._PROMPT, "The second import was confusing."
        ),
        encoding="utf-8",
    )
    reply = answer(ws, "not there")
    run(ws, "feedback", str(ws), "--include", str(reply))
    run(ws, "import", "segment", str(reply), str(ws), "--by", "t")
    text = report.read_text(encoding="utf-8")
    assert "The second import was confusing." in text
    assert f"## {feedback.MATERIAL}" in text and '"quote": "not there"' in text
    assert "| sent back |" in text

    capsys.readouterr()
    run(ws, "feedback", str(ws))
    out = capsys.readouterr().out
    assert "except the audit material you added" in out
    assert "send it by email, not as a public issue" in out


def test_one_report_covers_the_whole_audit(ws):
    first = datetime.datetime(2026, 1, 1, 9, 0)
    later = datetime.datetime(2026, 1, 2, 14, 30)
    feedback.record(ws, "audit", outcome="stopped", now=first)
    feedback.record(ws, "check", outcome="passed", now=later)
    feedback.record(ws, "audit", outcome="finished", now=later)
    [report] = (ws / "work" / "feedback").glob("*.md")
    assert report == ws / feedback.REPORT
    text = report.read_text(encoding="utf-8")
    assert "from 1 January 2026 at 09:00 to 2 January 2026 at 14:30" in text
    assert "the guide ran 2 times" in text
    assert "| 2026-01-02 14:30:00 | check |" in text


def test_nothing_is_recorded_outside_a_workspace(tmp_path, capsys):
    (tmp_path / "work" / "extract").mkdir(parents=True)
    (tmp_path / "work" / "extract" / "paragraphs.json").write_text(
        json.dumps([{"section": "Results", "paragraph": 1, "text": RESULTS}]),
        encoding="utf-8",
    )
    cli.main(["handoff", "decompose", str(tmp_path)])
    assert "Nothing to hand off" in capsys.readouterr().out
    assert not (tmp_path / "work" / "feedback").exists()
