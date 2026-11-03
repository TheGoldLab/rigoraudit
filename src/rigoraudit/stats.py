# Copyright (c) 2026, Joshua I. Gold
# SPDX-License-Identifier: BSD-2-Clause
"""Check each reported test against itself and the code (decision 0015).

Decompose copies each test a claim reports, part by part
(:class:`rigoraudit.decompose.ReportedTest`). From those printed parts the
tool, not a model, works out three things and compares each with what the
text prints:

- p, from the statistic and its degrees of freedom (t, F, χ², r, z);
- N, from the degrees of freedom (t and r), when the text states N;
- the effect size, from the statistic (d, r, partial η²).

A printed statistic is rounded, so each worked-out value is given with the
lowest and highest it can be for any statistic that rounds to the printed
one; it agrees if any value in that span does (as statcheck does). A test
the tool cannot work out from the text gets a *not verifiable* finding with
the reason.

The findings are drafted by the tool (:data:`DRAFTER_NAME`), with the date
the test was copied, and :func:`test_findings` builds them afresh each time
the record is built.

:func:`traced_test_findings` does the same for each test's settings
(paired, tails, Welch, correction, resampling) and the checks of its
assumptions: the trace assistant cites where the text and the code state
each, in fixed words, and the tool sets the status (items 5, 7, 8, and 10).

:func:`derived_test_findings` compares the N and the unit of analysis that a
derivation saves for a test it recomputes with what the text states (item
6), and :func:`test_context` gives the lines a claim card shows beside each
test, with no status: the test as printed (so a claim that reports several
can name them "test 1", "test 2"), what it assumes (:func:`assumes`, item 9), and
plain facts about the values the derivation saved (:func:`data_facts`, item
11).
"""

from __future__ import annotations

import datetime
import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from scipy import stats as sp

from rigoraudit import decompose, derive, trace
from rigoraudit.decompose import Design, EffectName, Printed, ReportedTest, Statistic
from rigoraudit.paragraphs import PARAGRAPHS, Paragraph, read_paragraphs
from rigoraudit.schema import (
    Basis,
    Comparison,
    Context,
    DataAnchor,
    Derivation,
    Drafter,
    DrafterKind,
    Facet,
    Finding,
    Kind,
    ManuscriptAnchor,
    Observation,
    Obtained,
    Relation,
    Source,
    Status,
    Value,
)
from rigoraudit.settings import Settings
from rigoraudit.trace import Assumption, Setting
from rigoraudit.values import read_values

STAGE = "stats"
DRAFTER_NAME = "rigoraudit"
SYMBOL = {Statistic.CHI2: "χ²"}
EFFECT_SYMBOL = {
    EffectName.D: "d",
    EffectName.R: "r",
    EffectName.PARTIAL_ETA_SQUARED: "partial η²",
}


@dataclass(frozen=True)
class Worked:
    """A value worked out from printed numbers, with the lowest and highest
    it can be given the rounding of the printed statistic."""

    value: float
    low: float
    high: float
    note: str = ""
    """What the tool took as given, e.g. ``two-tailed``."""


def _half(p: Printed) -> float:
    return 0.5 * 10.0 ** -(p.decimals or 0)


def _ends(stat: Printed) -> tuple[float, float, float]:
    """The printed statistic's size, and the smallest and largest size that
    round to it."""
    x = abs(stat.value)
    return x, max(x - _half(stat), 0.0), x + _half(stat)


def p_value(statistic: Statistic, x: float, df: tuple[float, ...], tails: int) -> float:
    """p for a statistic of size ``x`` (not negative)."""
    match statistic:
        case Statistic.T:
            return tails * sp.t.sf(x, df[0])
        case Statistic.Z:
            return tails * sp.norm.sf(x)
        case Statistic.R:
            if x >= 1:
                return 0.0
            return tails * sp.t.sf(x * math.sqrt(df[0] / (1 - x * x)), df[0])
        case Statistic.F:
            return float(sp.f.sf(x, df[0], df[1]))
        case Statistic.CHI2:
            return float(sp.chi2.sf(x, df[0]))
    raise ValueError(statistic)


def worked_p(t: ReportedTest) -> Worked | str:
    """p worked out from the printed statistic, or why it cannot be."""
    if t.statistic not in decompose.DF_COUNT:
        return f"the tool cannot yet work out p for {_name(t)} from the text"
    df = _df(t)
    if len(df) != decompose.DF_COUNT[t.statistic]:
        return "the text does not print the degrees of freedom"
    stat = _read(t.value)
    x, low, high = _ends(stat)
    one_sided = t.statistic in (Statistic.F, Statistic.CHI2)
    tails = t.tails or 2
    note = (
        "" if one_sided or t.tails else "taken as two-tailed, as the text does not say"
    )
    return Worked(
        float(p_value(t.statistic, x, df, tails)),
        float(p_value(t.statistic, high, df, tails)),
        float(p_value(t.statistic, low, df, tails)),
        note,
    )


def implied_n(t: ReportedTest) -> int | str | None:
    """N implied by the degrees of freedom, why it cannot be worked out, or
    ``None`` for a statistic whose degrees of freedom do not give N."""
    if t.statistic not in (Statistic.T, Statistic.R):
        return None
    df = _df(t)
    if not df:
        return "the text does not print the degrees of freedom"
    if df[0] != int(df[0]):
        return (
            "the degrees of freedom are not a whole number (as with Welch's test), "
            "so they do not give N"
        )
    if t.statistic is Statistic.R or t.design is Design.INDEPENDENT:
        return int(df[0]) + 2
    if t.design in (Design.PAIRED, Design.ONE_SAMPLE):
        return int(df[0]) + 1
    return "the text does not say whether the test compares independent groups or paired values"


def worked_effect(t: ReportedTest) -> Worked | str:
    """The effect size worked out from the statistic, or why it cannot be."""
    assert t.effect is not None
    name, df = t.effect.name, _df(t)
    formula: Callable[[float], float] | None = None
    note = ""
    if name is EffectName.D and t.statistic is Statistic.T and df:
        if t.design is Design.INDEPENDENT:
            formula, note = (
                (lambda x: 2 * x / math.sqrt(df[0])),
                "assuming equal groups",
            )
        elif t.design in (Design.PAIRED, Design.ONE_SAMPLE):
            formula = lambda x: x / math.sqrt(df[0] + 1)
        else:
            return (
                "which d follows from t depends on whether the test is paired, "
                "which the text does not say"
            )
    elif name is EffectName.R and t.statistic is Statistic.T and df:
        formula = lambda x: x / math.sqrt(x * x + df[0])
    elif name is EffectName.R and t.statistic is Statistic.R:
        formula = lambda x: x
    elif (
        name is EffectName.PARTIAL_ETA_SQUARED
        and t.statistic is Statistic.F
        and len(df) == 2
    ):
        formula = lambda x: x * df[0] / (x * df[0] + df[1])
    if formula is None:
        return (
            f"the tool cannot work out the effect size {t.effect.printed!r} "
            f"from {_name(t)}"
        )
    x, low, high = _ends(_read(t.value))
    worked = Worked(formula(x), formula(low), formula(high), note)
    if _read(t.effect.printed).value < 0:  # the text gives the effect its sign
        return Worked(-worked.value, -worked.high, -worked.low, note)
    return worked


# --- Findings ----------------------------------------------------------------


def test_findings(workspace: Path, manuscript: str) -> list[Finding]:
    """The findings for every test copied by an accepted decompose answer.

    ``manuscript`` is the manuscript file, relative to ``materials/``.
    """
    paragraphs = {p.label: p for p in read_paragraphs(workspace / PARAGRAPHS)}
    where = {c.id: c.paragraph for c in decompose.to_decompose(workspace)}
    out = []
    for a in decompose.read_accepted(workspace):
        drafter = Drafter(
            kind=DrafterKind.TOOL,
            name=DRAFTER_NAME,
            stage=STAGE,
            date=datetime.date.fromisoformat(a.imported),
        )
        for c in a.answer.claims:
            for n, t in enumerate(c.tests, 1):
                part = f", test {n}" if len(c.tests) > 1 else ""
                out += claim_test_findings(
                    c.id, t, part, paragraphs[where[c.id]], manuscript, drafter
                )
    return out


def claim_test_findings(
    claim: str,
    t: ReportedTest,
    part: str,
    p: Paragraph,
    manuscript: str,
    drafter: Drafter,
) -> list[Finding]:
    """The findings for one test of one claim; ``part`` names the test when
    the claim reports several (``", test 2"``)."""

    shown = _shown(t)
    printed = Observation(
        source=Source.RESULTS,
        statement=f"The text reports {shown}.",
        anchor=_anchor(p, t.quote, manuscript),
        obtained=Obtained.QUOTED,
        values=tuple(_printed_values(t)),
    )
    n_printed = printed
    if t.n is not None and t.n_quote is not None:
        n_printed = Observation(
            source=Source.RESULTS,
            statement=f"The text states N = {t.n.strip()}.",
            anchor=_anchor(p, t.n_quote, manuscript),
            obtained=Obtained.QUOTED,
            values=(_value("N", t.n),),
        )

    def finding(
        facet: Facet, scope: str, summary: str, *observations: Observation, **kw
    ) -> Finding:
        scope += part
        return Finding(
            id=f"{claim}/{facet}/{scope.replace(' ', '-').replace(',', '')}",
            claim_id=claim,
            facet=facet,
            scope=scope,
            summary=summary,
            observations=(printed, *observations),
            drafted_by=drafter,
            **kw,
        )

    def computed(statement: str, values: list[Value]) -> Observation:
        return Observation(
            source=Source.RESULTS,
            statement=statement,
            anchor=printed.anchor,
            obtained=Obtained.COMPUTED,
            values=tuple(values),
        )

    out = []
    if t.p is not None:
        stated = _value("p", t.p)
        scope = "p from the statistic"
        result = worked_p(t)
        if isinstance(result, str):
            out.append(_unverifiable(finding, Facet.QUANTITY, scope, shown, result))
        elif stated.relation is Relation.APPROX:
            reason = "p is printed as approximate"
            out.append(_unverifiable(finding, Facet.QUANTITY, scope, shown, reason))
        else:
            values, comparison = _compare("p", stated, result)
            text = f"Worked out from {_statistic(t)}, p = {_fmt(result)}."
            out.append(
                finding(
                    Facet.QUANTITY,
                    scope,
                    f"The text prints p {t.p.strip()} with {_statistic(t)}; worked out "
                    f"from the statistic, p = {_fmt(result)}.",
                    computed(text, values),
                    basis=Basis.REPORTED_PRECISION,
                    comparisons=(comparison,),
                )
            )
    if t.n is not None and (implied := implied_n(t)) is not None:
        scope = "N from the degrees of freedom"
        if isinstance(implied, str):
            out.append(_unverifiable(finding, Facet.POPULATION, scope, shown, implied))
        else:
            stated = _value("N", t.n)
            worked_n = Value(name="N implied by df", value=implied)
            how = (
                "df + 2"
                if t.statistic is Statistic.R or t.design is Design.INDEPENDENT
                else "df + 1"
            )
            out.append(
                finding(
                    Facet.POPULATION,
                    scope,
                    f"The text states N = {t.n.strip()}; the degrees of freedom of "
                    f"{_statistic(t)} imply N = {implied} ({how}).",
                    *([n_printed] if n_printed is not printed else []),
                    computed(
                        f"N implied by the degrees of freedom: {implied} ({how}).",
                        [worked_n],
                    ),
                    basis=Basis.EXACT,
                    comparisons=(
                        Comparison(
                            kind=Kind.EXACT, stated=(stated,), observed=(worked_n,)
                        ),
                    ),
                )
            )
    if t.effect is not None:
        symbol = EFFECT_SYMBOL.get(t.effect.name, "effect size")
        scope = "effect size from the statistic"
        result = worked_effect(t)
        if isinstance(result, str):
            out.append(_unverifiable(finding, Facet.QUANTITY, scope, shown, result))
        else:
            stated = _value(symbol, t.effect.printed)
            values, comparison = _compare(symbol, stated, result)
            text = f"Worked out from {_statistic(t)}, {symbol} = {_fmt(result)}."
            out.append(
                finding(
                    Facet.QUANTITY,
                    scope,
                    f"The text prints {symbol} = {t.effect.printed.strip()}; worked out "
                    f"from {_statistic(t)}, {symbol} = {_fmt(result)}.",
                    computed(text, values),
                    basis=Basis.REPORTED_PRECISION,
                    comparisons=(comparison,),
                )
            )
    return out


def _unverifiable(
    finding, facet: Facet, scope: str, shown: str, reason: str
) -> Finding:
    return finding(
        facet,
        scope,
        f"The text reports {shown}; {reason}.",
        status=Status.NOT_VERIFIABLE,
        reason=reason[0].upper() + reason[1:] + ".",
    )


def _compare(name: str, stated: Value, w: Worked) -> tuple[list[Value], Comparison]:
    """The worked-out values, and their comparison with the stated one."""
    values = [
        Value(name=name, value=w.value),
        Value(name=f"{name}, lowest", value=w.low),
        Value(name=f"{name}, highest", value=w.high),
    ]
    kind = Kind.PRECISION if stated.relation is Relation.EQ else Kind.INEQUALITY
    comparison = Comparison(
        kind=kind, stated=(stated,), observed=(values[0],), span=(values[1], values[2])
    )
    return values, comparison


# --- Printed parts -------------------------------------------------------------


def _read(printed: str) -> Printed:
    p = decompose.read_printed(printed)
    if p is None:  # checked when the answer was accepted
        raise ValueError(f"{printed!r} is not a number")
    return p


def _value(name: str, printed: str) -> Value:
    p = _read(printed)
    return Value(name=name, value=p.value, relation=p.relation, decimals=p.decimals)


def _df(t: ReportedTest) -> tuple[float, ...]:
    return tuple(float(_read(d).value) for d in t.df)


def _printed_values(t: ReportedTest) -> list[Value]:
    symbol = SYMBOL.get(t.statistic, t.statistic.value)
    values = [_value(symbol, t.value)]
    names = ["df"] if len(t.df) == 1 else ["df1", "df2"]
    values += [_value(n, d) for n, d in zip(names, t.df, strict=False)]
    values += [_value("p", t.p)] if t.p else []
    values += [_value("N", t.n)] if t.n and not t.n_quote else []
    if t.effect:
        values.append(
            _value(EFFECT_SYMBOL.get(t.effect.name, "effect size"), t.effect.printed)
        )
    return values


def _statistic(t: ReportedTest) -> str:
    symbol = SYMBOL.get(t.statistic, t.statistic.value)
    df = f"({', '.join(d.strip() for d in t.df)})" if t.df else ""
    return f"{symbol}{df} = {t.value.strip()}"


def _shown(t: ReportedTest) -> str:
    return t.quote if not t.named else f"{t.named}, {t.quote}"


def _name(t: ReportedTest) -> str:
    return (
        f"a {t.named}"
        if t.named
        else f"a {SYMBOL.get(t.statistic, t.statistic.value)} statistic"
    )


def _fmt(w: Worked) -> str:
    text = f"{w.value:.3g} ({w.low:.3g} to {w.high:.3g} allowing for rounding)"
    return f"{text}, {w.note}" if w.note else text


# --- Settings and assumptions, from the trace (items 5, 7, 8, and 10) ----------

ASSUMES: dict[Statistic, tuple[Assumption, ...]] = {
    Statistic.T: (Assumption.NORMALITY, Assumption.EQUAL_VARIANCES),
    Statistic.F: (Assumption.NORMALITY, Assumption.EQUAL_VARIANCES),
    Statistic.R: (Assumption.NORMALITY,),
}
"""The assumptions whose checks the trace looks for, by statistic. Equal
variances is left out for a paired or one-sample test, and for a test the
code runs in Welch's version."""
SETTING_WORDS = {
    Setting.DESIGN: "whether the test is paired",
    Setting.TAILS: "the tails",
    Setting.EQUAL_VARIANCES: "equal variances (Welch's test or not)",
    Setting.CORRECTION: "the correction for multiple tests",
    Setting.RESAMPLES: "the number of resamples",
    Setting.RESAMPLED: "what is resampled",
    Setting.CI_METHOD: "the method for the confidence interval",
    Setting.SEED: "the random seed",
}
ASSUMPTION_WORDS = {
    Assumption.NORMALITY: "normality",
    Assumption.EQUAL_VARIANCES: "equal variances",
}


def traced_test_findings(workspace: Path, settings: Settings) -> list[Finding]:
    """The findings for the settings and assumption checks that accepted
    trace answers cite for each test.

    The trace assistant cites the passages and names what each says, in
    fixed words (:data:`rigoraudit.trace.SAYS`); the tool sets the status.
    A setting the Results paragraph states (paired, tails) counts as the
    text too.
    """
    paragraphs = {p.label: p for p in read_paragraphs(workspace / PARAGRAPHS)}
    where = {c.id: c.paragraph for c in decompose.to_decompose(workspace)}
    reported = {
        c.id: c.tests
        for a in decompose.read_accepted(workspace)
        for c in a.answer.claims
    }
    cite = trace.Citations(workspace, settings)
    out = []
    for a in trace.read_accepted(workspace):
        drafter = Drafter(
            kind=DrafterKind.TOOL,
            name=DRAFTER_NAME,
            stage=STAGE,
            date=datetime.date.fromisoformat(a.imported),
        )
        for c in a.answer.claims:
            tests = reported.get(c.id, ())
            for entry in c.tests:
                t = tests[entry.test - 1]
                part = f", test {entry.test}" if len(tests) > 1 else ""
                printed = Observation(
                    source=Source.RESULTS,
                    statement=f"The text reports {_shown(t)}.",
                    anchor=_anchor(
                        paragraphs[where[c.id]], t.quote, settings.manuscript
                    ),
                    obtained=Obtained.QUOTED,
                )
                out += _setting_findings(
                    c.id, t, entry, part, printed, cite, a.commit, drafter
                )
    return out


def _setting_findings(
    claim: str,
    t: ReportedTest,
    entry: trace.TestTrace,
    part: str,
    printed: Observation,
    cite: trace.Citations,
    commit: str | None,
    drafter: Drafter,
) -> list[Finding]:
    def finding(scope: str, summary: str, observations, **kw) -> Finding:
        scope += part
        return Finding(
            id=f"{claim}/{Facet.ANALYSIS}/{scope.replace(' ', '-').replace(',', '')}",
            claim_id=claim,
            facet=Facet.ANALYSIS,
            scope=scope,
            summary=summary,
            observations=tuple(observations),
            drafted_by=drafter,
            **kw,
        )

    out = []
    from_results = {
        Setting.DESIGN: t.design.value if t.design else None,
        Setting.TAILS: str(t.tails) if t.tails else None,
    }
    given = {s.setting: s for s in entry.settings}
    for setting in (x for x in Setting if x in given or from_results.get(x)):
        s = given.get(setting, trace.SettingTrace(setting=setting))
        words = SETTING_WORDS[setting]
        text: list[tuple[str, Observation]] = []
        if said := from_results.get(setting):
            text.append((said, printed))
        if s.methods is not None:
            statement = f"The Methods state {words}: {s.methods.says}."
            text.append((s.methods.says, cite.methods(s.methods, statement)))
        code = None
        if s.code is not None:
            statement = f"The code sets {words}: {s.code.says}."
            code = (s.code.says, cite.code(s.code, commit, statement))
        scope = setting.value.replace("_", " ")
        if code is None:
            said = list(dict.fromkeys(w for w, _ in text))
            out.append(
                finding(
                    scope,
                    f"The text states {words}: {' and '.join(said)}. The code for it "
                    "was not found.",
                    [o for _, o in text],
                    status=Status.NOT_VERIFIABLE,
                    reason="The code that sets this was not found in the materials.",
                )
            )
        elif not text:
            if setting is Setting.CORRECTION and code[0] == "none":
                continue  # nothing corrected, and nothing said
            out.append(
                finding(
                    scope,
                    f"The code sets {words}: {code[0]}. The text does not say.",
                    [code[1]],
                    status=Status.NOT_DESCRIBED,
                    not_described_in=(Source.METHODS, Source.RESULTS),
                )
            )
        elif "other" in {code[0], *(w for w, _ in text)}:
            out.append(
                finding(
                    scope,
                    f"The text states {words} as {', '.join(w for w, _ in text)}; the "
                    f"code as {code[0]}.",
                    [*(o for _, o in text), code[1]],
                    status=Status.NOT_VERIFIABLE,
                    reason="One of them is not among the settings the tool compares; "
                    "compare the quotes.",
                )
            )
        else:
            comparisons = []
            observations = []
            for w, o in text:
                v = _setting_value(setting, w)
                observations.append(o.model_copy(update={"values": (*o.values, v)}))
                comparisons.append(v)
            observed = _setting_value(setting, code[0])
            observations.append(code[1].model_copy(update={"values": (observed,)}))
            out.append(
                finding(
                    scope,
                    f"The text states {words}: {', '.join(w for w, _ in text)}. The "
                    f"code sets {code[0]}.",
                    observations,
                    basis=Basis.EXACT,
                    comparisons=tuple(
                        Comparison(kind=Kind.EXACT, stated=(v,), observed=(observed,))
                        for v in comparisons
                    ),
                )
            )
    welch = given.get(Setting.EQUAL_VARIANCES)
    assumes = [
        a
        for a in ASSUMES.get(t.statistic, ())
        if not (
            a is Assumption.EQUAL_VARIANCES
            and (
                t.design in (Design.PAIRED, Design.ONE_SAMPLE)
                or (welch and welch.code and welch.code.says == "not_assumed")
            )
        )
    ]
    checks = {a.assumption: a for a in entry.assumptions}
    for assumption in dict.fromkeys([*assumes, *checks]):
        a = checks.get(assumption, trace.AssumptionTrace(assumption=assumption))
        words = ASSUMPTION_WORDS[assumption]
        scope = f"{words} addressed"
        in_text = sorted({m.says for m in a.methods})
        in_code = sorted({k.says for k in a.code})
        text_obs = [
            cite.methods(m, f"The Methods address {words}: {m.says}.")
            for m in a.methods
        ]
        code_obs = [
            cite.code(k, commit, f"The code checks {words}: {k.says}.") for k in a.code
        ]
        if in_text and in_code:
            stated = Value(name=f"{words} checks", value=", ".join(in_text))
            observed = Value(name=f"{words} checks", value=", ".join(in_code))
            out.append(
                finding(
                    scope,
                    f"The Methods address {words} with {', '.join(in_text)}; the code "
                    f"with {', '.join(in_code)}.",
                    [
                        text_obs[0].model_copy(update={"values": (stated,)}),
                        *text_obs[1:],
                        code_obs[0].model_copy(update={"values": (observed,)}),
                        *code_obs[1:],
                    ],
                    basis=Basis.EXACT,
                    comparisons=(
                        Comparison(kind=Kind.EXACT, stated=(stated,), observed=(observed,)),
                    ),
                )
            )  # fmt: skip
        elif in_text:
            out.append(
                finding(
                    scope,
                    f"The Methods address {words} with {', '.join(in_text)}. The code "
                    "shows no check of it.",
                    text_obs,
                    status=Status.NOT_VERIFIABLE,
                    reason="The check may have been run outside the shared code.",
                )
            )
        elif in_code:
            out.append(
                finding(
                    scope,
                    f"The code checks {words} with {', '.join(in_code)}. The text does "
                    "not say.",
                    code_obs,
                    status=Status.NOT_DESCRIBED,
                    not_described_in=(Source.METHODS,),
                )
            )
        else:
            out.append(
                finding(
                    scope,
                    f"The test assumes {words}. Neither the Methods nor the code "
                    "address it.",
                    [printed],
                    status=Status.NOT_DESCRIBED,
                    not_described_in=(Source.METHODS, Source.CODE),
                )
            )
    return out


READINGS = {
    s.value.replace("_", " "): words for s, words in trace.SAYS.items() if words
}
"""The value names of the settings stated in fixed words, and those words.
Such a value is the trace assistant's reading of the cited code (``paired``
for ``ttest_rel``), so the code's quote need not show it."""


def _setting_value(setting: Setting, says: str) -> Value:
    name = setting.value.replace("_", " ")
    if name not in READINGS:
        return _value(name, says)
    return Value(name=name, value=says)


# --- Unit of analysis, from the derivation (item 6) ----------------------------


def derived_test_findings(workspace: Path, settings: Settings) -> list[Finding]:
    """The findings comparing the N and the unit of analysis that accepted
    derive answers save for a test with what the text states.

    N is compared when the text prints it. The unit is compared with the one
    the text states; when the text does not say, it is not described.
    """
    paragraphs = {p.label: p for p in read_paragraphs(workspace / PARAGRAPHS)}
    where = {c.id: c.paragraph for c in decompose.to_decompose(workspace)}
    reported = {
        c.id: c.tests
        for a in decompose.read_accepted(workspace)
        for c in a.answer.claims
    }
    out = []
    for a in derive.read_accepted(workspace):
        drafter = Drafter(
            kind=DrafterKind.TOOL,
            name=DRAFTER_NAME,
            stage=STAGE,
            date=datetime.date.fromisoformat(a.imported),
        )
        for c in a.answer.claims:
            if not c.tests or a.script is None:
                continue
            output = a.outputs[c.claim]
            saved = read_values(workspace / output)["values"]
            tests = reported.get(c.claim, ())
            for d in c.tests:
                t = tests[d.test - 1]
                part = f", test {d.test}" if len(tests) > 1 else ""
                out += _unit_findings(
                    c.claim,
                    t,
                    d,
                    part,
                    saved,
                    Derivation(script=a.script, output=output),
                    paragraphs[where[c.claim]],
                    workspace,
                    settings.manuscript,
                    drafter,
                )
    return out


def _unit_findings(
    claim: str,
    t: ReportedTest,
    d: derive.TestData,
    part: str,
    saved: Mapping,
    derivation: Derivation,
    p: Paragraph,
    workspace: Path,
    manuscript: str,
    drafter: Drafter,
) -> list[Finding]:
    n = Value(name="N in the data", value=saved[d.n], key=d.n)
    unit = Value(name="unit of analysis", value=saved[d.unit], key=d.unit)
    data = Observation(
        source=Source.DATA,
        statement=f"The derivation recomputes the test from {n.value} values, "
        f"one per {unit.value}.",
        anchor=DataAnchor(
            file=d.source,
            derivation=f"N and unit of analysis behind {_statistic(t)}",
            produced_by=derivation,
            quote=f"{d.n} = {n.value!r}; {d.unit} = {unit.value!r}",
        ),
        obtained=Obtained.RECOMPUTED,
        values=(n, unit),
    )

    def finding(scope: str, summary: str, *observations: Observation, **kw) -> Finding:
        scope += part
        return Finding(
            id=f"{claim}/{Facet.POPULATION}/{scope.replace(' ', '-').replace(',', '')}",
            claim_id=claim,
            facet=Facet.POPULATION,
            scope=scope,
            summary=summary,
            observations=observations,
            drafted_by=drafter,
            **kw,
        )

    out = []
    if t.n is not None:
        stated = _value("N", t.n)
        quote = t.n_quote or t.quote
        printed = Observation(
            source=Source.RESULTS,
            statement=f"The text states N = {t.n.strip()}.",
            anchor=_anchor(p, quote, manuscript),
            obtained=Obtained.QUOTED,
            values=(stated,),
        )
        out.append(
            finding(
                "N in the data",
                f"The text states N = {t.n.strip()} for {_statistic(t)}; the "
                f"derivation recomputes it from {n.value} values.",
                printed,
                data,
                basis=Basis.EXACT,
                comparisons=(Comparison(kind=Kind.EXACT, stated=(stated,), observed=(n,)),),
            )
        )  # fmt: skip
    scope = "unit of analysis"
    if d.stated_unit is None:
        out.append(
            finding(
                scope,
                f"The derivation recomputes {_statistic(t)} with one value per "
                f"{unit.value}. The text does not say what one value is.",
                data,
                status=Status.NOT_DESCRIBED,
                not_described_in=(Source.METHODS, Source.RESULTS),
            )
        )
        return out
    says = d.stated_unit.says
    where = derive.unit_paragraph(workspace, p.label, d.stated_unit.quote)
    assert where is not None  # checked when the answer was accepted
    text = Observation(
        source=Source.RESULTS if where.label == p.label else Source.METHODS,
        statement=f"The text states one value per {says}.",
        anchor=_anchor(where, d.stated_unit.quote, manuscript),
        obtained=Obtained.QUOTED,
    )
    if "other" in (says, unit.value):
        out.append(
            finding(
                scope,
                f"The text states one value per {says}; the derivation uses one "
                f"per {unit.value}.",
                text,
                data,
                status=Status.NOT_VERIFIABLE,
                reason="One of them is not among the units the tool compares; "
                "compare the quotes.",
            )
        )
        return out
    stated_unit = Value(name="unit of analysis", value=says)
    out.append(
        finding(
            scope,
            f"The text states one value per {says} for {_statistic(t)}; the "
            f"derivation uses one per {unit.value}.",
            text.model_copy(update={"values": (stated_unit,)}),
            data,
            basis=Basis.EXACT,
            comparisons=(
                Comparison(kind=Kind.EXACT, stated=(stated_unit,), observed=(unit,)),
            ),
        )
    )
    return out


def _anchor(p: Paragraph, quote: str, manuscript: str) -> ManuscriptAnchor:
    start, quote = p.locate(quote)
    return ManuscriptAnchor(
        file=manuscript,
        section=p.section,
        paragraph=p.number,
        char_start=start,
        char_end=start + len(quote),
        page=p.page_at(start),
        quote=quote,
    )


# --- Context: assumptions and the data (items 9 and 11) -------------------------

RANK_WORDS = ("spearman", "kendall", "rank", "mann", "wilcoxon")


def assumes(t: ReportedTest) -> str | None:
    """What the test assumes, in one line, or ``None`` for a test the
    table does not hold."""
    rank = any(w in (t.named or "").lower() for w in RANK_WORDS)
    match t.statistic:
        case Statistic.T if t.design is Design.PAIRED:
            return "Assumes independent pairs and roughly normal differences."
        case Statistic.T if t.design is Design.ONE_SAMPLE:
            return "Assumes independent observations and a roughly normal mean."
        case Statistic.T if t.design is Design.INDEPENDENT:
            return (
                "Assumes independent observations, roughly normal group means, and, "
                "unless Welch's version is used, equal variances."
            )
        case Statistic.T:
            return (
                "Assumes independent observations and roughly normal means; for "
                "independent groups, also equal variances unless Welch's version is "
                "used."
            )
        case Statistic.F:
            return (
                "Assumes independent observations, roughly normal residuals, and equal "
                "variances across groups (for repeated measures, sphericity)."
            )
        case Statistic.CHI2:
            return (
                "Assumes independent observations, each counted once, and expected "
                "counts of about 5 or more in most cells."
            )
        case Statistic.R if rank:
            return "Assumes independent pairs and a relation that only rises or only falls."
        case Statistic.R:
            return (
                "Assumes independent pairs and a straight-line relation; its p also "
                "assumes roughly normal values."
            )
        case Statistic.Z:
            return (
                "Assumes independent observations and a standard error that is known "
                "or estimated from a large sample."
            )
        case Statistic.U:
            return (
                "Assumes independent observations and, to compare medians, groups of "
                "the same shape."
            )
        case Statistic.W:
            return (
                "Assumes independent pairs and differences spread evenly about their "
                "median."
            )
    return None


def data_facts(
    groups: Mapping[str, Sequence[float]],
    rank: bool = False,
    bounds: tuple[float, float] | None = None,
) -> str:
    """Plain facts about the values behind a test: N and skew in each group,
    the ratio of the largest variance to the smallest, and, for a rank test
    (``rank``), the share of tied values; with ``bounds``, the share at the
    floor and at the ceiling."""
    arrays = {g: np.asarray(xs, dtype=float) for g, xs in groups.items()}
    parts = []
    for g, x in arrays.items():
        part = f"{g}, N = {x.size}" if g else f"N = {x.size}"
        if x.size >= 3 and np.ptp(x) > 0:
            part += f", skew {_g(float(sp.skew(x)))}"
        parts.append(part)
    variances = [float(np.var(x, ddof=1)) for x in arrays.values() if x.size > 1]
    if len(variances) > 1 and min(variances) > 0:
        parts.append(
            f"variance ratio {_g(max(variances) / min(variances))} (largest to smallest)"
        )
    pooled = np.concatenate(list(arrays.values()))
    if rank:
        _, inverse, counts = np.unique(pooled, return_inverse=True, return_counts=True)
        parts.append(f"tied values {_pct(np.mean(counts[inverse] > 1))}")
    if bounds is not None:
        parts.append(
            f"at the floor {_pct(np.mean(pooled <= bounds[0]))}, at the ceiling "
            f"{_pct(np.mean(pooled >= bounds[1]))}"
        )
    return "Data: " + "; ".join(parts) + "."


def test_context(workspace: Path) -> list[Context]:
    """The lines each claim card shows beside each copied test: the test as
    printed, what it assumes, and the facts about the values a derivation
    saved for it. Every test of a claim that reports several has an entry,
    so the card can say which is "test 1" and which "test 2"."""
    derived = {}
    for a in derive.read_accepted(workspace):
        for c in a.answer.claims:
            for d in c.tests:
                if d.groups is not None and c.claim in a.outputs:
                    derived[c.claim, d.test] = (a.outputs[c.claim], d)
    out = []
    for a in decompose.read_accepted(workspace):
        for c in a.answer.claims:
            for n, t in enumerate(c.tests, 1):
                data = None
                if (c.id, n) in derived:
                    output, d = derived[c.id, n]
                    saved = read_values(workspace / output)["values"]
                    rank = t.statistic in (Statistic.U, Statistic.W) or any(
                        w in (t.named or "").lower() for w in RANK_WORDS
                    )
                    data = data_facts(
                        derive.group_values(saved, d.groups), rank, d.bounds
                    )
                line = assumes(t)
                if line or data or len(c.tests) > 1:
                    out.append(
                        Context(
                            claim_id=c.id,
                            scope=f"test {n}" if len(c.tests) > 1 else None,
                            test=_shown(t),
                            assumes=line,
                            data=data,
                        )
                    )
    return out


def _g(x: float) -> str:
    return f"{x if abs(x) >= 0.005 else 0.0:.2g}"  # no "-1e-17" for a skew of 0


def _pct(share: float) -> str:
    return f"{100 * share:.0f}%"
