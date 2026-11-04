# Copyright (c) 2026, Joshua I. Gold
# SPDX-License-Identifier: BSD-2-Clause

import hashlib
import subprocess

import pytest
from conftest import DRAFTER

from miragold import stats
from miragold.schema import (
    AuditRecord,
    Basis,
    Claim,
    ClaimType,
    CodeAnchor,
    DataAnchor,
    Finding,
    ManuscriptAnchor,
    Observation,
    Obtained,
    Source,
    Status,
    Trace,
    Value,
)
from miragold.values import write_values
from miragold.verify import (
    ManuscriptText,
    Outcome,
    check_code_anchor,
    check_data_anchor,
    check_manuscript_anchor,
    check_record,
    shown_in,
    unsupported_numbers,
)

PAGES = [
    "Title page\nTiming and rule- based\nchoice",
    (
        "We recorded from 212 single units in two subjects. Accuracy\n"
        "increased with stimulus strength (p < 0.001)."
    ),
    "Evidence accumu-\nlation was slower in block B; perfor -\nmance dropped. Cohen’s d = −0.12; p = 0.35",
]
PARAGRAPH = "We recorded from 212 single units in two subjects."


def ms(quote: str, page: int | None = 2, start: int = 0) -> ManuscriptAnchor:
    return ManuscriptAnchor(
        file="manuscript/paper.pdf",
        section="Results",
        paragraph=1,
        char_start=start,
        char_end=start + len(quote),
        page=page,
        quote=quote,
    )


@pytest.fixture
def text() -> ManuscriptText:
    return ManuscriptText(PAGES)


# --- Manuscript -----------------------------------------------------------------


def test_quote_across_line_break_verifies(text):
    outcome, detail = check_manuscript_anchor(
        ms("Accuracy increased with stimulus strength"), text
    )
    assert outcome is Outcome.VERIFIED
    assert "page 2" in detail


def test_hyphenation_and_unicode_need_normalization(text):
    for quote in (
        "Evidence accumulation was slower",
        "performance dropped",
        "Cohen's d = -0.12",
    ):
        outcome, _ = check_manuscript_anchor(ms(quote, page=3), text)
        assert outcome is Outcome.VERIFIED_NORMALIZED


def test_accents_compare_wherever_the_text_puts_them():
    # the text layer puts the combining tilde before its letter
    text = ManuscriptText(["the residual ̃X(t) and ̃Y; about ~50 ms"])
    for quote in ("the residual X~(t) and Y~", "the residual X̃(t) and Ỹ"):
        assert check_manuscript_anchor(ms(quote, page=1), text)[0] is (
            Outcome.VERIFIED_NORMALIZED
        )
    # a tilde before a number means "about" and still counts
    assert check_manuscript_anchor(ms("about 50 ms", page=1), text)[0] is (
        Outcome.MISMATCH
    )


def test_normalization_keeps_signs_and_ranges():
    text = ManuscriptText(["Cohen’s d = −0.12; durations 200– 1500 ms"])
    assert check_manuscript_anchor(ms("d = -0.12", page=1), text)[0] is (
        Outcome.VERIFIED_NORMALIZED
    )
    for changed in ("d = 0.12", "durations 2001500 ms"):
        assert check_manuscript_anchor(ms(changed, page=1), text)[0] is (
            Outcome.MISMATCH
        )
    assert check_manuscript_anchor(ms("200-1500 ms", page=1), text)[0] is (
        Outcome.VERIFIED_NORMALIZED
    )


def test_wrong_page(text):
    outcome, detail = check_manuscript_anchor(ms("212 single units", page=3), text)
    assert outcome is Outcome.WRONG_PAGE
    assert "states page 3" in detail


def test_changed_value_is_mismatch_and_says_where(text):
    outcome, detail = check_manuscript_anchor(ms("recorded from 213 single"), text)
    assert outcome is Outcome.MISMATCH
    assert "'recordedfrom21'" in detail and "'3single'" in detail


def test_span_checked_against_paragraph(text):
    paragraphs = {("Results", 1): PARAGRAPH}
    good = ms("212 single units", start=PARAGRAPH.index("212"))
    assert check_manuscript_anchor(good, text, paragraphs)[0] is Outcome.VERIFIED
    shifted = ms("212 single units", start=PARAGRAPH.index("212") + 1)
    assert check_manuscript_anchor(shifted, text, paragraphs)[0] is Outcome.MISMATCH


def test_quote_from_a_wrong_paragraph_points_at_it(text):
    # the paragraph has a figure label run into its sentence; the page does not
    paragraph = "We recorded from 212 single Figure 3 units in two subjects."
    anchor = ms("212 single Figure 3 units", start=paragraph.index("212"))
    outcome, detail = check_manuscript_anchor(anchor, text, {("Results", 1): paragraph})
    assert outcome is Outcome.MISMATCH
    assert "compare it with page 2" in detail
    # a quote that is not the paragraph's text gets no such note
    outcome, detail = check_manuscript_anchor(ms("recorded from 213 single"), text)
    assert outcome is Outcome.MISMATCH and "paragraph" not in detail


def test_a_mismatch_names_characters_only_one_side_has(text):
    _, detail = check_manuscript_anchor(ms("Cohen’s d = 0.12; p = 0.35", page=3), text)
    assert "the page has '-' here, which the quote leaves out" in detail
    _, detail = check_manuscript_anchor(ms("We recorded from ~212 single units"), text)
    assert "the quote has '~' here, which the page does not" in detail


def test_repeated_quote_checked_on_stated_page():
    # Exact on page 1; only hyphenated on the stated page 2.
    text = ManuscriptText(
        ["a 50% probability of an additional change", "an addi- tional change here"]
    )
    outcome, detail = check_manuscript_anchor(ms("an additional change", page=2), text)
    assert outcome is Outcome.VERIFIED_NORMALIZED
    assert detail == "found after normalizing on page 1, 2"


def test_a_supplements_pages_are_named_by_its_file():
    text = ManuscriptText(
        ["The article ends with this line", "of the legend, then more.", "The legend"],
        ["", "figures.pdf", "figures.pdf"],
    )
    assert text.names([3, 1, 2]) == "page 1; page 1, 2 of figures.pdf"
    outcome, detail = check_manuscript_anchor(ms("The legend", page=1), text)
    assert outcome is Outcome.WRONG_PAGE
    assert detail == "anchor states page 1; found on page 2 of figures.pdf"
    # a quote is not split across the end of one file and the start of the next
    assert text.find_split("ends with this line of the legend") == []


def test_quote_split_by_page_furniture():
    text = ManuscriptText(
        [
            "Responses were baseline corrected using responses",
            "Research article Neuroscience 17 of 22\nfrom the 100 ms window before onset.",
        ]
    )
    quote = "baseline corrected using responses from the 100 ms window"
    outcome, detail = check_manuscript_anchor(ms(quote, page=1), text)
    assert outcome is Outcome.VERIFIED_NORMALIZED
    assert "page break" in detail
    assert check_manuscript_anchor(ms(quote, page=2), text)[0] is Outcome.WRONG_PAGE


def test_quote_split_by_a_figure_page():
    text = ManuscriptText(
        [
            "Licking rates rose with",
            "Figure 4. Licking rates. (a) Mean rates by session.",
            "reward size in every session.",
            "Methods follow.",
        ]
    )
    quote = "Licking rates rose with reward size in every session"
    outcome, detail = check_manuscript_anchor(ms(quote, page=1), text)
    assert outcome is Outcome.VERIFIED_NORMALIZED
    assert "page break" in detail
    # two pages between the parts are too many
    text = ManuscriptText(
        [
            "Licking rates rose with",
            "Figure 4.",
            "Figure 5.",
            "reward size in every session.",
        ]
    )
    assert text.find_split(quote) == []


def test_quote_around_an_equation():
    text = ManuscriptText(
        [
            "The rate follows the rule\n y = a + b x (1)\nwhere a is the start,",
            "and the slope is b. Far away, where a is the start, again.",
        ]
    )
    quote = "follows the rule [Equation 1] where a is the start"
    outcome, detail = check_manuscript_anchor(ms(quote, page=1), text)
    assert outcome is Outcome.VERIFIED
    assert detail == "found on page 1; the equations it marks are not compared"
    # the parts must come in order, and close together
    assert (
        text.find("where a is the start [Equation] follows the rule", loose=True) == []
    )
    far = ManuscriptText([f"follows the rule {'x ' * 4000} where a is the start"])
    assert far.find(quote, loose=True) == []
    assert text.find("[Equation 1]", loose=True) == []


def test_image_text_is_unchecked_not_mismatched(text):
    anchor = ms("Cohen's d = 0.35; p < 0.001", page=4).model_copy(
        update={"section": "Figure 2C (text in panel)"}
    )
    assert check_manuscript_anchor(anchor, text)[0] is Outcome.MISMATCH
    outcome, _ = check_manuscript_anchor(
        anchor, text, image_sections={"Figure 2C (text in panel)"}
    )
    assert outcome is Outcome.UNCHECKED


def test_missing_page_is_noted(text):
    outcome, detail = check_manuscript_anchor(ms("212 single", page=None), text)
    assert outcome is Outcome.VERIFIED
    assert "no page" in detail


# --- Code -----------------------------------------------------------------------


def git(repo, *args):
    return subprocess.run(
        ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", *args],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


@pytest.fixture
def materials(tmp_path):
    repo = tmp_path / "code"
    repo.mkdir()
    git(repo, "init", "-q")
    (repo / "fit.m").write_text(
        "x = 1;\ndata = data(data.rt < 2, :);\ny = 3;\n", encoding="utf-8"
    )
    git(repo, "add", "fit.m")
    git(repo, "commit", "-qm", "init")
    return tmp_path


def code(materials, quote, start=2, end=2, commit="HEAD"):
    sha = git(materials / "code", "rev-parse", commit) if commit else None
    return CodeAnchor(
        file="code/fit.m", line_start=start, line_end=end, commit=sha, quote=quote
    )


def test_code_matches_commit(materials):
    anchor = code(materials, "data = data(data.rt < 2, :);")
    assert check_code_anchor(anchor, materials) == (
        Outcome.VERIFIED,
        f"matches commit {anchor.commit}",
    )


def test_code_checked_at_commit_not_working_tree(materials):
    anchor = code(materials, "data = data(data.rt < 2, :);")
    (materials / "code" / "fit.m").write_text(
        "x = 1;\ndata = data(data.rt < 3, :);\n", encoding="utf-8"
    )
    outcome, detail = check_code_anchor(anchor, materials)
    assert outcome is Outcome.VERIFIED
    assert "working tree differs" in detail

    edited = code(materials, "data = data(data.rt < 3, :);", commit=anchor.commit)
    assert check_code_anchor(edited, materials)[0] is Outcome.MISMATCH


def test_code_wrong_lines_and_past_end(materials):
    assert (
        check_code_anchor(code(materials, "x = 1;"), materials)[0] is Outcome.MISMATCH
    )
    outcome, detail = check_code_anchor(code(materials, "z", 9, 9), materials)
    assert outcome is Outcome.MISMATCH
    assert "only" in detail


def test_code_without_commit_uses_working_tree(materials):
    anchor = code(materials, "data = data(data.rt < 2, :);", commit=None)
    outcome, detail = check_code_anchor(anchor, materials)
    assert outcome is Outcome.VERIFIED
    assert "no commit" in detail


# --- Data -----------------------------------------------------------------------


def test_data_anchor_checksum(tmp_path):
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "t.csv").write_bytes(b"a,b\n1,2\n")
    digest = hashlib.sha256(b"a,b\n1,2\n").hexdigest()
    anchor = DataAnchor(file="data/t.csv", quote="n = 1")

    assert check_data_anchor(anchor, tmp_path, {})[0] is Outcome.UNCHECKED
    assert check_data_anchor(anchor, tmp_path, {"data/t.csv": digest})[0] is (
        Outcome.UNCHECKED
    )
    assert check_data_anchor(anchor, tmp_path, {"data/t.csv": "0" * 64})[0] is (
        Outcome.MISMATCH
    )
    missing = DataAnchor(file="data/none.csv", quote="n = 1")
    assert check_data_anchor(missing, tmp_path, {})[0] is Outcome.MISMATCH


def test_data_anchor_folder_compares_each_file_in_it(tmp_path):
    folder = tmp_path / "data" / "sessions"
    folder.mkdir(parents=True)
    for i in (1, 2):
        (folder / f"s{i}.csv").write_bytes(f"session {i}\n".encode())
    sums = {
        f"data/sessions/s{i}.csv": hashlib.sha256(f"session {i}\n".encode()).hexdigest()
        for i in (1, 2)
    }
    anchor = DataAnchor(file="data/sessions", quote="n = 2")

    outcome, detail = check_data_anchor(anchor, tmp_path, sums)
    assert outcome is Outcome.UNCHECKED and "checksums match for 2 files" in detail
    wrong = {**sums, "data/sessions/s2.csv": "0" * 64}
    outcome, detail = check_data_anchor(anchor, tmp_path, wrong)
    assert outcome is Outcome.MISMATCH and "s2.csv checksum differs" in detail


@pytest.mark.parametrize(
    ("value", "quote", "shown"),
    [
        (4.125, "SEM 4.13", True),  # half a unit of the last digit
        (4.1351, "SEM 4.13", False),
        (18236, "n = 18,236; mean 412.6 ms", True),
        (412.63, "n = 18,236; mean 412.6 ms", True),
        (-1.21, "−1.21 · −1.07", True),
        (1.21, "−1.21 · −1.07", False),  # sign matters
        (1.5612e-10, "p = 1.56e-10", True),
        (1.5612e-9, "p = 1.56e-10", False),
        (100, "bins [0,100] … [450,550] ms", True),
        (550, "bins [0,100] … [450,550] ms", True),
        (0.84, "+0.84 · +1.25", True),
        ("ABDR", "AADR_…, BBDR_…, ABDR_…", True),
        ("Ab", "AADR_…, BBDR_…, ABDR_…", False),
        (True, "all trials kept: yes", True),
        (True, "TRUE", True),
        (False, "all trials kept: yes", False),
        (False, "converged: false", True),
        (False, "not known", False),  # whole words only
    ],
)
def test_value_shown_in_quote(value, quote, shown):
    assert shown_in(Value(name="x", value=value), quote) is shown


@pytest.fixture
def workspace(tmp_path):
    (tmp_path / "materials" / "data").mkdir(parents=True)
    (tmp_path / "materials" / "data" / "t.mat").write_bytes(b"raw")
    exported = tmp_path / "derivations" / "output" / "t.csv"
    exported.parent.mkdir(parents=True)
    exported.write_text("x\n1\n", encoding="utf-8")
    script = tmp_path / "derivations" / "behavior.py"
    script.write_text("", encoding="utf-8")
    write_values(
        tmp_path / "derivations" / "output" / "behavior.json",
        {"durations": {"A": {"n": 18236, "mean": 412.63}}},
        script=script,
        inputs=[exported],
        workspace=tmp_path,
    )
    return tmp_path


def derived(quote="n = 18,236; mean 412.6 ms", script="derivations/behavior.py"):
    return DataAnchor(
        file="data/t.mat",
        quote=quote,
        produced_by={"script": script, "output": "derivations/output/behavior.json"},
    )


VALUES = (
    Value(name="n", value=18236, key="durations/A/n"),
    Value(name="mean", value=412.63, unit="ms", key="durations/A/mean"),
)


def check(workspace, anchor=None, values=VALUES):
    return check_data_anchor(
        anchor or derived(), workspace / "materials", {}, values, workspace
    )


def test_values_verified_against_output(workspace):
    outcome, detail = check(workspace)
    assert outcome is Outcome.VERIFIED
    assert detail.startswith("2 values match derivations/output/behavior.json")


def test_values_unchecked_without_workspace(workspace):
    outcome, _ = check_data_anchor(derived(), workspace / "materials", {}, VALUES)
    assert outcome is Outcome.UNCHECKED


@pytest.mark.parametrize(
    ("values", "message"),
    [
        ((Value(name="n", value=19755, key="durations/A/n"),), "in the record"),
        ((Value(name="sd", value=1, key="durations/A/sd"),), "not in"),
    ],
)
def test_value_mismatch_or_missing_key(workspace, values, message):
    outcome, detail = check(workspace, values=values)
    assert outcome is Outcome.MISMATCH
    assert message in detail


def test_true_false_values_not_confused_with_one_and_zero(tmp_path):
    script = tmp_path / "derivations" / "check.py"
    script.parent.mkdir(parents=True)
    script.write_text("", encoding="utf-8")
    write_values(
        tmp_path / "derivations" / "output" / "behavior.json",
        {"kept": True},
        script=script,
        inputs=[],
        workspace=tmp_path,
    )
    (tmp_path / "materials" / "data").mkdir(parents=True)
    (tmp_path / "materials" / "data" / "t.mat").write_bytes(b"raw")
    anchor = derived(quote="all kept: yes (1 session)", script="derivations/check.py")

    def outcome(value):
        values = (Value(name="kept", value=value, key="kept"),)
        return check(tmp_path, anchor=anchor, values=values)[0]

    assert outcome(True) is Outcome.VERIFIED
    assert outcome(1) is Outcome.MISMATCH


def test_value_must_be_shown_in_quote(workspace):
    outcome, detail = check(workspace, anchor=derived(quote="n = 18,236"))
    assert outcome is Outcome.MISMATCH
    assert "mean = 412.63 is not shown" in detail


def test_changed_input_makes_output_stale(workspace):
    (workspace / "derivations" / "output" / "t.csv").write_text(
        "x\n2\n", encoding="utf-8"
    )
    outcome, detail = check(workspace)
    assert outcome is Outcome.STALE
    assert "derivations/output/t.csv" in detail


@pytest.mark.parametrize(
    ("statement", "missing"),
    [
        ("n = 18,236 trials; mean 412.6 ms.", []),
        ("18236 trials, mean 413 ms.", []),  # rounding the quote is allowed
        ("Mean 412.7 ms.", ["412.7"]),
        ("Per subject: d = 0.45.", ["0.45"]),
    ],
)
def test_statement_numbers_must_be_shown(statement, missing):
    assert unsupported_numbers(statement, "n = 18,236; mean 412.6 ms") == missing


def test_changed_script_makes_output_stale(workspace):
    (workspace / "derivations" / "behavior.py").write_text(
        "# edited\n", encoding="utf-8"
    )
    outcome, detail = check(workspace)
    assert outcome is Outcome.STALE
    assert "derivations/behavior.py" in detail


def test_output_must_come_from_the_named_script(workspace):
    (workspace / "derivations" / "other.py").write_text("", encoding="utf-8")
    outcome, detail = check(workspace, anchor=derived(script="derivations/other.py"))
    assert outcome is Outcome.MISMATCH
    assert "was written by derivations/behavior.py" in detail


# --- Record ---------------------------------------------------------------------


def test_check_record_covers_claims_and_observations(materials, text):
    claim_anchor = ms("212 single units")
    record = AuditRecord(
        drafted_by=DRAFTER,
        claims=(
            Claim(
                id="R1.a",
                type=ClaimType.NEW_RESULT,
                anchor=claim_anchor,
                trace=Trace.TRACED,
            ),
        ),
        findings=(
            Finding(
                id="R1.a/units",
                claim_id="R1.a",
                status=Status.CONSISTENT,
                basis=Basis.EXACT,
                summary="Results and code agree.",
                observations=(
                    Observation(
                        source=Source.RESULTS,
                        statement="212 units",
                        anchor=claim_anchor,
                        obtained=Obtained.QUOTED,
                    ),
                    Observation(
                        source=Source.CODE,
                        statement="rt < 2",
                        anchor=code(materials, "data = data(data.rt < 2, :);"),
                        obtained=Obtained.READ,
                        values=(Value(name="cutoff", value=2),),
                    ),
                ),
            ),
        ),
    )
    checks = check_record(record, materials, text)
    assert [c.location for c in checks] == [
        "claim R1.a",
        "finding R1.a/units results",
        "finding R1.a/units code",
    ]
    assert all(c.outcome is Outcome.VERIFIED for c in checks)

    # a value the code is said to set must be in the lines quoted
    finding = record.findings[0]
    results, in_code = finding.observations
    wrong = in_code.model_copy(update={"values": (Value(name="cutoff", value=3),)})
    finding = finding.model_copy(update={"observations": (results, wrong)})
    checks = check_record(record.model_copy(update={"findings": (finding,)}),
                          materials, text)  # fmt: skip
    assert checks[-1].outcome is Outcome.MISMATCH
    assert "cutoff = 3 is not shown in the quote" in checks[-1].detail

    # a setting stated in fixed words is a reading of the code, not its text
    paired = in_code.model_copy(
        update={"values": (Value(name="design", value="paired"),)}
    )
    finding = finding.model_copy(update={"observations": (results, paired)})
    record = record.model_copy(update={"findings": (finding,)})
    assert check_record(record, materials, text)[-1].outcome is Outcome.MISMATCH
    checks = check_record(record, materials, text, readings=stats.READINGS)
    assert checks[-1].outcome is Outcome.VERIFIED


def test_derived_statement_may_cite_numbers_its_quote_does_not(workspace, text):
    # a derived value's statement says how it was computed (here, a window)
    claim_anchor = ms("212 single units")
    observation = Observation(
        source=Source.DATA,
        statement="Mean duration of trials shorter than 2000 ms: 412.63",
        anchor=derived(quote="durations/A/mean = 412.63"),
        obtained=Obtained.RECOMPUTED,
        values=(VALUES[1],),
    )
    record = AuditRecord(
        drafted_by=DRAFTER,
        claims=(
            Claim(
                id="R1.a",
                type=ClaimType.NEW_RESULT,
                anchor=claim_anchor,
                trace=Trace.TRACED,
            ),
        ),
        findings=(
            Finding(
                id="R1.a/durations",
                claim_id="R1.a",
                status=Status.CONSISTENT,
                basis=Basis.EXACT,
                summary="Results and data agree.",
                observations=(
                    Observation(
                        source=Source.RESULTS,
                        statement="212 units",
                        anchor=claim_anchor,
                        obtained=Obtained.QUOTED,
                    ),
                    observation,
                ),
            ),
        ),
    )
    checks = check_record(record, workspace / "materials", text, workspace=workspace)
    assert checks[-1].outcome is Outcome.VERIFIED, checks[-1].detail


def test_a_formula_given_as_a_picture_is_filled_in_only_where_it_was():
    text = ManuscriptText(
        ["For the sample X = {xi} of size N, the fit converged in every case."]
    )
    quote = "For the sample of size N, the fit converged in every case."
    place = quote.index("of size")
    filled = text.filled(quote, [place])
    assert filled == "For the sample X={xi} of size N, the fit converged in every case."
    assert text.filled(quote) is None  # too long to put in elsewhere
    assert text.filled(quote, [quote.index("in every")]) is None


def test_the_increment_sign_matches_a_capital_delta():
    text = ManuscriptText(["The change ∆t was 2 ms."])
    assert text.find("The change Δt was 2 ms.", loose=True) == [1]


def test_a_quote_is_filled_in_only_where_the_page_has_a_few_characters_more():
    text = ManuscriptText(
        ["When the likelihood point ˆθ is on the boundary, we stop here."]
    )
    filled = text.filled("When the likelihood point is on the boundary, we stop here.")
    assert filled == "When the likelihood point ˆθ is on the boundary, we stop here."
    assert (
        text.filled("When the likelihood value is on the boundary, we stop here.")
        is None
    )
