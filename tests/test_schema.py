# Copyright (c) 2026, Joshua I. Gold
# SPDX-License-Identifier: BSD-2-Clause

import datetime

import pytest
from conftest import DRAFTER
from pydantic import ValidationError

from miragold.schema import (
    AuditRecord,
    Basis,
    Claim,
    ClaimType,
    CodeAnchor,
    Comparison,
    DataAnchor,
    Derivation,
    Drafter,
    DrafterKind,
    Effect,
    Facet,
    Finding,
    Kind,
    ManuscriptAnchor,
    Observation,
    Obtained,
    Relation,
    Source,
    Status,
    Trace,
    Value,
)

CLAIM_TEXT = "Accuracy increased with stimulus strength (β = 0.42, p < .001; Fig. 2a)"


def ms_anchor(quote: str = CLAIM_TEXT, section: str = "Results") -> ManuscriptAnchor:
    return ManuscriptAnchor(
        file="manuscript.pdf",
        section=section,
        paragraph=3,
        char_start=0,
        char_end=len(quote),
        quote=quote,
    )


def code_anchor() -> CodeAnchor:
    return CodeAnchor(
        file="analysis/fit_glm.m",
        line_start=41,
        line_end=41,
        quote="data = data(data.rt < 2, :);",
    )


def methods_obs() -> Observation:
    return Observation(
        source=Source.METHODS,
        statement="All trials are included.",
        anchor=ms_anchor("All trials were analyzed.", section="Methods"),
        obtained=Obtained.QUOTED,
    )


def code_obs() -> Observation:
    return Observation(
        source=Source.CODE,
        statement="Trials with RT of 2 s or more are excluded.",
        anchor=code_anchor(),
        obtained=Obtained.READ,
    )


def claim(**kwargs) -> Claim:
    return Claim(
        **{"id": "R2.3.b", "type": ClaimType.NEW_RESULT, "anchor": ms_anchor()} | kwargs
    )


def differs_finding(**kwargs) -> Finding:
    return Finding(
        **{
            "id": "R2.3.b/condition/rt",
            "claim_id": "R2.3.b",
            "facet": Facet.CONDITION,
            "status": Status.DIFFERS,
            "basis": Basis.EXACT,
            "summary": "Methods states all trials are included. "
            "The code excludes trials with RT ≥ 2 s.",
            "observations": (methods_obs(), code_obs()),
            "effect": Effect.INDIRECT,
        }
        | kwargs
    )


def test_record_round_trips_through_json():
    record = AuditRecord(
        drafted_by=DRAFTER,
        claims=(claim(trace=Trace.TRACED),),
        findings=(differs_finding(),),
    )
    assert AuditRecord.model_validate_json(record.model_dump_json()) == record


@pytest.mark.parametrize("path", ["/Users/x/paper.pdf", "../paper.pdf", ""])
def test_anchor_paths_must_stay_inside_materials(path):
    with pytest.raises(ValidationError):
        CodeAnchor(file=path, line_start=1, line_end=1, quote="x = 1")


@pytest.mark.parametrize("quote", ["", "   "])
def test_anchor_requires_quoted_evidence(quote):
    with pytest.raises(ValidationError):
        DataAnchor(file="data/trials.csv", quote=quote)


def test_manuscript_span_must_be_nonempty():
    with pytest.raises(ValidationError):
        ManuscriptAnchor(
            file="m.pdf",
            section="Results",
            paragraph=1,
            char_start=5,
            char_end=5,
            quote="x",
        )


def test_code_range_must_be_ordered():
    with pytest.raises(ValidationError):
        CodeAnchor(file="a.py", line_start=10, line_end=9, quote="x")


def test_observation_anchor_must_match_source():
    with pytest.raises(ValidationError):
        Observation(
            source=Source.METHODS,
            statement="s",
            anchor=code_anchor(),
            obtained=Obtained.QUOTED,
        )


@pytest.mark.parametrize("ctype", [ClaimType.REFERENCED_RESULT, ClaimType.COMPARISON])
def test_cited_claim_types_require_citations(ctype):
    with pytest.raises(ValidationError):
        claim(type=ctype)
    assert claim(type=ctype, citations=("[12]",)).citations == ("[12]",)


def test_no_stated_support_claim_has_no_support():
    with pytest.raises(ValidationError):
        claim(type=ClaimType.NO_STATED_SUPPORT, citations=("[3]",))


def test_claim_cannot_depend_on_itself():
    with pytest.raises(ValidationError):
        claim(depends_on=("R2.3.b",))


@pytest.mark.parametrize("status", [Status.CONSISTENT, Status.DIFFERS])
def test_comparison_needs_two_sources(status):
    with pytest.raises(ValidationError):
        differs_finding(status=status, observations=(methods_obs(),))


def test_not_described_names_silent_sources():
    finding = differs_finding(
        status=Status.NOT_DESCRIBED,
        basis=None,
        observations=(code_obs(),),
        not_described_in=(Source.METHODS,),
    )
    assert finding.not_described_in == (Source.METHODS,)
    with pytest.raises(ValidationError):
        differs_finding(
            status=Status.NOT_DESCRIBED, basis=None, observations=(code_obs(),)
        )
    with pytest.raises(ValidationError):
        differs_finding(
            status=Status.NOT_DESCRIBED,
            basis=None,
            observations=(code_obs(),),
            not_described_in=(Source.CODE,),
        )


def test_not_described_in_only_for_not_described():
    with pytest.raises(ValidationError):
        differs_finding(not_described_in=(Source.DATA,))


def test_not_verifiable_requires_reason():
    kwargs = {"status": Status.NOT_VERIFIABLE, "basis": None, "observations": ()}
    with pytest.raises(ValidationError):
        differs_finding(**kwargs)
    reason = "Data for this analysis are not included in the materials provided."
    assert differs_finding(**kwargs, reason=reason).reason == reason


def test_record_rejects_duplicate_and_dangling_ids():
    with pytest.raises(ValidationError):
        AuditRecord(drafted_by=DRAFTER, claims=(claim(), claim()))
    with pytest.raises(ValidationError):
        AuditRecord(drafted_by=DRAFTER, claims=(claim(depends_on=("R9.9",)),))
    with pytest.raises(ValidationError):
        AuditRecord(drafted_by=DRAFTER, claims=(), findings=(differs_finding(),))


def test_findings_for_claim():
    other = claim(id="R2.4.a", trace=Trace.TRACED)
    record = AuditRecord(
        drafted_by=DRAFTER,
        claims=(claim(trace=Trace.TRACED), other),
        findings=(
            differs_finding(),
            differs_finding(id="R2.4.a/condition/rt", claim_id="R2.4.a"),
        ),
    )
    assert [f.claim_id for f in record.findings_for("R2.4.a")] == ["R2.4.a"]


def test_trace_matches_findings():
    with pytest.raises(ValidationError):
        AuditRecord(
            drafted_by=DRAFTER, claims=(claim(),), findings=(differs_finding(),)
        )
    with pytest.raises(ValidationError):
        AuditRecord(drafted_by=DRAFTER, claims=(claim(trace=Trace.TRACED),))


def test_via_dependencies_needs_dependencies():
    with pytest.raises(ValidationError):
        claim(type=ClaimType.INTERPRETATION, trace=Trace.VIA_DEPENDENCIES)
    base = claim(id="R2.3.a")
    interp = claim(
        type=ClaimType.INTERPRETATION,
        trace=Trace.VIA_DEPENDENCIES,
        depends_on=("R2.3.a",),
    )
    assert (
        AuditRecord(drafted_by=DRAFTER, claims=(base, interp)).claims[1].trace
        is Trace.VIA_DEPENDENCIES
    )


def test_deferred_needs_citations():
    with pytest.raises(ValidationError):
        claim(trace=Trace.DEFERRED)
    cited = claim(
        type=ClaimType.REFERENCED_RESULT, trace=Trace.DEFERRED, citations=("[4]",)
    )
    assert cited.trace is Trace.DEFERRED


def test_manuscript_page_is_positive():
    assert ms_anchor().model_copy(update={"page": 5}).page == 5
    with pytest.raises(ValidationError):
        ManuscriptAnchor(
            file="m.pdf",
            section="Results",
            paragraph=1,
            char_start=0,
            char_end=1,
            page=0,
            quote="x",
        )


def test_partial_coverage_is_split_by_scope():
    covered = differs_finding(
        id="R2.3.b/condition/bins-1-3",
        status=Status.CONSISTENT,
        scope="bins 1 and 3",
        effect=Effect.UNKNOWN,
    )
    silent = differs_finding(
        id="R2.3.b/condition/bins-2-4",
        status=Status.NOT_DESCRIBED,
        basis=None,
        scope="bins 2 and 4",
        observations=(methods_obs(),),
        not_described_in=(Source.CODE,),
        effect=Effect.NONE_OBSERVED,
    )
    record = AuditRecord(
        drafted_by=DRAFTER,
        claims=(claim(trace=Trace.TRACED),),
        findings=(covered, silent),
    )
    assert [f.scope for f in record.findings_for("R2.3.b")] == [
        "bins 1 and 3",
        "bins 2 and 4",
    ]


def test_basis_required_exactly_for_comparisons():
    with pytest.raises(ValidationError):
        differs_finding(basis=None)
    with pytest.raises(ValidationError):
        differs_finding(
            status=Status.NOT_DESCRIBED,
            observations=(code_obs(),),
            not_described_in=(Source.METHODS,),
        )


# --- Values, comparisons, computed status (decision 0007) ----------------------

DERIVATION = Derivation(
    script="derivations/durations.py", output="derivations/output/durations.json"
)


def v(value, name="mean", **kwargs) -> Value:
    return Value(name=name, value=value, **kwargs)


def obs_value(value, name="mean", **kwargs) -> Value:
    return v(value, name, key=f"{name}/{value}", **kwargs)


def stated_obs(*values: Value) -> Observation:
    return Observation(
        source=Source.METHODS,
        statement="Stated design.",
        anchor=ms_anchor("mean of 500 ms", section="Methods"),
        obtained=Obtained.QUOTED,
        values=values,
    )


def data_obs(*values: Value) -> Observation:
    return Observation(
        source=Source.DATA,
        statement="Recorded values.",
        anchor=DataAnchor(
            file="data/trials.csv", quote="see output", produced_by=DERIVATION
        ),
        obtained=Obtained.RECOMPUTED,
        values=values,
    )


def compared(kind, stated, observed, basis, **kwargs) -> Finding:
    stated = stated if isinstance(stated, tuple) else (stated,)
    observed = observed if isinstance(observed, tuple) else (observed,)
    predicted = kwargs.get("predicted")
    extra = (predicted,) if predicted is not None else ()
    return Finding(
        id="R2.3.b/condition/x",
        claim_id="R2.3.b",
        basis=basis,
        summary="Compared.",
        observations=(stated_obs(*stated), data_obs(*observed, *extra)),
        comparisons=(
            Comparison(kind=kind, stated=stated, observed=observed, **kwargs),
        ),
    )


DVR, RP = Basis.DESIGN_VS_REALIZATION, Basis.REPORTED_PRECISION
PREDICTED = obs_value(420.0, unit="ms")


@pytest.mark.parametrize(
    ("kind", "stated", "observed", "basis", "kwargs", "expected"),
    [
        # duration means against a predicted 420.0 ms
        (Kind.RELATIVE, v(500, unit="ms"), obs_value(392.6, unit="ms"), DVR,
         {"predicted": PREDICTED, "amount": 0.05}, Status.DIFFERS),
        (Kind.RELATIVE, v(500, unit="ms"), obs_value(415.3, unit="ms"), DVR,
         {"predicted": PREDICTED, "amount": 0.05}, Status.CONSISTENT),
        # switch rate: ±2 percentage points of 30%
        (Kind.ABSOLUTE, v(30, "switch", unit="%"), obs_value(33.5, "switch", unit="%"),
         DVR, {"amount": 2}, Status.DIFFERS),
        (Kind.ABSOLUTE, v(30, "switch", unit="%"), obs_value(30.4, "switch", unit="%"),
         DVR, {"amount": 2}, Status.CONSISTENT),
        # SEM at reported precision; the rounding boundary counts as agreeing
        (Kind.PRECISION, v(4.12, "SEM", decimals=2), obs_value(4.57, "SEM"), RP, {},
         Status.DIFFERS),
        (Kind.PRECISION, v(4.12, "SEM", decimals=2), obs_value(4.115, "SEM"), RP, {},
         Status.CONSISTENT),
        (Kind.INEQUALITY, v(0.001, "p", relation=Relation.LT), obs_value(1.56e-10, "p"),
         RP, {}, Status.CONSISTENT),
        (Kind.INEQUALITY, v(0.001, "p", relation=Relation.LT), obs_value(0.002, "p"),
         RP, {}, Status.DIFFERS),
        # hedged "~80" within ±10%
        (Kind.RELATIVE, v(80, relation=Relation.APPROX), obs_value(83.0), RP,
         {"amount": 0.10, "hedge": "~80"}, Status.CONSISTENT),
        (Kind.RANGE, (v(200, "min"), v(1500, "max")),
         (obs_value(200.5, "min"), obs_value(1499.9, "max")), DVR, {}, Status.CONSISTENT),
        (Kind.RANGE, (v(200, "min"), v(1500, "max")),
         (obs_value(200.5, "min"), obs_value(1500.4, "max")), DVR, {}, Status.DIFFERS),
        (Kind.SIGN, v(1, "rho"), obs_value(-0.31, "rho"), Basis.DIRECTION, {},
         Status.DIFFERS),
        (Kind.SIGN, v(1, "rho"), obs_value(0, "rho"), Basis.DIRECTION, {},
         Status.DIFFERS),
        (Kind.EXACT, v(41, "sessions"), obs_value(40, "sessions"), Basis.EXACT, {},
         Status.DIFFERS),
        (Kind.EXACT, v("ABDR", "prefix"), obs_value("ABDR", "prefix"), Basis.EXACT, {},
         Status.CONSISTENT),
    ],
)  # fmt: skip
def test_status_is_computed(kind, stated, observed, basis, kwargs, expected):
    assert compared(kind, stated, observed, basis, **kwargs).status is expected


def test_given_status_must_match_computed():
    args = (Kind.EXACT, v(41, "sessions"), obs_value(40, "sessions"), Basis.EXACT)
    finding = compared(*args)
    assert finding.status is Status.DIFFERS
    data = finding.model_dump() | {"status": Status.CONSISTENT}
    with pytest.raises(ValidationError, match="contradicts the comparisons"):
        Finding.model_validate(data)
    assert Finding.model_validate(finding.model_dump()) == finding


def test_record_with_comparisons_round_trips_through_json():
    finding = compared(
        Kind.RELATIVE,
        v(500, unit="ms"),
        obs_value(392.6, unit="ms"),
        DVR,
        predicted=PREDICTED,
        amount=0.05,
    )
    record = AuditRecord(
        drafted_by=DRAFTER, claims=(claim(trace=Trace.TRACED),), findings=(finding,)
    )
    assert AuditRecord.model_validate_json(record.model_dump_json()) == record


def test_tolerance_text_is_generated():
    relative = compared(
        Kind.RELATIVE,
        v(500, unit="ms"),
        obs_value(392.6, unit="ms"),
        DVR,
        predicted=PREDICTED,
        amount=0.05,
    )
    assert relative.tolerance_text == (
        "±5% of the predicted mean 420.0 ms (399.0–441.0 ms)"
    )
    absolute = compared(
        Kind.ABSOLUTE,
        v(30, "switch", unit="%"),
        obs_value(30.4, "switch", unit="%"),
        DVR,
        amount=2,
    )
    assert absolute.tolerance_text == "±2 percentage points of 30% (28–32%)"
    hedged = compared(
        Kind.RELATIVE,
        v(80, relation=Relation.APPROX, unit="ms"),
        obs_value(83.0, unit="ms"),
        RP,
        amount=0.1,
        hedge="~80",
    )
    assert hedged.tolerance_text == "hedged “~80”: ±10% of 80 ms (72–88 ms)"
    # A derived prediction prints one place beyond the stated value, and a
    # name that already says "predicted" is not repeated
    derived = compared(
        Kind.RELATIVE,
        v(500, unit="ms"),
        obs_value(392.6, unit="ms"),
        DVR,
        predicted=obs_value(420.0438, "predicted mean", unit="ms"),
        amount=0.05,
    )
    assert derived.tolerance_text == (
        "±5% of the predicted mean 420.0 ms (399.0–441.0 ms)"
    )


def test_wording_read_as_an_inequality():
    finding = compared(
        Kind.INEQUALITY,
        v(0.05, "p", relation=Relation.GE),
        obs_value(0.38, "p"),
        Basis.DIRECTION,
        hedge="neither term reliably predominating",
    )
    assert finding.tolerance_text == (
        "“neither term reliably predominating” read as p ≥ 0.05"
    )


def test_a_span_agrees_if_any_value_in_it_agrees():
    stated = Value(name="p", value=0.052, decimals=3)
    worked = Value(name="p", value=0.0486)
    span = (
        Value(name="p, lowest", value=0.044),
        Value(name="p, highest", value=0.0537),
    )
    c = Comparison(kind=Kind.PRECISION, stated=(stated,), observed=(worked,), span=span)
    assert c.agrees()
    assert not c.model_copy(update={"span": None}).agrees()
    assert "allowing for rounding" in c.describe()
    below = Value(name="p", value=0.05, relation=Relation.LT)
    assert Comparison(
        kind=Kind.INEQUALITY, stated=(below,), observed=(worked,), span=span
    ).agrees()
    above = Value(name="p", value=0.0539, relation=Relation.GT)
    assert not Comparison(
        kind=Kind.INEQUALITY, stated=(above,), observed=(worked,), span=span
    ).agrees()
    with pytest.raises(ValidationError, match="around the observed value"):
        Comparison(
            kind=Kind.PRECISION, stated=(stated,), observed=(worked,), span=span[::-1]
        )


def test_a_value_is_shown_as_printed():
    assert v(0.1, "SD", decimals=2).printed() == "0.10"
    assert v(75, "accuracy", unit="%").printed() == "75%"
    assert v(0.05, "p", relation=Relation.LT).printed() == "< 0.05"
    stated = v(0.2, "SD", subject="block A", decimals=2)
    c = Comparison(kind=Kind.PRECISION, stated=(stated,), observed=(v(0.23612, "SD"),))
    assert not c.agrees()
    assert c.values_text() == "SD (for block A) 0.20 vs 0.2361"


def test_a_value_computed_from_the_text_is_compared_with_the_text():
    anchor = ManuscriptAnchor(
        file="paper.pdf", section="Results", paragraph=1, char_start=0, char_end=5,
        quote="p = 0.047",
    )  # fmt: skip
    stated = Value(name="p", value=0.047, decimals=3)
    worked = Value(name="p", value=0.0474)
    quoted = Observation(
        source=Source.RESULTS, statement="p = 0.047.", anchor=anchor,
        obtained=Obtained.QUOTED, values=(stated,),
    )  # fmt: skip
    computed = quoted.model_copy(
        update={"obtained": Obtained.COMPUTED, "values": (worked,)}
    )
    finding = Finding(
        id="R1.1.a/quantity/p", claim_id="R1.1.a", facet=Facet.QUANTITY,
        basis=RP, summary="p as printed and worked out.",
        observations=(quoted, computed),
        comparisons=(Comparison(kind=Kind.PRECISION, stated=(stated,), observed=(worked,)),),
    )  # fmt: skip
    assert finding.status is Status.CONSISTENT
    with pytest.raises(ValidationError, match="at least two sources"):
        Finding.model_validate(
            {**finding.model_dump(), "observations": (quoted, quoted), "status": None}
        )


def test_exact_and_repeated_tolerances_print_once():
    exact = compared(Kind.EXACT, v(76, "n"), obs_value(75, "n"), Basis.EXACT)
    assert exact.tolerance_text is None


def test_numeric_bases_require_comparisons():
    for basis in (DVR, RP, Basis.DIRECTION):
        with pytest.raises(ValidationError, match="as comparisons"):
            differs_finding(basis=basis)
    assert differs_finding(basis=Basis.EXACT).tolerance_text is None


def test_tolerance_text_cannot_be_set_with_comparisons():
    finding = compared(Kind.EXACT, v(76, "n"), obs_value(75, "n"), Basis.EXACT)
    with pytest.raises(ValidationError, match="generated from the comparisons"):
        Finding.model_validate(finding.model_dump() | {"tolerance": "exact"})


def test_kind_must_fit_basis():
    with pytest.raises(ValidationError, match="does not fit basis"):
        compared(Kind.SIGN, v(1, "rho"), obs_value(0.3, "rho"), DVR)
    majority = compared(
        Kind.INEQUALITY,
        v(0.5, "share", relation=Relation.GT),
        obs_value(0.67, "share"),
        Basis.DIRECTION,
    )
    assert majority.status is Status.CONSISTENT


def test_compared_values_must_appear_in_observations():
    finding = compared(Kind.EXACT, v(76, "n"), obs_value(75, "n"), Basis.EXACT)
    other = Comparison(
        kind=Kind.EXACT, stated=(v(80, "n"),), observed=(obs_value(75, "n"),)
    )
    with pytest.raises(ValidationError, match="stated values must appear"):
        Finding.model_validate(finding.model_dump() | {"comparisons": (other,)})


@pytest.mark.parametrize(
    "kwargs",
    [
        {"kind": Kind.RELATIVE, "stated": (v(1),), "observed": (v(1),)},  # no amount
        {"kind": Kind.EXACT, "stated": (v(1),), "observed": (v(1),), "amount": 1.0},
        {"kind": Kind.RANGE, "stated": (v(1),), "observed": (v(1),)},  # one bound
        {"kind": Kind.RANGE, "stated": (v(2), v(1)), "observed": (v(1),)},  # unordered
        {"kind": Kind.PRECISION, "stated": (v(1.2),), "observed": (v(1.2),)},  # decimals
        {"kind": Kind.INEQUALITY, "stated": (v(0.05, "p"),), "observed": (v(0.01),)},
        {"kind": Kind.SIGN, "stated": (v(2),), "observed": (v(1),)},
        {"kind": Kind.RELATIVE, "stated": (v("a"),), "observed": (v(1),), "amount": 0.1},
        {"kind": Kind.ABSOLUTE, "stated": (v(True),), "observed": (v(1),), "amount": 1.0},
        {"kind": Kind.PRECISION, "stated": (v(1.2, decimals=1),), "observed": (v(1.2),),
         "predicted": v(1.0)},
    ],
)  # fmt: skip
def test_malformed_comparisons_rejected(kwargs):
    with pytest.raises(ValidationError):
        Comparison(**kwargs)


def test_exact_comparison_keeps_true_apart_from_one():
    def agrees(stated, observed):
        return Comparison(
            kind=Kind.EXACT, stated=(v(stated),), observed=(v(observed),)
        ).agrees()

    assert type(v(True).value) is bool and type(v(1).value) is int
    assert agrees(True, True) and agrees(1, 1.0)
    assert not agrees(True, 1) and not agrees(0, False)


def test_obtained_must_fit_source():
    with pytest.raises(ValidationError, match="obtained as"):
        Observation(
            source=Source.CODE,
            statement="s",
            anchor=code_anchor(),
            obtained=Obtained.QUOTED,
        )


def test_data_observations_name_their_derivation_and_keys():
    anchor = DataAnchor(file="data/trials.csv", quote="n = 3")
    kwargs = {"source": Source.DATA, "statement": "s", "obtained": Obtained.RECOMPUTED}
    with pytest.raises(ValidationError, match="produced_by"):
        Observation(anchor=anchor, values=(obs_value(3, "n"),), **kwargs)
    produced = anchor.model_copy(update={"produced_by": DERIVATION})
    with pytest.raises(ValidationError, match="key"):
        Observation(anchor=produced, values=(v(3, "n"),), **kwargs)
    with pytest.raises(ValidationError, match="key"):
        Observation(anchor=produced, **kwargs)  # no values
    assert Observation(anchor=produced, values=(obs_value(3, "n"),), **kwargs)


def test_derivation_paths_stay_inside_workspace():
    with pytest.raises(ValidationError):
        Derivation(script="../x.py", output="out.json")


def test_finding_ids_are_stable_and_unique():
    with pytest.raises(ValidationError, match="must start with"):
        differs_finding(id="R9.9/condition/rt")
    with pytest.raises(ValidationError, match="duplicate finding ids"):
        AuditRecord(
            drafted_by=DRAFTER,
            claims=(claim(trace=Trace.TRACED),),
            findings=(differs_finding(), differs_finding()),
        )


DAY = datetime.date(2026, 1, 2)


def test_model_drafter_names_model_and_stage():
    Drafter(
        kind=DrafterKind.MODEL,
        name="Model X",
        model_id="x-1",
        stage="segment",
        date=DAY,
    )
    with pytest.raises(ValidationError, match="model_id and stage"):
        Drafter(kind=DrafterKind.MODEL, name="Model X", date=DAY)


def test_person_drafter_has_no_model_fields():
    with pytest.raises(ValidationError, match="model drafter only"):
        Drafter(kind=DrafterKind.PERSON, name="A. Reviewer", model_id="x", date=DAY)
    with pytest.raises(ValidationError, match="a person has none"):
        Drafter(kind=DrafterKind.PERSON, name="A. Reviewer", stage="segment", date=DAY)


def test_tool_drafter_names_its_stage():
    Drafter(kind=DrafterKind.TOOL, name="miragold", stage="stats", date=DAY)
    with pytest.raises(ValidationError, match="the tool names its stage"):
        Drafter(kind=DrafterKind.TOOL, name="miragold", date=DAY)
    with pytest.raises(ValidationError, match="model drafter only"):
        Drafter(
            kind=DrafterKind.TOOL,
            name="miragold",
            stage="stats",
            model_id="x",
            date=DAY,
        )


def test_record_needs_a_drafter():
    with pytest.raises(ValidationError, match="drafted_by"):
        AuditRecord()


def test_item_drafter_overrides_the_records():
    other = Drafter(kind=DrafterKind.PERSON, name="B. Reviewer", date=DAY)
    record = AuditRecord(
        drafted_by=DRAFTER,
        claims=(claim(), claim(id="R2.3.c", drafted_by=other)),
    )
    assert [record.drafter_of(c).name for c in record.claims] == [
        "A. Reviewer",
        "B. Reviewer",
    ]


def _p(stated: Value, *observed: float, **kw) -> bool:
    seen = tuple(Value(name="p", value=x) for x in observed)
    return Comparison(kind=Kind.P, stated=(stated,), observed=seen, **kw).agrees()


def test_p_is_compared_to_three_decimal_places():
    four = Value(name="p", value=0.0473, decimals=4)
    assert _p(four, 0.0476)  # 0.047 and 0.048 are within 0.0005
    assert not _p(four, 0.0482)
    two = Value(name="p", value=0.05, decimals=2)
    assert _p(two, 0.054)  # fewer decimals shown: those decimals decide
    tiny = Value(name="p", value=1e-300)
    assert _p(tiny, 0.0004)  # any p below 0.0005 counts as 0.000
    assert not _p(tiny, 0.0006)


def test_a_p_bound_below_three_decimals_is_read_as_0_0005():
    assert _p(Value(name="p", value=1e-10, relation=Relation.LT), 1e-5)
    assert not _p(Value(name="p", value=0.001, relation=Relation.LT), 0.0012)
    assert _p(Value(name="p", value=0.05, relation=Relation.GT), 0.2)


def test_a_p_margin_widens_the_comparison_for_resampling():
    stated = Value(name="p", value=0.031, decimals=3)
    assert not _p(stated, 0.040)
    assert _p(stated, 0.040, amount=0.0175)
    c = Comparison(
        kind=Kind.P, stated=(stated,), observed=(Value(name="p", value=0.04),),
        amount=0.0175,
    )  # fmt: skip
    assert "±0.018 for resampling error" in c.describe()
