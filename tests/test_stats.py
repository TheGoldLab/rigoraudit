# Copyright (c) 2026, Joshua I. Gold
# SPDX-License-Identifier: BSD-2-Clause

import datetime
import json

import pytest

from miragold import compare, decompose, segment, settings
from miragold.decompose import Design, EffectName, EffectSize, ReportedTest, Statistic
from miragold.paragraphs import Paragraph
from miragold.schema import Drafter, DrafterKind, Obtained, Status, Trace
from miragold.stats import (
    claim_test_findings,
    implied_n,
    resampling_margin,
    worked_effect,
    worked_p,
)

TOOL = Drafter(
    kind=DrafterKind.TOOL,
    name="miragold",
    stage="stats",
    date=datetime.date(2026, 1, 2),
)


def findings(text: str, **test):
    p = Paragraph(label="R2.1", section="Results", number=1, text=text, page=3)
    t = ReportedTest(**test)
    found = claim_test_findings("R2.1.a", t, "", p, "paper.pdf", TOOL)
    return {f.scope: f for f in found}


def test_p_worked_out_from_t_agrees_at_the_printed_precision():
    text = "Rats pressed faster, t(22) = 2.10, p = 0.047."
    f = findings(
        text, quote="t(22) = 2.10, p = 0.047", statistic="t", value="2.10",
        df=["22"], p="= 0.047",
    )["p from the statistic"]  # fmt: skip
    assert f.status is Status.CONSISTENT
    assert f.drafted_by == TOOL
    worked = f.observations[1]
    assert worked.obtained is Obtained.COMPUTED
    assert worked.values[0].value == pytest.approx(0.0474, abs=1e-4)
    assert "taken as two-tailed" in f.summary


def test_rounding_of_the_statistic_is_allowed_for():
    # p is 0.0486 at t = 2.1 itself, but 0.0537 at t = 2.05, which rounds to 2.1
    text = "Rats pressed faster, t(20) = 2.1, p = 0.052."
    f = findings(
        text, quote="t(20) = 2.1, p = 0.052", statistic="t", value="2.1",
        df=["20"], p="= 0.052",
    )["p from the statistic"]  # fmt: skip
    assert f.status is Status.CONSISTENT
    assert "allowing for rounding" in f.tolerance_text


def test_p_inequality_that_does_not_hold_differs():
    text = "The groups differed, F(2, 40) = 3.10, p < 0.01."
    f = findings(
        text, quote="F(2, 40) = 3.10, p < 0.01", statistic="F", value="3.10",
        df=["2", "40"], p="< 0.01",
    )["p from the statistic"]  # fmt: skip
    assert f.status is Status.DIFFERS


def test_n_from_the_degrees_of_freedom():
    text = "In 26 rats, t(22) = 2.10, p = 0.047 (independent groups)."
    test = {
        "quote": "t(22) = 2.10, p = 0.047", "statistic": "t", "value": "2.10", "df": ["22"],
        "p": "= 0.047", "n": "26", "n_quote": "26 rats",
    }  # fmt: skip
    f = findings(text, **test, design="independent")["N from the degrees of freedom"]
    assert f.status is Status.DIFFERS
    assert [o.anchor.quote for o in f.observations][:2] == [test["quote"], "26 rats"]
    f = findings(text, **test)["N from the degrees of freedom"]
    assert f.status is Status.NOT_VERIFIABLE
    assert "paired" in f.reason


def test_effect_size_from_t():
    text = "Rats pressed faster, t(22) = 2.10, p = 0.047, d = 0.90."
    test = {
        "quote": "t(22) = 2.10, p = 0.047, d = 0.90", "statistic": "t", "value": "2.10",
        "df": ["22"], "p": "= 0.047", "effect": {"name": "d", "printed": "0.90"},
    }  # fmt: skip
    f = findings(text, **test, design="independent")["effect size from the statistic"]
    assert f.status is Status.CONSISTENT  # 2t/√df = 0.895
    assert "equal groups" in f.summary
    f = findings(text, **test)["effect size from the statistic"]
    assert f.status is Status.NOT_VERIFIABLE


def test_a_statistic_the_tool_cannot_work_out_is_not_verifiable():
    text = "Licking differed, U = 31, p = 0.02."
    f = findings(text, quote="U = 31, p = 0.02", statistic="U", value="31", p="= 0.02")[
        "p from the statistic"
    ]
    assert f.status is Status.NOT_VERIFIABLE
    assert "cannot yet work out p" in f.reason


def test_worked_values():
    t = ReportedTest(quote="q", statistic=Statistic.R, value="0.50", df=("18",))
    w = worked_p(t)
    assert w.low < w.value < w.high
    assert implied_n(t) == 20
    paired = ReportedTest(
        quote="q", statistic=Statistic.T, value="-3.0", df=("9",), design=Design.PAIRED,
        effect=EffectSize(name=EffectName.D, printed="-0.95"),
    )  # fmt: skip
    assert implied_n(paired) == 10
    assert worked_effect(paired).value == pytest.approx(-3 / 10**0.5)
    welch = ReportedTest(quote="q", statistic=Statistic.T, value="2.0", df=("21.4",))
    assert "whole number" in implied_n(welch)
    assert "degrees of freedom" in worked_p(
        ReportedTest(quote="q", statistic=Statistic.T, value="2.0")
    )


def test_the_record_holds_the_tools_findings(tmp_path):
    text = "Rats pressed faster, t(22) = 2.10, p = 0.047."
    ws = tmp_path / "audit"
    ws.mkdir()
    (ws / "audit.yaml").write_text(
        "materials:\n  manuscript:\n    path: paper.pdf\n", encoding="utf-8"
    )
    para = ws / "work" / "extract" / "paragraphs.json"
    para.parent.mkdir(parents=True)
    para.write_text(
        json.dumps([{"section": "Results", "paragraph": 1, "text": text}]),
        encoding="utf-8",
    )
    segment.write_handoffs(ws, ("Results",))
    _, problems = segment.import_answer(ws, json.dumps({
        "instructions": "segment v3", "claims": [{"id": "R1.1.a", "paragraph": "R1.1",
        "type": "new_result", "quote": text.rstrip(".")}]}), "T")  # fmt: skip
    assert not problems
    decompose.write_handoffs(ws)
    _, problems = decompose.import_answer(ws, json.dumps({
        "instructions": "decompose v4", "claims": [{"id": "R1.1.a", "facets": [
        {"facet": "quantity", "quote": "pressed faster, t(22) = 2.10, p = 0.047",
         "states": "s"}], "tests": [{"quote": "t(22) = 2.10, p = 0.047",
        "statistic": "t", "value": "2.10", "df": ["22"], "p": "= 0.047"}]}]}), "T")  # fmt: skip
    assert not problems
    record = compare.build_record(ws, settings.load(ws))
    [f] = record.findings
    assert f.id == "R1.1.a/quantity/p-from-the-statistic"
    assert f.drafted_by.kind is DrafterKind.TOOL
    assert record.claims[0].trace is Trace.TRACED


def test_each_test_says_what_it_assumes():
    from miragold.stats import assumes

    def line(**test):
        return assumes(ReportedTest(quote="q", value="1", **test))

    assert line(statistic="t", design="paired").startswith("Assumes independent pairs")
    assert "straight-line" in line(statistic="r")
    assert "only rises or only falls" in line(
        statistic="r", named="Spearman correlation"
    )
    assert line(statistic="other") is None


def test_the_data_are_described_without_a_judgment():
    from miragold.stats import data_facts

    text = data_facts({"": [0, 0, 1, 1, 1, 0.5]}, rank=True, bounds=(0, 1))
    assert text == (
        "Data: N = 6, skew -0.33; tied values 83%; at the floor 33%, at the ceiling 50%."
    )


def test_a_test_printed_with_p_only_has_nothing_to_work_out():
    text = "Rats pressed faster (permutation test, p = 0.003)."
    found = findings(text, quote="p = 0.003", named="permutation test", p="= 0.003")
    assert found == {}


def test_the_resampling_margin_is_twice_the_error_of_two_runs():
    assert resampling_margin(0.05, 1000, 1000) == pytest.approx(0.0195, abs=1e-4)
    assert resampling_margin(0.0, 1000, 1000) == 0.0
