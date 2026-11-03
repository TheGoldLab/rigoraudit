# Copyright (c) 2026, Joshua I. Gold
# SPDX-License-Identifier: BSD-2-Clause

import dataclasses
import json

import pytest

from rigoraudit import cli, decompose, derive, instructions, segment, settings
from rigoraudit.schema import Facet, Source
from rigoraudit.verify import shown_in

RESULTS = "Mice were correct on 75% of trials in block A."
SCRIPT = """from pathlib import Path
import json

from rigoraudit.values import write_values

HERE = Path(__file__).resolve().parent
WORKSPACE = HERE.parent
DATA = WORKSPACE / "materials" / "data" / "trials.json"
trials = json.loads(DATA.read_text())
write_values(
    HERE / "output" / "values" / "R1.1.a.json",
    {"accuracy": {"A": 100 * sum(trials) / len(trials)}},
    script=Path(__file__),
    inputs=[DATA],
    workspace=WORKSPACE,
)
"""


@pytest.fixture
def ws(tmp_path):
    """A workspace whose one claim is split into facets, with its data."""
    ws = tmp_path / "audit"
    (ws / "materials" / "data").mkdir(parents=True)
    (ws / "materials" / "data" / "trials.json").write_text("[1, 1, 1, 0]")
    (ws / "audit.yaml").write_text("materials:\n  manuscript:\n    path: paper.pdf\n")
    para = ws / "work" / "extract" / "paragraphs.json"
    para.parent.mkdir(parents=True)
    para.write_text(
        json.dumps([{"section": "Results", "paragraph": 1, "text": RESULTS}])
    )
    segment.write_handoffs(ws, ("Results",))
    _, problems = segment.import_answer(ws, json.dumps({
        "instructions": "segment v2", "claims": [{"id": "R1.1.a", "paragraph": "R1.1",
        "type": "new_result", "quote": RESULTS.rstrip(".")}]}), "T")  # fmt: skip
    assert not problems
    decompose.write_handoffs(ws)
    _, problems = decompose.import_answer(ws, json.dumps({
        "instructions": "decompose v3", "claims": [{"id": "R1.1.a", "facets": [
        {"facet": "quantity", "quote": "correct on 75% of trials", "states": "s",
         "values": [{"name": "accuracy", "printed": "75%", "subject": "block A"}]},
        {"facet": "condition", "quote": "in block A", "states": "s"}]}]}), "T")  # fmt: skip
    assert not problems
    return ws


def reply(values, cannot=(), script=SCRIPT):
    answer = {"instructions": "derive v4", "claims": [{"claim": "R1.1.a",
              "values": values, "cannot": list(cannot)}]}  # fmt: skip
    text = f"```json\n{json.dumps(answer)}\n```\n"
    return text + (f"\n```python\n{script}```\n" if script else "")


GOOD = [{"for": "V1", "key": "accuracy/A", "how": "recomputed",
         "source": "data/trials.json", "derivation": "percent correct"}]  # fmt: skip


def test_the_handoff_lists_each_printed_number_and_the_materials(ws):
    [path] = derive.write_handoffs(ws, settings.load(ws))
    text = path.read_text()
    assert "- `V1` (quantity): accuracy = 75%, for block A" in text
    assert (
        "data/trials.json" in text and "derivations/output/values/R1.1.a.json" in text
    )
    assert text.startswith(instructions.load("derive").text.rstrip())


def test_linked_folders_are_listed_and_the_code_documentation_left_out(ws, tmp_path):
    elsewhere = tmp_path / "elsewhere"
    (elsewhere / "sessions").mkdir(parents=True)
    (elsewhere / "sessions" / "s1.csv").write_text("a\n1\n")
    (elsewhere / "sessions" / "loop").symlink_to(elsewhere)  # a link back
    (ws / "materials" / "linked").symlink_to(elsewhere)
    code = ws / "materials" / "code" / "lab"
    code.mkdir(parents=True)
    (code / "README.md").write_text("Run it.")
    (code / "fit.py").write_text("")
    s = dataclasses.replace(settings.load(ws), code=settings.Code(path="code/lab"))
    listed = [line.split(" (")[0] for line in derive._materials(ws, s)]
    assert listed == [
        "code/lab/fit.py",
        "data/trials.json",
        "linked/sessions/s1.csv",
    ]


def ask(ws):
    """The workspace's settings, asking before every script."""
    return dataclasses.replace(settings.load(ws), derive_run="ask")


def test_the_script_is_run_once_agreed_and_its_values_become_observations(ws):
    derive.write_handoffs(ws, settings.load(ws))
    asked = []
    saved, problems = derive.import_answer(
        ws,
        ask(ws),
        reply(GOOD),
        "T",
        approve=lambda p, c: asked.append((p, c)) or True,
    )
    assert problems == [] and saved is not None
    assert asked == [(ws / "derivations" / "R1.1.a.py", [])]
    [obs] = derive.derived_observations(ws, settings.load(ws))["R1.1.a"][Facet.QUANTITY]
    assert obs.source is Source.DATA and obs.values[0].value == 75.0
    assert obs.values[0].unit == "%" and shown_in(obs.values[0], obs.anchor.quote)
    assert not derive.plan_handoffs(ws, settings.load(ws))


def test_the_script_runs_when_the_workspace_is_named_by_a_relative_path(
    ws, monkeypatch
):
    monkeypatch.chdir(ws.parent)
    rel = type(ws)(ws.name)
    derive.write_handoffs(rel, settings.load(rel))
    _, problems = derive.import_answer(
        rel, settings.load(rel), reply(GOOD), "T", approve=lambda p, c: True
    )
    assert problems == []


def test_nothing_runs_without_agreement(ws):
    derive.write_handoffs(ws, settings.load(ws))
    saved, problems = derive.import_answer(
        ws, ask(ws), reply(GOOD), "T", approve=lambda p, c: False
    )
    assert (saved, problems) == (None, [])
    assert not (ws / "derivations" / "output").exists()


def test_a_script_that_fails_is_sent_back_with_its_error(ws):
    derive.write_handoffs(ws, settings.load(ws))
    broken = SCRIPT.replace("trials.json", "missing.json")
    _, problems = derive.import_answer(
        ws,
        settings.load(ws),
        reply(GOOD, script=broken),
        "T",
        approve=lambda p, c: True,
    )
    assert [p.kind for p in problems] == ["script-failed"]
    assert "FileNotFoundError" in problems[0]
    _, problems = derive.import_answer(
        ws,
        settings.load(ws),
        reply(GOOD, script=SCRIPT.replace('"A"', '"B"')),
        "T",
        approve=lambda p, c: True,
    )
    assert [p.kind for p in problems] == ["key-not-saved"]


def test_a_printed_number_saved_as_true_or_false_is_sent_back(ws):
    derive.write_handoffs(ws, settings.load(ws))
    flag = SCRIPT.replace("100 * sum(trials) / len(trials)", "len(trials) > 0")
    _, problems = derive.import_answer(
        ws, settings.load(ws), reply(GOOD, script=flag), "T",
        approve=lambda p, c: True,
    )  # fmt: skip
    assert [p.kind for p in problems] == ["not-a-number"]
    assert "printed number V1" in problems[0]


def test_a_number_the_code_sets_is_quoted_from_the_code(ws):
    code = ws / "materials" / "code"
    code.mkdir()
    (code / "fit.py").write_text("import math\nLEVEL = 75  # percent\n")
    s = dataclasses.replace(settings.load(ws), code=settings.Code(path="code"))
    derive.write_handoffs(ws, s)

    def answer(**setting):
        entry = {"for": "V1", "file": "fit.py", "lines": [2, 2], "value": 75}
        claims = [{"claim": "R1.1.a", "in_code": [{**entry, **setting}]}]
        return json.dumps({"instructions": "derive v4", "claims": claims})

    def kinds(**setting):
        _, problems = derive.import_answer(ws, s, answer(**setting), "T",
            approve=lambda p, c: pytest.fail("nothing to run"))  # fmt: skip
        return [p.kind for p in problems]

    assert kinds(value=80) == ["not-in-code"]
    assert kinds(lines=[2, 9]) == ["bad-lines"]
    assert kinds(file="other.py") == ["no-such-file"]
    assert kinds(**{"for": "V9"}) == ["value-missing", "unknown-value"]
    assert kinds() == []
    [obs] = derive.derived_observations(ws, s)["R1.1.a"][Facet.QUANTITY]
    assert obs.source == "code" and obs.anchor.file == "code/fit.py"
    assert obs.anchor.quote == "LEVEL = 75  # percent"
    assert obs.values[0].value == 75 and obs.values[0].unit == "%"


def test_every_number_is_recomputed_or_says_why_not(ws):
    derive.write_handoffs(ws, settings.load(ws))
    _, problems = derive.import_answer(
        ws, settings.load(ws), reply([], script=None), "T",
                                       approve=lambda p, c: True)  # fmt: skip
    assert [p.kind for p in problems] == ["value-missing"]
    bad = [{**GOOD[0], "source": "data/other.json"}]
    _, problems = derive.import_answer(
        ws, settings.load(ws), reply(bad, script=None), "T",
                                       approve=lambda p, c: True)  # fmt: skip
    assert {p.kind for p in problems} == {"no-such-file", "no-script"}
    folder = [{**GOOD[0], "source": "data"}]  # values from several files there
    _, problems = derive.import_answer(
        ws, settings.load(ws), reply(folder, script=None), "T",
                                       approve=lambda p, c: True)  # fmt: skip
    assert {p.kind for p in problems} == {"no-script"}
    _, problems = derive.import_answer(
        ws, settings.load(ws), reply([], [{"for": "V1", "reason": "no data"}], script=None), "T",
        approve=lambda p, c: pytest.fail("nothing to run"),
    )  # fmt: skip
    assert problems == [] and derive.cannot(ws) == {"R1.1.a": {"V1": "no data"}}
    assert derive.derived_observations(ws, settings.load(ws)) == {}


def test_a_claim_stated_in_words_may_say_why_it_cannot_be_checked(ws):
    derive.write_handoffs(ws, settings.load(ws))
    why = [{"for": "V1", "reason": "no data"}, {"for": "V9", "reason": "r"}]
    _, problems = derive.import_answer(
        ws, settings.load(ws), reply([], why, script=None), "T",
        approve=lambda p, c: True,
    )  # fmt: skip
    assert [p.kind for p in problems] == ["unknown-value"]
    why = [{"for": "V1", "reason": "no data"}, {"for": "condition", "reason": "r"}]
    _, problems = derive.import_answer(
        ws, settings.load(ws), reply([], why, script=None), "T",
        approve=lambda p, c: pytest.fail("nothing to run"),
    )  # fmt: skip
    assert problems == []
    assert derive.cannot(ws) == {"R1.1.a": {"V1": "no data", "condition": "r"}}


def test_the_example_in_the_instructions_is_an_answer():
    text = instructions.load("derive").text
    block = text[text.index("```json") :]
    answer, script = derive.parse_answer(block)
    assert answer.instructions == instructions.load("derive").label
    assert script is None


def test_import_on_the_command_line_asks_before_a_flagged_script(
    ws, monkeypatch, capsys
):
    cli.main(["handoff", "derive", str(ws)])
    (ws / "reply.txt").write_text(reply(GOOD, script="import os\n" + SCRIPT))
    questions = []
    monkeypatch.setattr("builtins.input", lambda q: questions.append(q) or "n")
    cli.main(["import", "derive", str(ws / "reply.txt"), "--by", "T", str(ws)])
    assert "Not run" in capsys.readouterr().out
    assert "line 1: imports os" in questions[0]
    monkeypatch.setattr("builtins.input", lambda q: "y")
    cli.main(["import", "derive", str(ws / "reply.txt"), "--by", "T", str(ws)])
    assert "1 value recomputed" in capsys.readouterr().out


def test_a_script_the_checks_pass_runs_without_asking(ws, monkeypatch, capsys):
    cli.main(["handoff", "derive", str(ws)])
    (ws / "reply.txt").write_text(reply(GOOD))
    monkeypatch.setattr("builtins.input", lambda q: pytest.fail("asked"))
    cli.main(["import", "derive", str(ws / "reply.txt"), "--by", "T", str(ws)])
    out = capsys.readouterr().out
    assert "(it passed the script checks)" in out and "1 value recomputed" in out


def concerns(body):
    head = "from pathlib import Path\nHERE = Path(__file__).resolve().parent\n"
    return [c.split(": ", 1)[1] for c in derive.script_concerns(head + body)]


def test_the_script_checks_flag_what_a_person_should_look_at():
    assert concerns(SCRIPT) == []
    assert concerns("(HERE / 'output' / 'x.txt').write_text('1')") == []
    assert concerns("import numpy as np\nnp.save(HERE / 'out.npy', [1])") == []
    assert concerns("import subprocess") == [
        "imports subprocess, which starts other programs"
    ]
    assert concerns("from os import remove") == [
        "imports os.remove, which can start programs and change or delete files"
    ]
    [unknown] = concerns("from rigoraudit import derive")
    assert unknown.startswith("imports rigoraudit.derive, which is not one of")
    assert concerns("(HERE.parent / 'materials' / 'x').write_text('1')") == [
        "writes outside derivations/"
    ]
    assert concerns("open(HERE.parent / 'x', 'w')") == ["writes outside derivations/"]
    assert concerns("open(HERE.parent / 'x')") == []  # reading the workspace
    assert concerns("import h5py\nh5py.File(HERE.parent / 'x.nc', 'r')") == []
    assert concerns("import h5py\nh5py.File(HERE.parent / 'x.nc')") == []
    assert concerns("import h5py\nh5py.File(HERE.parent / 'x.nc', 'a')") == [
        "writes outside derivations/"
    ]
    read = "import tarfile\nt = tarfile.open(HERE.parent / 'max.tar.gz')\n"
    assert concerns(read + "t.extractfile('a.csv').read()") == []
    assert concerns(read + "t.extractall()") == [
        "unpacks files from an archive (extractall)"
    ]
    assert concerns("import gzip\ngzip.open(HERE.parent / 'x.gz', 'wt')") == [
        "writes outside derivations/"
    ]
    assert concerns("import zipfile\nzipfile.ZipFile(HERE.parent / 'x.zip', 'w')") == [
        "writes outside derivations/"
    ]
    assert concerns("p = HERE.parent.parent / 'other'\nprint(p)") == [
        "reaches outside the audit's workspace"
    ]
    assert concerns("x = '/home/someone/data.mat'") == [
        "names a place on this computer by its full path (/home/someone/data.mat)"
    ]
    assert concerns("(HERE / 'x').unlink()") == [
        "deletes, renames, or changes a file (unlink)"
    ]
    assert concerns("eval('1')") == ["runs text as code (eval)"]
    assert concerns("def f(p):\n    p.write_text('1')") == [
        "writes to a file whose place the check cannot work out"
    ]
    assert concerns("'a b'.replace('a', 'b')") == []


def test_a_script_may_start_matlab_if_the_manifest_allows_it():
    head = "from pathlib import Path\n"
    script = head + "from rigoraudit import matlab\nmatlab.run('x = 1', Path('.'))\n"
    [concern] = derive.script_concerns(script)
    assert concern.startswith("line 2: imports rigoraudit.matlab, which starts MATLAB")
    assert derive.script_concerns(script, ["matlab"]) == []
    assert derive.script_concerns("import subprocess", ["matlab"]) == [
        "line 1: imports subprocess, which starts other programs"
    ]


def test_a_flagged_script_asks_even_in_auto(ws):
    derive.write_handoffs(ws, settings.load(ws))
    asked = []
    _, problems = derive.import_answer(
        ws,
        settings.load(ws),
        reply(GOOD, script="import shutil\n" + SCRIPT),
        "T",
        approve=lambda p, c: asked.append(c) or True,
    )
    assert problems == []
    assert asked == [["line 1: imports shutil, which can copy, move, or delete files"]]


TWO = "Mice were correct on 75% of trials in block A, over 4 trials."
BOTH = """from pathlib import Path
import json

from rigoraudit.values import write_values

HERE = Path(__file__).resolve().parent
WORKSPACE = HERE.parent
DATA = WORKSPACE / "materials" / "data" / "trials.json"
trials = json.loads(DATA.read_text())
for claim, values in [("R1.1.a", {"accuracy": 100 * sum(trials) / len(trials)}),
                      ("R1.1.b", {"trials": len(trials)})]:
    write_values(HERE / "output" / "values" / f"{claim}.json", values,
                 script=Path(__file__), inputs=[DATA], workspace=WORKSPACE)
"""


@pytest.fixture
def ws_two(tmp_path):
    """A workspace with two claims in one paragraph, each split into facets."""
    ws = tmp_path / "audit"
    (ws / "materials" / "data").mkdir(parents=True)
    (ws / "materials" / "data" / "trials.json").write_text("[1, 1, 1, 0]")
    (ws / "audit.yaml").write_text("materials:\n  manuscript:\n    path: paper.pdf\n")
    para = ws / "work" / "extract" / "paragraphs.json"
    para.parent.mkdir(parents=True)
    para.write_text(json.dumps([{"section": "Results", "paragraph": 1, "text": TWO}]))
    segment.write_handoffs(ws, ("Results",))
    _, problems = segment.import_answer(ws, json.dumps({
        "instructions": "segment v2", "claims": [
        {"id": "R1.1.a", "paragraph": "R1.1", "type": "new_result",
         "quote": "Mice were correct on 75% of trials in block A"},
        {"id": "R1.1.b", "paragraph": "R1.1", "type": "new_result",
         "quote": "over 4 trials"}]}), "T")  # fmt: skip
    assert not problems
    decompose.write_handoffs(ws)
    _, problems = decompose.import_answer(ws, json.dumps({
        "instructions": "decompose v3", "claims": [
        {"id": "R1.1.a", "facets": [{"facet": "quantity", "quote": "correct on 75% of trials",
         "states": "s", "values": [{"name": "accuracy", "printed": "75%"}]}]},
        {"id": "R1.1.b", "facets": [{"facet": "population", "quote": "over 4 trials",
         "states": "s", "values": [{"name": "trials", "printed": "4"}]}]}]}), "T")  # fmt: skip
    assert not problems
    return ws


def both(*claims):
    answer = {"instructions": "derive v4", "claims": list(claims)}
    return f"```json\n{json.dumps(answer)}\n```\n\n```python\n{BOTH}```\n"


A = {"claim": "R1.1.a", "values": [{"for": "V1", "key": "accuracy", "how": "recomputed",
     "source": "data/trials.json", "derivation": "percent correct"}]}  # fmt: skip
B = {"claim": "R1.1.b", "values": [{"for": "V2", "key": "trials", "how": "recomputed",
     "source": "data/trials.json", "derivation": "number of trials"}]}  # fmt: skip


def test_claims_share_a_task_and_one_script(ws_two):
    s = settings.load(ws_two)
    assert len(derive.plan_handoffs(ws_two, s, max_claims=1)) == 2
    [path] = derive.write_handoffs(ws_two, s)
    text = path.read_text()
    assert text.count("## Paragraph R1.1") == 1 and "the 2 claims below" in text
    assert "`V1` (quantity)" in text and "`V2` (population)" in text
    _, problems = derive.import_answer(
        ws_two, settings.load(ws_two), both(A), "T", approve=lambda p, c: True
    )
    assert [p.kind for p in problems] == ["claim-missing"]
    asked = []
    _, problems = derive.import_answer(
        ws_two,
        dataclasses.replace(settings.load(ws_two), derive_run="ask"),
        both(A, B),
        "T",
        approve=lambda p, c: asked.append(p) or True,
    )
    assert problems == []
    assert asked == [ws_two / "derivations" / "R1.1.a_to_R1.1.b.py"]
    found = derive.derived_observations(ws_two, settings.load(ws_two))
    assert found["R1.1.b"][Facet.POPULATION][0].values[0].value == 4
    assert found["R1.1.a"][Facet.QUANTITY][0].values[0].value == 75.0


TESTED = "12 mice ran faster in block A than in block B, t(10) = 2.50, p = 0.031."
TEST_SCRIPT = """from pathlib import Path

from rigoraudit.values import write_values

HERE = Path(__file__).resolve().parent
WORKSPACE = HERE.parent
DATA = WORKSPACE / "materials" / "data" / "trials.json"
write_values(
    HERE / "output" / "values" / "R1.1.a.json",
    {"test_1": {"n": 12, "unit": "session",
                "groups": {"A": [1, 2, 2, 3, 3, 9], "B": [1, 1, 2, 2, 3, 3]}}},
    script=Path(__file__),
    inputs=[DATA],
    workspace=WORKSPACE,
)
"""


@pytest.fixture
def ws_test(tmp_path):
    """A workspace whose one claim reports a t test, with its data."""
    ws = tmp_path / "audit"
    (ws / "materials" / "data").mkdir(parents=True)
    (ws / "materials" / "data" / "trials.json").write_text("[]")
    (ws / "audit.yaml").write_text("materials:\n  manuscript:\n    path: paper.pdf\n")
    para = ws / "work" / "extract" / "paragraphs.json"
    para.parent.mkdir(parents=True)
    para.write_text(
        json.dumps([{"section": "Results", "paragraph": 1, "text": TESTED}])
    )
    segment.write_handoffs(ws, ("Results",))
    _, problems = segment.import_answer(ws, json.dumps({
        "instructions": "segment v2", "claims": [{"id": "R1.1.a", "paragraph": "R1.1",
        "type": "new_result", "quote": TESTED.rstrip(".")}]}), "T")  # fmt: skip
    assert not problems
    decompose.write_handoffs(ws)
    _, problems = decompose.import_answer(ws, json.dumps({
        "instructions": "decompose v3", "claims": [{"id": "R1.1.a", "facets": [
        {"facet": "population", "quote": "12 mice", "states": "s",
         "values": [{"name": "mice", "printed": "12"}]},
        {"facet": "analysis", "quote": "t(10) = 2.50, p = 0.031", "states": "s",
         "values": [{"name": "t", "printed": "2.50"}, {"name": "p", "printed": "0.031"}]}],
        "tests": [{"quote": "t(10) = 2.50, p = 0.031", "statistic": "t",
                   "value": "2.50", "df": ["10"], "p": "= 0.031", "n": "12",
                   "n_quote": "12 mice", "design": "independent"}]}]}), "T")  # fmt: skip
    assert not problems, problems
    derive.write_handoffs(ws, settings.load(ws))
    return ws


def reply_for_test(**test):
    entry = {"test": 1, "n": "test_1/n", "unit": "test_1/unit",
             "source": "data/trials.json", "groups": "test_1/groups"} | test  # fmt: skip
    answer = {"instructions": "derive v4", "claims": [{"claim": "R1.1.a",
              "cannot": [{"for": f"V{i}", "reason": "r"} for i in (1, 2, 3)],
              "tests": [entry]}]}  # fmt: skip
    return f"```json\n{json.dumps(answer)}\n```\n\n```python\n{TEST_SCRIPT}```\n"


def test_the_handoff_lists_the_tests_and_what_is_wrong_is_sent_back(ws_test):
    [h] = derive.pending_handoffs(ws_test)
    assert "- Test 1: t(10) = 2.50, p = 0.031" in derive.render_handoff(h)
    s = settings.load(ws_test)
    _, problems = derive.import_answer(
        ws_test, s, reply_for_test(test=2, stated_unit={"says": "mouse", "quote": "rats"}),
        "T", approve=lambda p, c: True,
    )  # fmt: skip
    assert {p.kind for p in problems} >= {"unknown-test", "bad-unit", "quote-not-found"}


def test_n_and_unit_are_compared_with_the_text_and_the_data_described(ws_test):
    from rigoraudit import stats
    from rigoraudit.schema import Status

    s = settings.load(ws_test)
    reply = reply_for_test(stated_unit={"says": "animal", "quote": "12 mice"})
    saved, problems = derive.import_answer(
        ws_test, s, reply, "T", approve=lambda p, c: True
    )
    assert problems == [] and saved is not None
    found = {f.scope: f for f in stats.derived_test_findings(ws_test, s)}
    assert found["N in the data"].status is Status.CONSISTENT
    assert found["unit of analysis"].status is Status.DIFFERS
    [context] = stats.test_context(ws_test)
    assert context.assumes.startswith("Assumes independent observations")
    assert context.data.startswith("Data: A, N = 6, skew ")
    assert "variance ratio 10 (largest to smallest)" in context.data


def test_a_saved_unit_must_be_one_of_the_words(ws_test):
    bad = reply_for_test().replace('"unit": "session"', '"unit": "mouse"')
    _, problems = derive.import_answer(
        ws_test, settings.load(ws_test), bad.replace(
            '"session"', '"mouse"'), "T", approve=lambda p, c: True
    )  # fmt: skip
    assert [p.kind for p in problems] == ["bad-unit"]
