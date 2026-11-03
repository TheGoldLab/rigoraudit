# Copyright (c) 2026, Joshua I. Gold
# SPDX-License-Identifier: BSD-2-Clause

import json
import shutil
from pathlib import Path

from rigoraudit import check, crosscheck, segment
from rigoraudit.coverage import EXCLUSIONS

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "example-audit"


def test_gaps_must_name_claims_in_the_record(tmp_path):
    ws = tmp_path / "example-audit"
    shutil.copytree(EXAMPLE, ws, ignore=shutil.ignore_patterns("review", "__pycache__"))
    result = check.run(ws)
    assert result.passed and (ws / crosscheck.FINDINGS).is_file()
    assert "Cross-claim checks: 0 values" in check.describe(result)
    manifest = ws / "audit.yaml"
    manifest.write_text(
        manifest.read_text(encoding="utf-8").replace(
            "claims: []", "claims: [R1.2.a, R9.9.z]"
        ),
        encoding="utf-8",
    )
    result = check.run(ws)
    assert result.gap_claims == ("R9.9.z",) and not result.passed
    assert "GAPS name claims not in the record: R9.9.z" in check.describe(result)


def test_segment_left_out_items_are_exclusions(tmp_path):
    paragraphs = tmp_path / "work" / "extract" / "paragraphs.json"
    paragraphs.parent.mkdir(parents=True)
    paragraphs.write_text(
        (EXAMPLE / "work/extract/paragraphs.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    assert check.read_exclusions(tmp_path) is None
    segment.write_handoffs(tmp_path)
    answer = {
        "instructions": segment.instructions.load("segment").label,
        "claims": [
            {"id": "R1.2.a", "paragraph": "R1.2", "type": "new_result",
             "quote": "Twelve mice completed 3,600 trials over 10 sessions."},
            {"id": "R1.2.b", "paragraph": "R1.2", "type": "new_result",
             "quote": "Accuracy rose from 60% in session 1 to 87% in session 10"},
        ],
        "left_out": [{"paragraph": "R1.1", "quote": "(4 and 8 kHz)", "reason": "task"}],
    }  # fmt: skip
    assert segment.import_answer(tmp_path, json.dumps(answer), "test")[1] == []
    (tmp_path / EXCLUSIONS).parent.mkdir()
    (tmp_path / EXCLUSIONS).write_text(
        json.dumps(
            {"exclusions": [{"paragraph": "R1.2", "quote": "10", "reason": "x"}]}
        ),
        encoding="utf-8",
    )
    assert [(e.quote, e.reason) for e in check.read_exclusions(tmp_path)] == [
        ("(4 and 8 kHz)", "task"),
        ("10", "x"),
    ]
