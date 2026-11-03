# Copyright (c) 2026, Joshua I. Gold
# SPDX-License-Identifier: BSD-2-Clause

import shutil
from pathlib import Path

import pytest

from rigoraudit import cli, status

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "example-audit"


def test_the_workspace_comes_last_and_defaults_to_here():
    parse = cli._parser().parse_args
    args = parse(["import", "segment", "reply.txt", "--by", "A. Reviewer"])
    assert (args.reply, args.workspace) == (Path("reply.txt"), Path("."))
    args = parse(["handoff", "trace", "audits/one"])
    assert (args.step, args.workspace) == ("trace", Path("audits/one"))
    assert not hasattr(parse(["osf", "https://osf.io/abcde/", "code"]), "workspace")


def test_review_names_the_reviewer(tmp_path, monkeypatch):
    seen = {}
    monkeypatch.setattr(
        cli.server, "serve", lambda ws, reviewer, port: seen.update(r=reviewer, p=port)
    )
    cli.main(["review", str(tmp_path), "--reviewer", "A. Reviewer"])
    assert seen == {"r": "A. Reviewer", "p": 8765}


def test_check_passes_on_the_example_and_fails_on_a_changed_quote(tmp_path, capsys):
    ws = tmp_path / "example-audit"
    shutil.copytree(EXAMPLE, ws)
    (ws / status.CHECKS).unlink()
    cli.main(["check", str(ws)])
    out = capsys.readouterr().out
    assert "Anchors: 10 checked; 10 verified." in out and "All checks pass." in out
    assert status.load_checks(ws).uncovered == 0
    code = ws / "materials" / "code" / "analysis.py"
    code.write_text(code.read_text().replace("2.5", "3.0"))
    with pytest.raises(SystemExit) as stop:
        cli.main(["check", str(ws)])
    assert stop.value.code == 1
    assert "MISMATCH: finding R1.2.b/analysis code" in capsys.readouterr().out


def test_a_missing_record_is_a_short_message(tmp_path):
    with pytest.raises(SystemExit, match="record/record.json is missing"):
        cli.main(["report", str(tmp_path)])


def test_extract_without_a_manifest_is_a_short_message(tmp_path):
    with pytest.raises(SystemExit, match="no audit.yaml"):
        cli.main(["extract", str(tmp_path)])


def test_extract_names_a_paper_that_is_not_there(tmp_path):
    (tmp_path / "audit.yaml").write_text(
        "materials:\n  manuscript:\n    path: manuscript/paper.pdf\n"
    )
    with pytest.raises(SystemExit, match="but there is no file there"):
        cli.main(["extract", str(tmp_path)])
