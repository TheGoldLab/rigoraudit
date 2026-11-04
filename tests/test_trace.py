# Copyright (c) 2026, Joshua I. Gold
# SPDX-License-Identifier: BSD-2-Clause

import json
import subprocess

import pytest

from miragold import cli, compare, decompose, segment, settings, stats, trace
from miragold.schema import DrafterKind, Facet, Source, Status, Trace

CODE = """import json

def accuracy(trials):
    kept = [t for t in trials if t["rt"] <= 2.0]
    return 100 * sum(t["correct"] for t in kept) / len(kept)
"""
STATS = """from scipy import stats

def above_chance(accuracy):
    return stats.ttest_1samp(accuracy, 50, alternative="greater")
"""
METHODS = (
    "Trials with response times above 2 s were excluded. Accuracy is the percent "
    "correct. Accuracy was compared with chance by a two-tailed t test."
)
RESULTS = (
    "Accuracy was 80% in block A (Figure 1), above chance (t(9) = 3.10, p = 0.013)."
)


def git(cwd, *args):
    return subprocess.run(
        ["git", "-c", "user.name=T", "-c", "user.email=t@example.org", *args],
        cwd=cwd, check=True, capture_output=True, text=True,
    ).stdout.strip()  # fmt: skip


@pytest.fixture
def ws(tmp_path):
    code = tmp_path / "materials" / "code"
    code.mkdir(parents=True)
    (code / "analysis.py").write_text(CODE, encoding="utf-8")
    (code / "stats.py").write_text(STATS, encoding="utf-8")
    git(code, "init", "-q")
    git(code, "add", ".")
    git(code, "commit", "-q", "-m", "c")
    commit = git(code, "rev-parse", "HEAD")
    # the working tree changes after the commit; checks must use the commit
    (code / "analysis.py").write_text(CODE.replace("2.0", "3.0"), encoding="utf-8")
    (tmp_path / "audit.yaml").write_text(
        "materials:\n  manuscript:\n    path: materials/paper.pdf\n"
        f"  code:\n    path: materials/code\n    repository: https://github.com/example/repo\n"
        f"    commit: {commit} (the version the paper cites)\n",
        encoding="utf-8",
    )
    extract = tmp_path / "work" / "extract" / "paragraphs.json"
    extract.parent.mkdir(parents=True)
    extract.write_text(json.dumps([
        {"section": "Methods › Analysis", "paragraph": 1, "text": METHODS},
        {"section": "Results › Accuracy", "paragraph": 1, "text": RESULTS},
    ]), encoding="utf-8")  # fmt: skip
    segment.write_handoffs(tmp_path)
    claim = {"id": "R1.1.a", "paragraph": "R1.1", "type": "new_result",
             "quote": "Accuracy was 80% in block A (Figure 1), above chance (t(9) = 3.10, p = 0.013)"}  # fmt: skip
    seg = {"instructions": "segment v3", "claims": [claim]}
    assert segment.import_answer(tmp_path, json.dumps(seg), "t")[1] == []
    decompose.write_handoffs(tmp_path)
    dec = {"instructions": "decompose v4", "claims": [{"id": "R1.1.a", "facets": [
        {"facet": "quantity", "quote": "80%", "states": "Accuracy was 80%.",
         "values": [{"name": "accuracy", "printed": "80%"}]},
        {"facet": "analysis", "quote": "above chance (t(9) = 3.10, p = 0.013)",
         "states": "The measure is accuracy."},
    ]}]}  # fmt: skip
    assert decompose.import_answer(tmp_path, json.dumps(dec), "t")[1] == []
    return tmp_path


def reply(analysis_code, analysis_methods=None, extra=()):
    methods = analysis_methods if analysis_methods is not None else [
        {"paragraph": "M1.1", "quote": "Accuracy is the percent correct.",
         "states": "Accuracy is the percent of trials correct."}]  # fmt: skip
    facets = [
        {"facet": "quantity", "methods": [], "code": []},
        {"facet": "analysis", "methods": methods, "code": analysis_code},
        *extra,
    ]
    return json.dumps(
        {"instructions": "trace v4", "claims": [{"id": "R1.1.a", "facets": facets}]}
    )


GOOD_CODE = [{"file": "analysis.py", "lines": [4, 5], "states": "Keeps trials up to 2 s; percent correct.",
              "quote": '    kept = [t for t in trials if t["rt"] <= 2.0]\n'
                       '    return 100 * sum(t["correct"] for t in kept) / len(kept)'}]  # fmt: skip


def test_settings_read_the_link_at_the_commit(ws):
    s = settings.load(ws)
    assert s.manuscript == "paper.pdf" and s.code.path == "code"
    assert s.code.link() == f"https://github.com/example/repo/tree/{s.code.commit}"


def test_handoff_gives_the_link_methods_and_facets(ws):
    [md] = trace.write_handoffs(ws, settings.load(ws))
    text = md.read_text(encoding="utf-8")
    assert "/tree/" in text and METHODS in text
    assert "- `R1.1.a`: Accuracy was 80% in block A" in text
    assert "  - analysis: The measure is accuracy." in text
    assert RESULTS not in text


def test_a_coding_assistant_gets_the_methods_once(ws):
    [md] = trace.write_handoffs(ws, settings.load(ws), shared_methods=True)
    text = md.read_text(encoding="utf-8")
    assert METHODS not in text and "`work/trace/methods.md`" in text
    assert METHODS in (ws / trace.METHODS).read_text(encoding="utf-8")


def test_good_reply_is_saved_with_the_lines_at_the_commit(ws, capsys):
    s = settings.load(ws)
    trace.write_handoffs(ws, s)
    path = ws / "reply.txt"
    path.write_text(reply(GOOD_CODE), encoding="utf-8")
    cli.main(["import", "trace", str(path), str(ws), "--by", "t"])
    out = capsys.readouterr().out
    assert out.startswith(
        "Accepted trace-R1.1.a: 1 Methods passage and 1 code passage for 1 claim"
    )
    obs = trace.trace_observations(ws, s)[R"R1.1.a"][Facet.ANALYSIS]
    assert [o.source for o in obs] == [Source.METHODS, Source.CODE]
    code = obs[1].anchor
    assert (code.file, code.line_start, code.commit) == (
        "code/analysis.py",
        4,
        s.code.commit,
    )
    assert "<= 2.0" in code.quote
    assert trace.write_handoffs(ws, s) == []


@pytest.mark.parametrize(
    ("code", "problem"),
    [
        ([{**GOOD_CODE[0], "quote": GOOD_CODE[0]["quote"].replace("2.0", "3.0")}],
         "the quote is not lines 4–5 of analysis.py at this version; line 4 there is"),
        ([{**GOOD_CODE[0], "quote": GOOD_CODE[0]["quote"].replace("100 *", "10 *")}],
         ("line 5 there is 'return 100 * sum(t[\"correct\"] for t in kept) / len(kept)', "
          "but the quote has 'return 10 *")),
        ([{**GOOD_CODE[0], "file": "fit.py"}], "fit.py is not in the repository at this version."),
        ([{**GOOD_CODE[0], "file": "../outside.py"}], "../outside.py is not in the repository"),
        ([{**GOOD_CODE[0], "lines": [4, 9]}], "analysis.py has only 6 lines, not 9."),
    ],
)  # fmt: skip
def test_code_citations_are_checked_against_the_local_copy(ws, code, problem):
    s = settings.load(ws)
    trace.write_handoffs(ws, s)
    saved, problems = trace.import_answer(ws, s, reply(code), "t")
    assert saved is None
    [p] = problems
    assert p.startswith("In claim R1.1.a, analysis: ") and problem in p


def test_facets_and_methods_are_checked(ws):
    s = settings.load(ws)
    trace.write_handoffs(ws, s)
    bad_methods = [
        {"paragraph": "M1.1", "quote": "Accuracy is percent correct.", "states": "s"}
    ]
    extra = [{"facet": "population", "methods": [], "code": []}]
    problems = trace.import_answer(ws, s, reply([], bad_methods, extra), "t")[1]
    assert problems == [
        "Claim R1.1.a has no population facet; give only its facets (quantity, analysis).",
        (
            "In claim R1.1.a, analysis: the Methods quote is not in paragraph M1.1 "
            "word for word: 'Accuracy is percent correct.'"
        ),
    ]


def ask(ws, s, **answer):
    text = json.dumps({"instructions": "trace v4", **answer})
    return trace.import_answer(ws, s, text, "t")


def test_no_access_brings_the_index_and_then_the_lines_asked_for(ws, capsys):
    s = settings.load(ws)
    trace.write_handoffs(ws, s)
    saved, problems = ask(ws, s, task="trace-R1.1.a", no_access="did not open")
    assert problems == [] and saved.parent.name == "asked"

    [md] = trace.write_handoffs(ws, s)
    assert md.stem == "trace-R1.1.a-round2"
    text = md.read_text(encoding="utf-8")
    assert "/tree/" not in text and "## Index of the code" in text
    assert "### `analysis.py` (5 lines)" in text
    assert "- functions: accuracy (3)" in text and "kept (4)" in text
    # the index is read at the commit, not the changed working tree
    assert "## Code you asked for" not in text

    # citing code before asking for it is refused
    assert (
        "were not sent to you"
        in trace.import_answer(ws, s, reply(GOOD_CODE), "t")[1][0]
    )

    saved, problems = ask(ws, s, requests=[{"file": "analysis.py", "lines": [3, 5]}])
    assert problems == []
    [md] = trace.write_handoffs(ws, s)
    assert md.stem == "trace-R1.1.a-round3"
    text = md.read_text(encoding="utf-8")
    assert "### `analysis.py`, lines 3–5" in text
    assert '4      kept = [t for t in trials if t["rt"] <= 2.0]' in text

    path = ws / "reply.txt"
    path.write_text(reply(GOOD_CODE), encoding="utf-8")
    cli.main(["import", "trace", str(path), str(ws), "--by", "t"])
    assert "Accepted trace-R1.1.a-round3" in capsys.readouterr().out
    obs = trace.trace_observations(ws, s)["R1.1.a"][Facet.ANALYSIS]
    assert obs[1].anchor.line_start == 4
    assert trace.write_handoffs(ws, s) == []


def test_requests_are_checked(ws):
    s = settings.load(ws)
    trace.write_handoffs(ws, s)
    ask(ws, s, no_access="did not open")
    trace.write_handoffs(ws, s)
    _, problems = ask(
        ws, s,
        requests=[{"file": "fit.py"}, {"file": "analysis.py", "lines": [1, 99]}],
        claims=json.loads(reply([]))["claims"],
    )  # fmt: skip
    assert problems == [
        "Send either requests for code or your answer for the claims, not both.",
        "fit.py is not in the index; ask only for files listed there.",
        "analysis.py has only 6 lines, not 99.",
    ]


def test_requests_stop_after_the_last_round(ws):
    s = settings.load(ws)
    trace.write_handoffs(ws, s)
    ask(ws, s, no_access="did not open")
    for _ in range(trace.MAX_ROUNDS - 2):
        trace.write_handoffs(ws, s)
        assert ask(ws, s, requests=[{"file": "analysis.py"}])[1] == []
    [md] = trace.write_handoffs(ws, s)
    assert "This is the last round" in md.read_text(encoding="utf-8")
    [problem] = ask(ws, s, requests=[{"file": "analysis.py"}])[1]
    assert problem.startswith("No more code can be sent for these claims.")


def test_a_link_task_takes_no_requests(ws):
    s = settings.load(ws)
    trace.write_handoffs(ws, s)
    [problem] = ask(ws, s, requests=[{"file": "analysis.py"}])[1]
    assert problem.startswith("This task gave a link to the repository")


def test_repository_only_setting_reports_no_access_plainly(ws):
    manifest = ws / "audit.yaml"
    manifest.write_text(
        manifest.read_text(encoding="utf-8")
        + "settings:\n  trace:\n    code_access: repository\n",
        encoding="utf-8",
    )
    s = settings.load(ws)
    trace.write_handoffs(ws, s)
    [problem] = ask(ws, s, no_access="the link did not open")[1]
    assert problem.startswith(
        "The assistant could not open the repository (the link did not open)."
    )


def test_a_notebook_in_the_code_gives_the_index_unless_repository_is_asked(ws):
    code = ws / "materials" / "code"
    (code / "figures.ipynb").write_text(json.dumps({"cells": [
        {"cell_type": "code", "source": "print(1)"}]}), encoding="utf-8")  # fmt: skip
    git(code, "add", "figures.ipynb")
    git(code, "commit", "-q", "-m", "nb")
    old = settings.load(ws).code.commit
    manifest = ws / "audit.yaml"
    text = manifest.read_text(encoding="utf-8").replace(
        old, git(code, "rev-parse", "HEAD")
    )
    manifest.write_text(text, encoding="utf-8")
    [md] = trace.write_handoffs(ws, settings.load(ws))
    assert "## Index of the code" in md.read_text(
        encoding="utf-8"
    ) and "/tree/" not in md.read_text(encoding="utf-8")

    md.unlink()
    manifest.write_text(
        text + "settings:\n  trace:\n    code_access: repository\n", encoding="utf-8"
    )
    [md] = trace.write_handoffs(ws, settings.load(ws))
    assert "/tree/" in md.read_text(encoding="utf-8")


def test_index_setting_or_no_repository_gives_the_index_first(ws):
    manifest = ws / "audit.yaml"
    text = manifest.read_text(encoding="utf-8")
    manifest.write_text(
        text + "settings:\n  trace:\n    code_access: index\n", encoding="utf-8"
    )
    [md] = trace.write_handoffs(ws, settings.load(ws))
    assert md.stem == "trace-R1.1.a" and "## Index of the code" in md.read_text(
        encoding="utf-8"
    )

    md.unlink()
    no_repo = "\n".join(
        ln
        for ln in text.splitlines()
        if "repository:" not in ln and "commit:" not in ln
    )
    manifest.write_text(no_repo + "\n", encoding="utf-8")
    [md] = trace.write_handoffs(ws, settings.load(ws))
    # without a commit the working tree is indexed
    assert "## Index of the code" in md.read_text(encoding="utf-8")
    manifest.write_text(
        no_repo + "\nsettings:\n  trace:\n    code_access: repository\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="no code repository and commit"):
        trace.write_handoffs(ws, settings.load(ws))


def test_no_code_in_the_manifest(ws):
    (ws / "audit.yaml").write_text(
        "materials:\n  manuscript:\n    path: paper.pdf\n", encoding="utf-8"
    )
    with pytest.raises(ValueError, match="no code"):
        trace.write_handoffs(ws, settings.load(ws))


def test_a_commit_of_only_digits_is_read_as_written(tmp_path):
    (tmp_path / "audit.yaml").write_text(
        "materials:\n  manuscript:\n    path: paper.pdf\n"
        f"  code:\n    path: code\n    commit: {'1' * 40}\n",
        encoding="utf-8",
    )
    assert settings.load(tmp_path).code.commit == "1" * 40


TEST = {"quote": "t(9) = 3.10, p = 0.013", "statistic": "t", "value": "3.10",
        "df": ["9"], "p": "= 0.013", "design": "one-sample"}  # fmt: skip
TAILS_TEXT = {"paragraph": "M1.1", "quote": "compared with chance by a two-tailed t test",
              "states": "A two-tailed t test against chance.", "says": "2"}  # fmt: skip
TAILS_CODE = {"file": "stats.py", "lines": [4, 4], "says": "1",
              "quote": '    return stats.ttest_1samp(accuracy, 50, alternative="greater")',
              "states": "A one-tailed one-sample t test against 50."}  # fmt: skip


@pytest.fixture
def tested(ws):
    """The workspace, with the claim's test copied by decompose."""
    [answer] = decompose.read_accepted(ws)
    dec = answer.answer.model_dump(mode="json", exclude_none=True)
    for saved in (ws / "work" / "decompose" / "answers").glob("*.json"):
        saved.unlink()
    dec["claims"][0]["tests"] = [TEST]
    assert decompose.import_answer(ws, json.dumps(dec), "t")[1] == []
    return ws


def with_tests(tests):
    answer = json.loads(reply(GOOD_CODE))
    answer["claims"][0]["tests"] = tests
    return json.dumps(answer)


def test_each_test_is_listed_and_its_settings_checked(tested):
    s = settings.load(tested)
    [md] = trace.write_handoffs(tested, s)
    assert "  - test 1: t(9) = 3.10, p = 0.013" in md.read_text(encoding="utf-8")
    assert trace.import_answer(tested, s, reply(GOOD_CODE), "t")[1] == [
        (
            "Claim R1.1.a has no entry for test 1; give one, with empty lists if the "
            "Methods and the code state none of its settings."
        )
    ]
    bad = [{"test": 1, "settings": [{"setting": "tails", "code": {**TAILS_CODE, "says": "one"}},
                                    {"setting": "seed"}]}]  # fmt: skip
    assert trace.import_answer(tested, s, with_tests(bad), "t")[1] == [
        "In claim R1.1.a, test 1, tails: says must be one of 1, 2, not 'one'.",
        (
            "In claim R1.1.a, test 1, seed: give where the Methods or the code state "
            "it, or leave the setting out."
        ),
    ]


def test_the_tool_compares_the_settings_and_assumption_checks(tested):
    s = settings.load(tested)
    trace.write_handoffs(tested, s)
    good = [{"test": 1, "settings": [
        {"setting": "tails", "methods": TAILS_TEXT, "code": TAILS_CODE},
        {"setting": "design", "code": {**TAILS_CODE, "says": "one-sample"}},
    ]}]  # fmt: skip
    assert trace.import_answer(tested, s, with_tests(good), "t")[1] == []
    found = {f.scope: f for f in stats.traced_test_findings(tested, s)}
    # equal variances is not assumed by a one-sample test; the settings come
    # in a fixed order, so the record is the same on every run
    assert list(found) == ["design", "tails", "normality addressed"]
    assert found["tails"].status is Status.DIFFERS
    assert found["tails"].drafted_by.kind is DrafterKind.TOOL
    # the Results paragraph states the design, and the code agrees
    assert found["design"].status is Status.CONSISTENT
    assert found["design"].observations[0].source is Source.RESULTS
    normality = found["normality addressed"]
    assert normality.status is Status.NOT_DESCRIBED
    assert normality.not_described_in == (Source.METHODS, Source.CODE)

    # compare shows what the tool checked, so the assistant does not redo it
    [md] = compare.write_handoffs(tested, s)
    text = md.read_text(encoding="utf-8")
    assert "#### Already checked by the tool; do not repeat" in text
    assert "- quantity, p from the statistic: consistent." in text
    assert "- analysis, tails: differs." in text
    # the facets the tool covered need no finding of the assistant's
    [h] = compare.pending_handoffs(tested)
    assert set(h.claims[0].checked_facets) == {Facet.QUANTITY, Facet.ANALYSIS}


PROCEDURE = "Trials with response times above 2 s were excluded."


@pytest.fixture
def pws(ws):
    """The workspace with one procedure claim, in the Methods."""
    segment.write_handoffs(ws, ("Results", "Methods"))
    claim = {"id": "M1.1.a", "paragraph": "M1.1", "type": "procedure",
             "quote": PROCEDURE}  # fmt: skip
    seg = {"instructions": "segment v3", "claims": [claim]}
    assert segment.import_answer(ws, json.dumps(seg), "t")[1] == []
    return ws


def procedure_reply(claim_values=None, code_values=None, **extra):
    code = {"file": "analysis.py", "lines": [4, 4], "states": "Keeps trials up to 2 s.",
            "quote": '    kept = [t for t in trials if t["rt"] <= 2.0]',
            "values": code_values if code_values is not None
            else [{"name": "RT limit", "printed": "2.0"}]}  # fmt: skip
    claim = {"id": "M1.1.a", "code": [code],
             "values": claim_values if claim_values is not None
             else [{"name": "RT limit", "printed": "2 s"}], **extra}  # fmt: skip
    return json.dumps({"instructions": "trace v4", "claims": [claim]})


def test_a_procedure_is_traced_whole_in_a_task_of_its_own(pws):
    s = settings.load(pws)
    new_result, procedures = trace.plan_handoffs(pws, s)
    assert list(new_result.claims) == ["R1.1.a"] and not new_result.procedures
    assert procedures.procedures == {"M1.1.a": "M1.1"} and not procedures.facets
    text = trace.render_handoff(procedures)
    assert f"- `M1.1.a` (paragraph `M1.1`): {PROCEDURE}" in text
    assert "## Claims and their facets" not in text


def test_a_procedure_gives_its_own_values_and_the_code_values(pws):
    s = settings.load(pws)
    trace.write_handoffs(pws, s)
    saved, problems = trace.import_answer(
        pws, s, procedure_reply(), "t", handoff="trace-M1.1.a"
    )
    assert problems == [] and saved is not None
    own, code = trace.procedure_observations(pws, s)["M1.1.a"]
    assert own.source is Source.METHODS and own.anchor.quote == PROCEDURE
    [stated] = own.values
    assert (stated.name, stated.value, stated.unit) == ("RT limit", 2, "s")
    assert code.source is Source.CODE and [v.value for v in code.values] == [2.0]
    assert "<= 2.0" in code.anchor.quote  # the commit, not the working tree


def test_a_procedure_has_no_facets_and_its_values_are_where_it_says(pws):
    s = settings.load(pws)
    trace.write_handoffs(pws, s)
    facets = [{"facet": "condition", "methods": [], "code": []}]
    _, problems = trace.import_answer(
        pws,
        s,
        procedure_reply(
            claim_values=[{"name": "RT limit", "printed": "3 s"}],
            code_values=[{"name": "RT limit", "printed": "2 s"}],
            facets=facets,
        ),
        "t",
        handoff="trace-M1.1.a",
    )
    assert [p.kind for p in problems] == [
        "whole", "value-not-in-quote", "value-not-in-quote"
    ]  # fmt: skip


def test_a_new_result_cites_by_facet_not_whole(ws):
    s = settings.load(ws)
    trace.write_handoffs(ws, s)
    answer = json.loads(reply(GOOD_CODE))
    answer["claims"][0]["code"] = GOOD_CODE
    _, problems = trace.import_answer(ws, s, json.dumps(answer), "t")
    assert [p.kind for p in problems] == ["not-whole"]


def traced_procedure(ws, **kw):
    s = settings.load(ws)
    trace.write_handoffs(ws, s)
    _, problems = trace.import_answer(
        ws, s, procedure_reply(**kw), "t", handoff="trace-M1.1.a"
    )
    assert problems == []
    return s


def test_a_value_in_another_unit_is_converted_to_the_codes(pws):
    s = traced_procedure(
        pws,
        claim_values=[{"name": "RT limit", "printed": "2 s"}],
        code_values=[{"name": "RT limit", "printed": "2.0", "unit": "min"}],
    )
    own, converted, code = trace.procedure_observations(pws, s)["M1.1.a"]
    assert converted.source is Source.METHODS and converted.anchor == own.anchor
    [v] = converted.values
    assert (v.value, v.unit) == (pytest.approx(2 / 60), "min")
    assert code.values[0].unit == "min"


def test_a_unit_the_tool_cannot_convert_is_sent_back(pws):
    s = settings.load(pws)
    trace.write_handoffs(pws, s)
    values = [{"name": "RT limit", "printed": "2.0", "unit": "fortnights"}]
    _, problems = trace.import_answer(
        pws, s, procedure_reply(code_values=values), "t", handoff="trace-M1.1.a"
    )
    assert [p.kind for p in problems] == ["unit-unknown"]


WHOLE = {"observations": ["O1", "O2"], "basis": "exact",
         "comparisons": [{"kind": "exact", "stated": ["O1.v1"], "observed": ["O2.v1"]}],
         "summary": "The Methods state 2 s. The code keeps trials up to 2.0."}  # fmt: skip


def whole_answer(*findings):
    return json.dumps({"instructions": "compare v6", "claims": [
        {"claim": "M1.1.a", "findings": list(findings)}]})  # fmt: skip


def test_a_procedure_is_compared_whole_in_a_task_of_its_own(pws):
    s = traced_procedure(pws)
    new_result, task = compare.plan_handoffs(pws, s)
    assert [c.claim for c in new_result.claims] == ["R1.1.a"]
    [claim] = task.claims
    assert claim.whole and claim.facets == ()
    assert "A procedure: compare it as a whole claim." in compare.render_handoff(task)
    compare.write_handoffs(pws, s)
    saved, problems = compare.import_answer(
        pws, whole_answer(WHOLE), "t", handoff=task.name
    )
    assert problems == [] and saved is not None
    [f] = compare.read_accepted(pws)[0].findings
    assert (f.id, f.facet, f.status) == ("M1.1.a/whole", None, Status.CONSISTENT)
    traced = {c.id: c.trace for c in compare.build_record(pws, s).claims}
    assert traced["M1.1.a"] is Trace.TRACED


def test_a_procedure_finding_names_no_facet(pws):
    s = traced_procedure(pws)
    compare.write_handoffs(pws, s)
    name = "compare-M1.1.a"
    _, problems = compare.import_answer(
        pws, whole_answer({**WHOLE, "facet": "condition"}), "t", handoff=name
    )
    assert "facet-given" in [p.kind for p in problems]
    _, problems = compare.import_answer(pws, whole_answer(), "t", handoff=name)
    assert "finding-missing" in [p.kind for p in problems]
