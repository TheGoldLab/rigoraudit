# Copyright (c) 2026, Joshua I. Gold
# SPDX-License-Identifier: BSD-2-Clause

import pytest
from conftest import DRAFTER

from rigoraudit.coverage import Exclusion, check, items, record_coverage, sentences
from rigoraudit.schema import AuditRecord

TEXT = (
    "Subjects were faster in block A (Figure 3D, Figure 3—figure supplement 2B; Smith et al., 2015). "
    "We recorded 212 units over 250–700 ms. "
    "Each trial had two epochs (Epoch 1 and Epoch 2)."
)
TEST_TEXT = "Tests: Wilcoxon signed-rank; the line is a linear fit ±95% CI."


def spans_of(*quotes: str) -> list[tuple[int, int]]:
    return [(TEXT.index(q), TEXT.index(q) + len(q)) for q in quotes]


def test_items_skip_references_and_keep_ranges():
    assert [(i.text, i.kind) for i in items(TEXT)] == [
        ("faster", "comparison"),
        ("212", "number"),
        ("250–700", "number"),
        ("1", "number"),
        ("2", "number"),
    ]


def test_appendices_and_plural_equations_are_references():
    text = "Fits used Equations 7 and 10 (Appendix 1; Equation 3), over 40 trials."
    assert [i.text for i in items(text)] == ["40"]


def test_statistical_tests_are_items():
    assert [i.text for i in items(TEST_TEXT)] == [
        "Wilcoxon", "signed-rank", "linear fit", "95%", "CI",
    ]  # fmt: skip


def test_sentences_do_not_split_at_et_al():
    assert len(sentences(TEXT)) == 3


def test_sentences_do_not_split_at_dotted_abbreviations():
    text = (
        "Error bars are s.e. (bootstrap). Bands are s.e.m. Across units, "
        "rates rose vs. baseline (cf. Table 1). Shading is s.d. The end."
    )
    assert [text[a:b].strip() for a, b in sentences(text)] == [
        "Error bars are s.e. (bootstrap).",
        "Bands are s.e.m. Across units, rates rose vs. baseline (cf. Table 1).",
        "Shading is s.d. The end.",
    ]


def test_lowercase_dispersion_names_are_items():
    text = "Error bars are s.e.; shading is s.d. or s.e.m., the standard error."
    assert [i.text for i in items(text)] == ["s.e.", "s.d.", "s.e.m.", "standard error"]


def test_everything_uncovered_is_reported_by_sentence():
    report = check({"P": TEXT}, {}, ())
    assert report.n_items == 5 and report.n_uncovered == 5
    assert [len(g.items) for g in report.gaps] == [1, 2, 2]


def test_claims_evidence_and_exclusions_cover_items():
    claims = {"P": spans_of("Subjects were faster in block A")}
    evidence = ["212 units"]
    excl = [Exclusion(paragraph="P", quote="(Epoch 1 and Epoch 2)", reason="Labels.")]
    report = check({"P": TEXT}, claims, evidence, excl)
    assert [i.text for g in report.gaps for i in g.items] == ["250–700"]
    assert report.unused == ()


def test_an_item_only_partly_inside_a_claim_is_uncovered():
    report = check({"P": TEXT}, {"P": spans_of("212 units over 250")}, ())
    assert "250–700" in [i.text for g in report.gaps for i in g.items]


def test_exclusions_that_no_longer_match_are_reported():
    stale = Exclusion(paragraph="P", quote="(Epoch 1 or Epoch 2)", reason="Labels.")
    report = check({"P": TEXT}, {}, (), [stale])
    assert report.unused == (stale,)


def test_exclusions_must_restate_claims_in_the_record():
    bad = Exclusion(paragraph="P", quote="212", reason="Repeats.", restates="R9.9.a")
    with pytest.raises(ValueError, match="R9.9.a"):
        record_coverage(AuditRecord(drafted_by=DRAFTER), {"P": TEXT}, {}, [bad])
