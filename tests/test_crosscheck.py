# Copyright (c) 2026, Joshua I. Gold
# SPDX-License-Identifier: BSD-2-Clause

import datetime
import json

from miragold import crosscheck
from miragold.crosscheck import agree
from miragold.schema import (
    AuditRecord,
    Claim,
    ClaimType,
    CodeAnchor,
    Drafter,
    DrafterKind,
    Finding,
    ManuscriptAnchor,
    Observation,
    Obtained,
    Relation,
    Rule,
    Source,
    Status,
    Trace,
    Value,
)

DRAFTER = Drafter(kind=DrafterKind.PERSON, name="T", date=datetime.date(2026, 1, 1))


def anchor(section, paragraph=1, start=0, quote="q"):
    return ManuscriptAnchor(
        file="paper.pdf",
        section=section,
        paragraph=paragraph,
        char_start=start,
        char_end=start + len(quote),
        quote=quote,
    )


def v(name, value, subject=None, unit=None, relation=Relation.EQ, decimals=None):
    return Value(
        name=name,
        value=value,
        subject=subject,
        unit=unit,
        relation=relation,
        decimals=decimals,
    )


def stated(section, *values, source=Source.RESULTS, paragraph=1):
    return Observation(
        source=source,
        statement="s",
        anchor=anchor(section, paragraph),
        obtained=Obtained.QUOTED,
        values=values,
    )


def code(start, end):
    return Observation(
        source=Source.CODE,
        statement="s",
        anchor=CodeAnchor(file="code/a.py", line_start=start, line_end=end, quote="x"),
        obtained=Obtained.READ,
    )


def claim(cid, restates=None):
    return Claim(
        id=cid,
        type=ClaimType.NEW_RESULT,
        anchor=anchor(f"Results {cid}"),
        trace=Trace.TRACED,
        restates=restates,
    )


def finding(cid, *observations):
    return Finding(
        id=f"{cid}/quantity",
        claim_id=cid,
        status=Status.NOT_VERIFIABLE,
        reason="r",
        summary="s",
        observations=observations,
    )


def record(*pairs):
    """``pairs``: (claim, observations) for each claim."""
    return AuditRecord(
        drafted_by=DRAFTER,
        claims=tuple(c for c, _ in pairs),
        findings=tuple(finding(c.id, *obs) for c, obs in pairs),
    )


def candidates(rec, tmp_path):
    """The candidate groups the rules propose, as value labels."""
    [h] = crosscheck.plan_handoffs(tmp_path, rec)
    return [(c.values, c.rules) for c in h.candidates]


def answer(*groups, set_aside=()):
    return crosscheck.CrossAnswer(
        instructions="crosscheck v1",
        groups=tuple(crosscheck.Group(values=g, reason="r") for g in groups),
        set_aside=tuple(
            crosscheck.SetAside(candidate=c, reason="r") for c in set_aside
        ),
    )


def test_the_same_label_in_two_claims_is_a_candidate(tmp_path):
    rec = record(
        (claim("R1.1.a"), [stated("A", v("sessions", 60, "group B"))]),
        (claim("F2.1.a"), [stated("B", v("Sessions", 61, "group  B"))]),
    )
    assert candidates(rec, tmp_path) == [(("V1", "V2"), (Rule.SAME_LABEL,))]
    [x] = crosscheck.find(rec, answer(("V1", "V2")))
    assert x.status is Status.DIFFERS
    assert x.rules == (Rule.SAME_LABEL,)
    assert x.claim_ids == ("R1.1.a", "F2.1.a")
    assert x.summary == "R1.1.a and F2.1.a give sessions (group B) as 60 and 61."


def test_a_summary_lists_each_claims_values_once(tmp_path):
    rec = record(
        (claim("R1.1.a"), [stated("A", v("sessions", 60, "group B"))]),
        (
            claim("M3.1.a"),
            [
                stated("B", v("sessions", 61, "group B"), v("sessions", 60, "group B")),
                stated("D", v("sessions", 61, "group B")),
            ],
        ),
    )
    [x] = crosscheck.find(rec, answer(("V1", "V2", "V3", "V4")))
    assert x.summary == "Sessions (group B): R1.1.a gives 60; M3.1.a gives 61 and 60."
    assert [(c, a.section) for c, a in crosscheck.quotes(x)] == [
        ("R1.1.a", "A"),
        ("M3.1.a", "B"),
        ("M3.1.a", "D"),
    ]


def test_a_value_with_no_subject_is_not_joined_by_its_label(tmp_path):
    rec = record(
        (claim("R1.1.a"), [stated("A", v("p", 0.01))]),
        (claim("R2.1.a"), [stated("B", v("p", 0.2))]),
    )
    assert candidates(rec, tmp_path) == []


def test_a_restatement_is_a_candidate(tmp_path):
    rec = record(
        (claim("R1.1.a"), [stated("A", v("slope", 0.42, decimals=2))]),
        (claim("D1.1.a", "R1.1.a"), [stated("B", v("slope", 0.4, decimals=1))]),
    )
    assert candidates(rec, tmp_path) == [(("V1", "V2"), (Rule.RESTATES,))]
    [x] = crosscheck.find(rec, answer(("V1", "V2")))
    assert x.status is Status.CONSISTENT  # at the coarser precision


def test_findings_on_the_same_code_lines_are_candidates(tmp_path):
    p1 = v("p", 0.01, relation=Relation.LT)
    p2 = v("p", 0.003, decimals=3)
    rec = record(
        (claim("R1.1.a"), [stated("A", p1), code(10, 20)]),
        (claim("S1.1.a"), [stated("B", p2), code(15, 30)]),
    )
    assert candidates(rec, tmp_path) == [(("V1", "V2"), (Rule.SAME_PLACE,))]
    rec = record(
        (claim("R1.1.a"), [stated("A", p1), code(10, 20)]),
        (claim("S1.1.a"), [stated("B", p2), code(21, 30)]),
    )
    assert candidates(rec, tmp_path) == []


def test_values_the_rules_miss_are_grouped_by_the_assistant(tmp_path):
    rec = record(
        (claim("R1.1.a"), [stated("A", v("subjects", 201))]),
        (claim("S1.1.a"), [stated("B", v("participants", 202))]),
    )
    assert candidates(rec, tmp_path) == []
    [x] = crosscheck.find(rec, answer(("V2", "V1")))
    assert x.rules == (Rule.SAME_MEANING,) and x.reason == "r"
    assert x.status is Status.DIFFERS


def test_one_claim_and_one_printed_text_are_not_compared_with_themselves(tmp_path):
    trials = v("trials", 400, "each subject")
    one_claim = record(
        (
            claim("R1.1.a"),
            [stated("A", trials), stated("B", v("trials", 410, "each subject"))],
        )
    )
    assert not crosscheck.plan_handoffs(tmp_path, one_claim)
    assert crosscheck.current(tmp_path, one_claim) == ()
    methods = stated("Methods", trials, source=Source.METHODS)
    rec = record((claim("R2.1.a"), [methods]), (claim("R3.1.a"), [methods]))
    [h] = crosscheck.plan_handoffs(tmp_path, rec)
    assert h.rows[1].same_text == "V1" and not h.candidates
    [problem] = crosscheck.check_answer(answer(("V1", "V2")), h)
    assert problem.kind == "nothing-to-compare"


def test_values_joined_through_others_make_one_candidate(tmp_path):
    rec = record(
        (claim("R1.1.a"), [stated("A", v("N", 20, "group B"))]),
        (claim("R2.1.a"), [stated("B", v("N", 20, "group B"))]),
        (claim("R3.1.a"), [stated("C", v("N", 21, "group B"))]),
    )
    assert candidates(rec, tmp_path) == [(("V1", "V2", "V3"), (Rule.SAME_LABEL,))]
    # the assistant splits it: one value is of another condition
    [x] = crosscheck.find(rec, answer(("V1", "V2")))
    assert x.claim_ids == ("R1.1.a", "R2.1.a")
    assert x.status is Status.CONSISTENT


def test_an_answer_is_checked(tmp_path):
    rec = record(
        (claim("R1.1.a"), [stated("A", v("N", 20, "group B"))]),
        (claim("R2.1.a"), [stated("B", v("N", 21, "group B"))]),
        (claim("R3.1.a"), [stated("C", v("rate", 2))]),
    )
    [h] = crosscheck.plan_handoffs(tmp_path, rec)
    kinds = [p.kind for p in crosscheck.check_answer(answer(), h)]
    assert kinds == ["candidate-unanswered"]
    assert not crosscheck.check_answer(answer(set_aside=("C1",)), h)
    bad = answer(("V1", "V9"), ("V1", "V3"), set_aside=("C7",))
    kinds = [p.kind for p in crosscheck.check_answer(bad, h)]
    assert kinds == ["unknown-value", "value-twice", "unknown-candidate"]


def test_an_answer_is_used_only_for_the_values_it_was_given(tmp_path):
    def rec(n):
        return record(
            (claim("R1.1.a"), [stated("A", v("N", 20, "group B"))]),
            (claim("R2.1.a"), [stated("B", v("N", n, "group B"))]),
        )

    assert crosscheck.write(tmp_path, rec(21)) is None
    assert "not done" in crosscheck.describe(None)
    crosscheck.write_handoffs(tmp_path, rec(21))
    reply = json.dumps({"instructions": "crosscheck v1",
        "groups": [{"values": ["V1", "V2"], "reason": "N of group B."}]})  # fmt: skip
    saved, problems = crosscheck.import_answer(tmp_path, reply, "T")
    assert saved is not None and not problems
    assert not crosscheck.plan_handoffs(tmp_path, rec(21))
    found = crosscheck.write(tmp_path, rec(21))
    saved = crosscheck.CrossCheck.model_validate_json(
        (tmp_path / crosscheck.FINDINGS).read_text(encoding="utf-8")
    )
    assert saved.findings == found and found[0].status is Status.DIFFERS
    # the record changed: the answer is not used, and the step is handed off again
    assert crosscheck.write(tmp_path, rec(22)) is None
    assert not (tmp_path / crosscheck.FINDINGS).exists()
    assert crosscheck.write_handoffs(tmp_path, rec(22))
    assert crosscheck.pending_handoffs(tmp_path)


def test_how_two_printed_values_agree():
    assert agree(v("p", 0.05, relation=Relation.LT), v("p", 0.03))
    assert not agree(v("p", 0.05, relation=Relation.LT), v("p", 0.07))
    assert agree(
        v("p", 0.05, relation=Relation.LT), v("p", 0.001, relation=Relation.LT)
    )
    assert not agree(
        v("p", 0.1, relation=Relation.GT), v("p", 0.05, relation=Relation.LT)
    )
    assert agree(v("p", 0.05, relation=Relation.GE), v("p", 0.05, relation=Relation.LE))
    assert agree(v("rt", 140, relation=Relation.APPROX), v("rt", 140.4, decimals=1))
    # a value printed as approximate agrees within 10% of it
    assert agree(v("n", 50, relation=Relation.APPROX), v("n", 52))
    assert agree(v("n", 52), v("n", 50, relation=Relation.APPROX))
    assert not agree(v("n", 50, relation=Relation.APPROX), v("n", 60))
    assert not agree(v("rate", 2), v("rate", 5))
    assert agree(v("coding", "left"), v("coding", "left"))
    assert not agree(v("coding", "left"), v("coding", "Left"))
