# Copyright (c) 2026, Joshua I. Gold
# SPDX-License-Identifier: BSD-2-Clause

import json

import pytest
from test_derive import GOOD, A, B, both, reply, ws, ws_two  # noqa: F401  (fixtures)

from rigoraudit import cli, compare, derive, instructions, settings
from rigoraudit.schema import RECORD, AuditRecord, Status, Trace


@pytest.fixture
def derived(ws):  # noqa: F811
    """The workspace, with the claim's number recomputed."""
    derive.write_handoffs(ws, settings.load(ws))
    _, problems = derive.import_answer(
        ws, settings.load(ws), reply(GOOD), "T", approve=lambda p, c: True
    )
    assert not problems
    compare.write_handoffs(ws, settings.load(ws))
    return ws


def answer(*findings):
    return json.dumps({"instructions": "compare v6", "claims": [
        {"claim": "R1.1.a", "findings": list(findings)}]})  # fmt: skip


PRECISION = {"facet": "quantity", "observations": ["O1", "O2"],
             "basis": "reported_precision",
             "comparisons": [{"kind": "precision", "stated": ["O1.v1"], "observed": ["O2.v1"]}],
             "summary": "The Results state 75%. The data give 75%."}  # fmt: skip
SILENT = {"facet": "condition", "observations": ["O3"], "status": "not_verifiable",
          "reason": "The data do not record the block.", "summary": "s"}  # fmt: skip


def test_the_handoff_labels_every_observation_and_value(derived):
    [path] = sorted((derived / "work" / "compare" / "handoffs").glob("*.md"))
    text = path.read_text(encoding="utf-8")
    assert "- `O1` (results, quoted; Results, paragraph 1)" in text
    assert "`O1.v1`: accuracy 75% (for block A, 0 decimals shown)" in text
    assert (
        "- `O2` (data, recomputed; `data/trials.json`, by `derivations/R1.1.a.py`)"
        in text
    )
    assert "## condition" in text


def test_the_handoff_gives_why_a_worded_claim_cannot_be_checked(ws):  # noqa: F811
    derive.write_handoffs(ws, settings.load(ws))
    why = [{"for": "condition", "reason": "the data do not record the block"}]
    _, problems = derive.import_answer(
        ws, settings.load(ws), reply(GOOD, why), "T", approve=lambda p, c: True
    )
    assert not problems
    [path] = compare.write_handoffs(ws, settings.load(ws))
    assert (
        "- condition, as stated in words: the data do not record the block"
        in path.read_text(encoding="utf-8")
    )


def test_the_status_is_computed_and_the_record_built(derived):
    saved, problems = compare.import_answer(derived, answer(PRECISION, SILENT), "T")
    assert problems == [] and saved is not None
    path = compare.write_record(derived, settings.load(derived))
    record = AuditRecord.model_validate_json(path.read_text(encoding="utf-8"))
    [claim] = record.claims
    assert claim.trace is Trace.TRACED
    assert [f.status for f in record.findings] == [
        Status.CONSISTENT,
        Status.NOT_VERIFIABLE,
    ]
    assert record.drafted_by.prompt_version == instructions.load("compare").label


def test_a_finding_the_record_would_refuse_is_sent_back(derived):
    one_source = {**PRECISION, "observations": ["O1"]}
    _, problems = compare.import_answer(derived, answer(one_source, SILENT), "T")
    assert {p.kind for p in problems} == {"finding-invalid"}
    _, problems = compare.import_answer(derived, answer(PRECISION), "T")
    assert [p.kind for p in problems] == ["facet-missing"]
    wrong = {
        **PRECISION,
        "comparisons": [{**PRECISION["comparisons"][0], "stated": ["O1.v9"]}],
    }
    _, problems = compare.import_answer(derived, answer(wrong, SILENT), "T")
    assert [p.kind for p in problems] == ["unknown-label"]
    # a stated status that contradicts the values is refused
    _, problems = compare.import_answer(
        derived, answer({**PRECISION, "status": "differs"}, SILENT), "T"
    )
    assert "contradicts the comparisons" in problems[0]


def test_a_direction_stated_in_words_is_compared_by_sign(derived):
    sign = {"facet": "quantity", "observations": ["O1", "O2"], "basis": "direction",
            "comparisons": [{"kind": "sign", "stated": ["+"], "observed": ["O2.v1"],
                             "hedge": "correct on 75%"}],
            "summary": "The Results state a positive value. The data give 75."}  # fmt: skip
    no_words = {**sign, "comparisons": [{**sign["comparisons"][0], "hedge": None}]}
    _, problems = compare.import_answer(derived, answer(no_words, SILENT), "T")
    assert [p.kind for p in problems] == ["unknown-label"]
    assert "needs the words" in problems[0]

    saved, problems = compare.import_answer(derived, answer(sign, SILENT), "T")
    assert problems == [] and saved is not None
    [found, _] = compare.read_accepted(derived)[0].findings
    assert found.status is Status.CONSISTENT
    assert found.observations[0].values[-1].value == 1  # added to the Results item
    assert found.comparisons[0].describe() == (
        "“correct on 75%” read as direction (positive)"
    )


def test_an_audit_with_its_own_record_script_keeps_it(derived, capsys):
    (derived / "record").mkdir(exist_ok=True)
    (derived / "record" / "record.py").write_text("", encoding="utf-8")
    with pytest.raises(SystemExit, match="its own record/record.py"):
        cli.main(["record", str(derived)])
    assert not (derived / RECORD).exists()


def test_claims_share_a_task_and_every_one_needs_findings(ws_two):  # noqa: F811
    s = settings.load(ws_two)
    derive.write_handoffs(ws_two, s)
    _, problems = derive.import_answer(
        ws_two, settings.load(ws_two), both(A, B), "T", approve=lambda p, c: True
    )
    assert not problems
    [path] = compare.write_handoffs(ws_two, s)
    text = path.read_text(encoding="utf-8")
    assert "### Claim `R1.1.a`" in text and "### Claim `R1.1.b`" in text
    [h] = compare.pending_handoffs(ws_two)
    labels = [label for c in h.claims for label in c.observations]
    assert len(labels) == len(set(labels)) == 4  # numbered through the task

    def finding(o1, o2):
        return {"facet": "quantity" if o1 == "O1" else "population",
                "observations": [o1, o2], "basis": "reported_precision",
                "comparisons": [{"kind": "precision", "stated": [f"{o1}.v1"],
                                 "observed": [f"{o2}.v1"]}], "summary": "s"}  # fmt: skip

    a = {"claim": "R1.1.a", "findings": [finding("O1", "O2")]}
    b = {"claim": "R1.1.b", "findings": [finding("O3", "O4")]}
    reply_ = {"instructions": "compare v6", "claims": [a]}
    _, problems = compare.import_answer(ws_two, json.dumps(reply_), "T")
    assert [p.kind for p in problems] == ["claim-missing"]
    reply_["claims"] = [a, b]
    saved, problems = compare.import_answer(ws_two, json.dumps(reply_), "T")
    assert problems == [] and saved is not None
    record = compare.build_record(ws_two, s)
    assert {f.claim_id for f in record.findings} == {"R1.1.a", "R1.1.b"}
    assert all(f.status is Status.CONSISTENT for f in record.findings)


def test_a_threshold_stated_in_words_is_compared_by_inequality(derived):
    at = {"facet": "quantity", "observations": ["O1", "O2"], "basis": "direction",
          "comparisons": [{"kind": "inequality", "stated": ["> 50"], "observed": ["O2.v1"],
                           "hedge": "most"}],
          "summary": "The Results state most. The data give 75."}  # fmt: skip
    no_words = {**at, "comparisons": [{**at["comparisons"][0], "hedge": None}]}
    _, problems = compare.import_answer(derived, answer(no_words, SILENT), "T")
    assert "a threshold stated as > 50 needs the words" in problems[0]

    saved, problems = compare.import_answer(derived, answer(at, SILENT), "T")
    assert problems == [] and saved is not None
    [found, _] = compare.read_accepted(derived)[0].findings
    assert found.status is Status.CONSISTENT
    assert found.observations[0].values[-1].value == 50  # added to the Results item
    assert found.comparisons[0].describe() == "“most” read as accuracy > 50"
