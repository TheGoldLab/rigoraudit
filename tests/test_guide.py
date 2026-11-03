# Copyright (c) 2026, Joshua I. Gold
# SPDX-License-Identifier: BSD-2-Clause

import dataclasses
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from conftest import make_pdf

from rigoraudit import (
    api,
    docs,
    feedback,
    guide,
    handoffs,
    instructions,
    materials,
    settings,
    trace,
)
from rigoraudit.extract import write_text_layer
from rigoraudit.sections import Heading

CODE = """def accuracy(trials):
    kept = [t for t in trials if t["rt"] <= 2.0]
    return 100 * sum(t["correct"] for t in kept) / len(kept)
"""
README = "Run analysis.py with Python 3.11.\n"
METHODS = "Accuracy is the percent correct."
RESULTS = "Accuracy was 80% in block A."
TITLE = "Accuracy in two blocks"
DERIVE = """import json
from pathlib import Path

from rigoraudit.values import write_values

HERE = Path(__file__).resolve().parent
WORKSPACE = HERE.parent
DATA = WORKSPACE / "materials" / "data" / "correct.json"
correct = json.loads(DATA.read_text())
write_values(
    HERE / "output" / "values" / "R1.1.a.json",
    {"accuracy": 100 * sum(correct) / len(correct)},
    script=Path(__file__),
    inputs=[DATA],
    workspace=WORKSPACE,
)
"""


def git(cwd, *args):
    return subprocess.run(
        ["git", "-c", "user.name=T", "-c", "user.email=t@example.org", *args],
        cwd=cwd, check=True, capture_output=True, text=True,
    ).stdout.strip()  # fmt: skip


@pytest.fixture
def upstream(tmp_path):
    """The authors' repository, with a later commit the paper did not use."""
    repo = tmp_path / "upstream"
    repo.mkdir()
    (repo / "README.md").write_text(README, encoding="utf-8")
    (repo / "analysis.py").write_text(CODE, encoding="utf-8")
    git(repo, "init", "-q")
    git(repo, "add", ".")
    git(repo, "commit", "-q", "-m", "paper version")
    commit = git(repo, "rev-parse", "HEAD")
    (repo / "analysis.py").write_text(CODE.replace("2.0", "3.0"), encoding="utf-8")
    git(repo, "commit", "-qam", "later")
    return repo, commit


class Script:
    """Answers the guide's questions in order, and keeps what it said."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.said = []

    def ask(self, question):
        self.said.append(question)
        return self.answers.pop(0)

    def say(self, text):
        self.said.append(text)

    @property
    def text(self):
        return "\n".join(self.said)


def run(ws, *answers):
    script = Script(*answers)
    outcome = guide.Guide(ws, ask=script.ask, say=script.say).run()
    return outcome, script


def replies(ws):
    """The assistant's replies for each step, saved as files."""
    out = {}

    def save(name, answer):
        path = ws / f"{name}.txt"
        path.write_text(json.dumps(answer), encoding="utf-8")
        out[name] = str(path)

    nothing = [h.value for h in docs.Heading if h.value not in ("run", "software")]
    save("docs", {"instructions": "docs v1", "files": [{"file": "code/README.md",
        "notes": [{"heading": "run", "quote": "Run analysis.py", "states": "s"},
                  {"heading": "software", "quote": "Python 3.11", "states": "s"}],
        "says_nothing": nothing}]})  # fmt: skip
    save("segment", {"instructions": "segment v2", "claims": [
        {"id": "R1.1.a", "paragraph": "R1.1", "type": "new_result",
         "quote": "Accuracy was 80% in block A"}]})  # fmt: skip
    save("decompose", {"instructions": "decompose v3", "claims": [{"id": "R1.1.a",
        "facets": [{"facet": "quantity", "quote": "80%", "states": "s",
                    "values": [{"name": "accuracy", "printed": "80%"}]}]}]})  # fmt: skip
    save("trace", {"instructions": "trace v4", "claims": [{"id": "R1.1.a", "facets": [
        {"facet": "quantity", "methods": [], "code": [{"file": "analysis.py",
         "lines": [2, 2], "states": "s",
         "quote": '    kept = [t for t in trials if t["rt"] <= 2.0]'}]}]}]})  # fmt: skip
    data = ws / "materials" / "data" / "correct.json"
    data.parent.mkdir(parents=True, exist_ok=True)
    data.write_text("[1, 1, 1, 1, 0]", encoding="utf-8")
    answer = {"instructions": "derive v4", "claims": [{"claim": "R1.1.a", "values": [
        {"for": "V1", "key": "accuracy", "how": "recomputed",
         "source": "data/correct.json", "derivation": "percent correct"}]}]}  # fmt: skip
    script = DERIVE
    path = ws / "derive.txt"
    path.write_text(
        f"{json.dumps(answer)}\n\n```python\n{script}```\n", encoding="utf-8"
    )
    out["derive"] = str(path)
    save("compare", {"instructions": "compare v4", "claims": [{"claim": "R1.1.a",
        "findings": [{"facet": "quantity", "observations": ["O1", "O3"],
         "basis": "reported_precision",
         "comparisons": [{"kind": "precision", "stated": ["O1.v1"], "observed": ["O3.v1"]}],
         "summary": "The Results state 80%. The data give 80%."}]}]})  # fmt: skip
    save("header", {"instructions": "header v1", "heading": "Test (2026)",
        "title": TITLE, "covers": "The Results.", "materials": [
            {"name": "Manuscript", "text": "m"}, {"name": "Code", "text": "c"}]})  # fmt: skip
    return out


def fill_in(ws, repo, commit):
    (ws / "audit.yaml").write_text(
        guide.TEMPLATE.replace('repository: ""', f"repository: {repo}").replace(
            'commit: ""', f"commit: {commit}"
        ),
        encoding="utf-8",
    )
    (ws / "materials" / "manuscript").mkdir()
    (ws / "materials" / "manuscript" / "paper.pdf").write_bytes(b"%PDF")


def extract(ws):
    path = ws / "work" / "extract" / "paragraphs.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps([
        {"section": "Methods", "paragraph": 1, "text": METHODS},
        {"section": "Results", "paragraph": 1, "text": RESULTS},
    ]), encoding="utf-8")  # fmt: skip
    pages = [f"{TITLE}\nMethods\n{METHODS}\nResults\n{RESULTS}\n"]
    outline = [Heading("Methods", 0, 1), Heading("Results", 0, 1)]
    write_text_layer(path.parent, pages, outline, "paper.pdf")


def test_a_whole_audit_from_an_empty_folder(tmp_path, upstream):
    repo, commit = upstream
    ws = tmp_path / "audit"

    outcome, script = run(ws)
    assert outcome == "made workspace"
    assert (ws / "audit.yaml").read_text(encoding="utf-8") == guide.TEMPLATE
    assert settings.load(ws).manuscript == "manuscript/paper.pdf"

    fill_in(ws, repo, commit)
    outcome, script = run(ws)
    assert outcome == "waiting for materials"
    assert (
        "downloading it from" in script.text
        and "could not read the paper's text" in script.text
    )
    code = ws / "materials" / "code"
    assert git(code, "rev-parse", "HEAD") == commit
    assert "<= 2.0" in (code / "analysis.py").read_text(
        encoding="utf-8"
    )  # the paper's version
    assert "`analysis.py` (code" in (ws / materials.LIST).read_text(encoding="utf-8")
    assert "Look there before recording anything as missing." in script.text

    extract(ws)
    r = replies(ws)
    outcome, script = run(
        ws,
        "1",
        "Test assistant",
        r["docs"],
        r["segment"],
        r["decompose"],
        r["trace"],
        r["derive"],
        r["compare"],
        r["header"],
    )
    assert outcome == "finished", script.text
    assert "<h1>Test (2026)</h1>" in (ws / "report" / "audit.html").read_text(
        encoding="utf-8"
    )
    assert "Built the record from the accepted answers" in script.text
    assert (
        "  [x] compare\n  [x] crosscheck\n  [x] header" in script.text
    )  # listed after the run
    for step in (
        "docs",
        "segment",
        "decompose",
        "trace",
        "derive",
        "compare",
        "header",
    ):
        assert f"{step}: done." in script.text
    assert trace.trace_observations(ws, settings.load(ws))["R1.1.a"]

    # the run's own feedback report counts every step, and nothing was sent
    report = (ws / feedback.REPORT).read_text(encoding="utf-8")
    assert "the guide ran" in report and "| audit |  |  | finished |" in report
    assert report.count("| accepted |") == 7
    assert "(it passed the script checks)" in script.text

    outcome, script = run(ws)
    assert outcome == "finished"
    assert "  [x] trace\n  [x] derive\n  [x] compare" in script.text
    assert "older instructions" not in script.text

    # an answer accepted before the instructions changed is kept, with a warning
    path = next((ws / "work" / "decompose" / "answers").glob("*.json"))
    saved = json.loads(path.read_text(encoding="utf-8"))
    saved["answer"]["instructions"] = "decompose v0"
    path.write_text(json.dumps(saved), encoding="utf-8")
    assert handoffs.old_answers(ws, "decompose") == {path.stem: "decompose v0"}
    outcome, script = run(ws)
    assert outcome == "finished"
    assert "  decompose: 1 answer followed decompose v0;" in script.text


def test_problems_are_given_to_paste_back_and_the_guide_can_stop(tmp_path, upstream):
    repo, commit = upstream
    ws = tmp_path / "audit"
    run(ws)
    fill_in(ws, repo, commit)
    extract(ws)
    r = replies(ws)
    bad = ws / "bad.txt"
    bad.write_text(
        json.dumps({"instructions": "docs v1", "files": []}), encoding="utf-8"
    )

    outcome, script = run(ws, "1", "Test assistant", "missing.txt", str(bad), "")
    assert outcome == "stopped"
    assert "There is no file at missing.txt." in script.text
    assert "Please correct these problems" in script.text
    assert "code/README.md has no answer" in script.text

    # picks up where it stopped, without asking again who answers
    outcome, script = run(ws, r["docs"], "")
    assert outcome == "stopped"
    assert "Which kind of assistant" not in script.text and "docs: done." in script.text


def test_a_commit_that_is_not_there_leaves_nothing_behind(tmp_path, upstream):
    repo, _ = upstream
    ws = tmp_path / "audit"
    run(ws)
    fill_in(ws, repo, "0" * 40)
    outcome, script = run(ws)
    assert outcome == "waiting for materials"
    assert "The download did not work." in script.text
    assert not (ws / "materials" / "code").exists()


def test_the_guide_extracts_the_paragraphs_and_offers_to_stop(tmp_path, upstream):
    repo, commit = upstream
    ws = tmp_path / "audit"
    run(ws)
    fill_in(ws, repo, commit)
    paper = ws / "materials" / "manuscript" / "paper.pdf"
    paper.write_bytes(make_pdf([["Methods", METHODS, "Results", RESULTS]]))
    outcome, script = run(ws, "1", "Test assistant", "n")
    assert outcome == "waiting for materials"
    assert "Wrote 2 paragraphs" in script.text and "best guess" in script.text
    assert "Go on to the next step now?" in script.text
    paras = json.loads(
        (ws / "work" / "extract" / "paragraphs.json").read_text(encoding="utf-8")
    )
    assert [(p["section"], p["text"]) for p in paras] == [
        ("Methods", METHODS),
        ("Results", RESULTS),
    ]

    # next time the paragraphs are there, so the guide goes on
    outcome, script = run(ws, "")
    assert "Extracting" not in script.text and "  [ ] docs" in script.text


def test_a_coding_assistant_is_not_stopped_to_look_over_paragraphs(tmp_path, upstream):
    repo, commit = upstream
    ws = tmp_path / "audit"
    run(ws)
    fill_in(ws, repo, commit)
    paper = ws / "materials" / "manuscript" / "paper.pdf"
    paper.write_bytes(make_pdf([["Methods", METHODS, "Results", RESULTS]]))
    _, script = run(ws, "2", "Test assistant")
    assert "best guess" in script.text and "Go on to the next" not in script.text
    assert "  [ ] docs" in script.text


def test_the_guide_offers_to_check_doubtful_breaks(tmp_path, upstream):
    repo, commit = upstream
    ws = tmp_path / "audit"
    run(ws)
    fill_in(ws, repo, commit)
    run(ws)  # download the code
    path = ws / "work" / "extract" / "paragraphs.json"
    path.parent.mkdir(parents=True)
    first, second = RESULTS.rstrip("."), "and 70% in block B."
    path.write_text(json.dumps([
        {"section": "Methods", "paragraph": 1, "text": METHODS, "approximate": True},
        {"section": "Results", "paragraph": 1, "text": first, "approximate": True},
        {"section": "Results", "paragraph": 2, "text": second, "approximate": True},
    ]), encoding="utf-8")  # fmt: skip
    answer = ws / "breaks.txt"
    answer.write_text(json.dumps({"instructions": "breaks v2",
        "decisions": [{"spot": "B1", "new_paragraph": False}]}), encoding="utf-8")  # fmt: skip

    outcome, script = run(ws, "1", "Test assistant", "y", str(answer), "")
    assert outcome == "stopped"
    assert "unsure about 1 paragraph break" in script.text
    assert "breaks: done." in script.text
    paras = json.loads(path.read_text(encoding="utf-8"))
    assert [p["text"] for p in paras] == [METHODS, f"{first} {second}"]

    # a skipped check is not offered again
    path.write_text(
        json.dumps([*paras, {**paras[1], "paragraph": 2, "text": "and"}]),
        encoding="utf-8",
    )
    (ws / "work" / "breaks" / "answers" / "breaks.json").unlink()
    outcome, script = run(ws, "n", "")
    assert "unsure about" in script.text
    outcome, script = run(ws, "")
    assert "unsure about" not in script.text and "  [x] breaks" in script.text


def test_code_on_osf_is_fetched_without_its_large_files(tmp_path, monkeypatch):
    from functools import partial

    from test_osf import FakeOsf

    from rigoraudit import osf

    fake = FakeOsf()
    monkeypatch.setattr(osf, "MAX_BYTES", 1000)
    monkeypatch.setattr(
        osf, "list_files", partial(osf.list_files, get_json=fake.get_json)
    )
    monkeypatch.setattr(osf, "fetch", partial(osf.fetch, get_file=fake.get_file))
    ws = tmp_path / "audit"
    run(ws)
    fill_in(ws, "https://osf.io/ab3cd/", "")
    _, script = run(ws)
    assert "OSF project ab3cd has 3 files (2.0 KB)" in script.text
    assert "leave out the 1 larger file (usually data)" in script.text
    assert "2 downloaded now. Left out 1 file" in script.text
    code = ws / "materials" / "code"
    assert (code / "code" / "fit.py").is_file() and (code / osf.LISTING).is_file()
    assert settings.load(ws).code.commit is None

    # a download that stopped is offered again; the files there are kept
    (code / osf.LISTING).unlink()
    fake.downloads.clear()
    _, script = run(ws, "y", "n")
    assert "may not have finished" in script.text
    assert "2 already there" in script.text and fake.downloads == []

    # answering no uses the folder as it is
    (code / osf.LISTING).unlink()
    _, script = run(ws, "n", "n")
    assert "may not have finished" in script.text and "Downloaded" not in script.text
    assert not (code / osf.LISTING).exists()


def test_the_guide_checks_the_record_and_writes_the_report(tmp_path):
    example = Path(__file__).resolve().parents[1] / "examples" / "example-audit"
    ws = tmp_path / "example-audit"
    shutil.copytree(example, ws, ignore=shutil.ignore_patterns("review", "report"))
    script = Script()
    g = guide.Guide(ws, ask=script.ask, say=script.say)
    assert g.check_and_report(settings.load(ws)) == "finished", script.text
    assert "All checks pass." in script.text and "rigoraudit review" in script.text
    assert (ws / "report" / "audit.html").is_file()

    # a quote the paper does not have fails the check, and no report is written
    (ws / "report" / "audit.html").unlink()
    record = ws / "record" / "record.json"
    data = json.loads(record.read_text(encoding="utf-8"))
    data["claims"][0]["anchor"]["quote"] += " and more"
    record.write_text(json.dumps(data), encoding="utf-8")
    assert g.check_and_report(settings.load(ws)) == "check failed"
    assert not (ws / "report" / "audit.html").exists()

    record.unlink()
    assert g.check_and_report(settings.load(ws)) == "waiting for the record"
    assert "builds its record with its own record/record.py" in script.text


class Model:
    """Stands in for a model in API mode: answers each task with the saved
    reply for its step, after a first bad answer to the docs task."""

    def __init__(self, replies, down=False):
        self.replies, self.down, self.asked = replies, down, []

    def __call__(self, model):
        self.model = model
        return self

    def ask(self, text):
        if self.down:
            raise api.Unavailable("The tool could not reach the API.")
        self.asked.append(text)
        if text.startswith("-" * 72):  # problems sent back
            return Path(self.replies["docs"]).read_text(encoding="utf-8")
        step = re.search(r"# Your task: ([a-z]+)", text)[1]
        if step == "docs" and len(self.asked) == 1:
            return json.dumps({"instructions": "docs v1", "files": []})
        return Path(self.replies[step]).read_text(encoding="utf-8")


def test_in_api_mode_the_tool_asks_the_model_and_sends_problems_back(
    tmp_path, upstream
):
    repo, commit = upstream
    ws = tmp_path / "audit"
    run(ws)
    fill_in(ws, repo, commit)
    extract(ws)
    model = Model(replies(ws))
    script = Script("3", "y", *["y"] * 7)
    g = guide.Guide(ws, ask=script.ask, say=script.say, talk=model)
    assert g.run() == "finished", script.text
    assert model.model == settings.MODEL
    assert "sending them back" in script.text
    assert "(it passed the script checks)" in script.text
    assert len(list((ws / "work" / "docs" / "replies").glob("*-2.txt"))) == 1
    # the trace handoff carries an index of the code, since the model cannot browse
    assert any(
        "Code index" in t or "index of" in t for t in model.asked if "trace" in t
    )
    record = json.loads((ws / "record" / "record.json").read_text(encoding="utf-8"))
    assert record["drafted_by"]["name"] == f"{settings.MODEL} (API)"


def test_api_mode_warns_of_the_cost_and_can_be_declined(tmp_path, upstream):
    repo, commit = upstream
    ws = tmp_path / "audit"
    run(ws)
    fill_in(ws, repo, commit)
    extract(ws)
    outcome, script = run(ws, "x", "3", "n", "1", "Test assistant", "")
    assert outcome == "stopped"
    assert script.text.count("Which kind of assistant") == 3  # asked again
    assert "substantial amount of money" in script.text
    assert "Turn on API mode, and pay for it?" in script.text
    choices = json.loads((ws / guide.CHOICES).read_text(encoding="utf-8"))
    assert choices == {"mode": "paste", "by": "Test assistant"}


def test_when_the_api_cannot_be_reached_the_user_takes_over(tmp_path, upstream):
    repo, commit = upstream
    ws = tmp_path / "audit"
    run(ws)
    fill_in(ws, repo, commit)
    extract(ws)
    r = replies(ws)
    script = Script("y", "3", "y", "y", r["docs"], "n", "")
    g = guide.Guide(ws, ask=script.ask, say=script.say, talk=Model(r, down=True))
    assert g.run() == "stopped"
    assert (
        "could not reach the API. Doing the rest of this step by hand." in script.text
    )
    assert "docs: done." in script.text


def test_a_coding_assistant_works_through_the_inbox(tmp_path, upstream):
    repo, commit = upstream
    ws = tmp_path / "audit"
    run(ws)
    fill_in(ws, repo, commit)
    extract(ws)
    r = replies(ws)

    def go(*answers, person=False):
        script = Script(*answers)
        g = guide.Guide(ws, ask=script.ask, say=script.say, interactive=person)
        return g.run(), script.text

    def answer_waiting(bad=False):
        """Write the reply for every task waiting, as the assistant would."""
        for step in (
            "docs",
            "segment",
            "decompose",
            "trace",
            "derive",
            "compare",
            "header",
        ):
            for task in (ws / "work" / step / "handoffs").glob("*.md"):
                if not (ws / "work" / step / "answers" / f"{task.stem}.json").exists():
                    inbox = ws / "work" / step / guide.INBOX
                    assert inbox.is_dir()  # the guide makes it
                    text = "{}" if bad else Path(r[step]).read_text(encoding="utf-8")
                    (inbox / f"{task.stem}.txt").write_text(text, encoding="utf-8")

    outcome, text = go("2", "Test assistant", person=True)
    assert outcome == "waiting" and "Tell it:" in text
    outcome, text = go()  # the assistant's first run: no questions
    assert outcome == "waiting"
    assert re.search(
        r"work/docs/handoffs/(docs-1\S*)\.md -> work/docs/inbox/\1\.txt", text
    )

    answer_waiting(bad=True)
    go()
    [note] = (ws / "work" / "docs" / guide.INBOX).glob(f"*{guide.PROBLEMS}")
    assert "Please correct these problems" in note.read_text(encoding="utf-8")
    outcome, text = go()  # the next run says which reply to correct
    assert f"correct it as work/docs/inbox/{note.name} says" in text
    outcome, text = go(person=True)
    assert "1 with problems in their replies" in text

    for _ in range(4):  # docs, segment, decompose, trace: one run each
        answer_waiting()
        outcome, text = go()
    assert not note.exists()
    assert [p.suffix for p in (ws / "work" / "docs" / "replies").iterdir()] == [".txt"]
    assert (ws / trace.METHODS).is_file()  # once, not in each trace task
    assert "derive: 1 task waiting" in text

    answer_waiting()
    reply = ws / "work" / "derive" / guide.INBOX / "derive-R1.1.a.txt"
    reply.write_text(
        reply.read_text(encoding="utf-8").replace("import json", "import json, os"),
        encoding="utf-8",
    )
    outcome, text = go()  # the script checks flag it, so it waits
    assert "1 script passed the checks and waits for the user" in text
    assert "imports os, which can start programs" in text
    assert "Accepted" not in text
    assert not (ws / "derivations" / "output").exists()
    outcome, text = go("y", person=True)
    assert "Running derivations/R1.1.a.py" in text
    assert text.count("Accepted derive") == 1
    assert "compare: 1 task wait for your assistant" in text

    answer_waiting()
    outcome, text = go()
    assert "header: 1 task waiting" in text
    answer_waiting()
    outcome, text = go()
    assert outcome == "finished", text
    assert (ws / "record" / "record.json").is_file()


def test_tasks_still_waiting_are_listed_beside_a_script_that_waits(tmp_path):
    @dataclasses.dataclass
    class Task:
        name: str

    ws = tmp_path / "audit"
    inbox = ws / "work" / "derive" / guide.INBOX
    inbox.mkdir(parents=True)
    (inbox / "derive-1.txt").write_text("a script", encoding="utf-8")
    script = ws / "derivations" / "R1.py"
    script.parent.mkdir()
    script.write_text("print(1)\n", encoding="utf-8")
    g = guide.Guide(ws, interactive=False, clip=None)
    g.choose("mode", "files")

    def import_answer(text, name):
        assert g.approve_run(script, []) is False  # held for the user
        return None, []

    tasks = [Task("derive-1"), Task("derive-2")]
    with pytest.raises(guide.Waiting) as w:
        g.read_inbox("derive", lambda: tasks, import_answer, None)
    assert "1 script passed the checks" in str(w.value)
    assert "work/derive/handoffs/derive-2.md -> " in str(w.value)
    assert "derive-1.md" not in str(w.value)


def test_a_step_hands_off_its_next_round_once_a_round_is_answered(tmp_path):
    # segment: the legends and tables follow once every Results paragraph is done
    @dataclasses.dataclass
    class Task:
        name: str

    ws = tmp_path / "audit"
    inbox = ws / "work" / "segment" / guide.INBOX
    inbox.mkdir(parents=True)
    (inbox / "segment-R1.txt").write_text("a reply", encoding="utf-8")
    g = guide.Guide(ws, interactive=False, clip=None)
    g.choose("mode", "files")
    rounds, written, answered = [["segment-R1"], ["segment-F1"]], [], set()

    def write():
        if rounds and set(written) <= answered:
            written.extend(rounds.pop(0))
        return written

    def import_answer(text, name):
        answered.add(name)
        return None, []

    def pending():
        return [Task(n) for n in written if n not in answered]

    with pytest.raises(guide.Waiting) as w:
        g.work_through("segment", write, pending, import_answer)
    assert "work/segment/handoffs/segment-F1.md -> " in str(w.value)


class Clip:
    """Stands in for the clipboard: holds what the tool copies, and gives the
    next reply the user copied, if any."""

    def __init__(self, *replies):
        self.replies, self.held, self.copied = list(replies), "", []

    def copy(self, text):
        self.held = text
        self.copied.append(text)
        return True

    def paste(self):
        """The next reply; ``None`` stands for one the user forgot to copy."""
        reply = self.replies.pop(0) if self.replies else None
        if reply is not None:
            self.held = reply
        return self.held


def test_tasks_and_replies_go_through_the_clipboard(tmp_path, upstream):
    repo, commit = upstream
    ws = tmp_path / "audit"
    run(ws)
    fill_in(ws, repo, commit)
    extract(ws)
    good = Path(replies(ws)["docs"]).read_text(encoding="utf-8")
    bad = json.dumps({"instructions": "docs v1", "files": []})
    clip = Clip(None, bad, good)  # first Enter: the user forgot to copy
    script = Script("y", "1", "Test assistant", "", "", "", "q")
    g = guide.Guide(ws, ask=script.ask, say=script.say, clip=clip)
    assert g.run() == "stopped"
    assert clip.copied[0].startswith(instructions.load("docs").text.rstrip()[:40])
    assert "still holds the task, not the reply" in script.text
    assert "A note listing them is on your clipboard" in script.text
    assert "Please correct these problems" in clip.copied[1]
    assert "docs: done." in script.text
    assert len(list((ws / "work" / "docs" / "replies").glob("*.txt"))) == 2


def test_the_guide_asks_once_whether_scripts_may_start_matlab(tmp_path, monkeypatch):
    ws = tmp_path / "audit"
    run(ws)
    fill_in(ws, "https://github.com/someone/analysis", "0" * 40)
    code = ws / "materials" / "code"
    code.mkdir()
    (code / "analysis.py").write_text(CODE, encoding="utf-8")
    monkeypatch.setattr("rigoraudit.matlab.find", lambda: Path("/opt/matlab"))

    def ask(*answers):
        script = Script(*answers)
        g = guide.Guide(ws, ask=script.ask, say=script.say)
        return g.ask_programs(settings.load(ws)), script.text

    s, text = ask()  # no MATLAB files, no question
    assert s.derive_programs is None and text == ""

    (code / "fit.m").write_text("x = 1;\n", encoding="utf-8")
    s, text = ask("y")
    assert (
        "includes MATLAB files" in text and f"(found at {Path('/opt/matlab')})" in text
    )
    assert s.derive_programs == ("matlab",)
    assert "    programs: [matlab]\n    run: auto" in (ws / "audit.yaml").read_text(
        encoding="utf-8"
    )
    s, text = ask()  # answered: not asked again
    assert text == ""
