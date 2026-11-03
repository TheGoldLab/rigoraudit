# Copyright (c) 2026, Joshua I. Gold
# SPDX-License-Identifier: BSD-2-Clause

import datetime
import json
import re
from pathlib import Path

import pytest

from rigoraudit import cli, instructions
from rigoraudit.paragraphs import read_paragraphs
from rigoraudit.schema import AuditRecord
from rigoraudit.segment import (
    Accepted,
    AnswerError,
    Handoff,
    check_answer,
    import_answer,
    parse_answer,
    pending_handoffs,
    plan_handoffs,
    read_accepted,
    record_claims,
    write_handoffs,
)

PARAGRAPHS = {
    "R1.1": "Rats pressed the lever faster in block A than in block B (Figure 1).",
    "R1.2": "Each block had 40 trials. Each block began with a cue.",
}

HANDOFFS = Path("work/segment/handoffs")
ANSWERS = Path("work/segment/answers")


def answer(claims=(), left_out=(), version="segment v2"):
    return parse_answer(
        json.dumps(
            {
                "instructions": version,
                "claims": list(claims),
                "left_out": list(left_out),
            }
        )
    )


GOOD = [
    {"id": "R1.1.a", "paragraph": "R1.1", "type": "new_result", "quote": "Rats pressed the lever faster in block A than in block B"},
    {"id": "R1.2.a", "paragraph": "R1.2", "type": "procedure", "quote": "Each block had 40 trials."},
]  # fmt: skip


def test_instructions_load_with_version():
    seg = instructions.load("segment")
    assert seg.label == "segment v2"
    assert seg.text.startswith("# Split the text into claims")


def test_example_in_the_instructions_passes():
    text = instructions.load("segment").text
    example = text[text.index("## Example") :]
    paragraphs = {
        label: " ".join(
            line.removeprefix("> ").strip() for line in quote.strip().splitlines()
        )
        for label, quote in re.findall(
            r"Paragraph `([^`]+)`[^\n]*:\n\n((?:>.*\n)+)", example
        )
    }
    assert set(paragraphs) == {"R2.1", "F3.1"}
    assert check_answer(parse_answer(example), paragraphs) == []


def test_good_answer_has_no_problems():
    assert check_answer(answer(GOOD), PARAGRAPHS) == []


def test_reply_with_text_around_a_fenced_block_is_read():
    reply = 'Here it is:\n```json\n{"instructions": "segment v2"}\n```\nDone.'
    assert parse_answer(reply).claims == ()


def test_unreadable_answers_are_described_in_words():
    with pytest.raises(AnswerError, match="not valid JSON"):
        parse_answer("{claims: }")
    with pytest.raises(AnswerError) as e:
        parse_answer(
            '{"instructions": "segment v2", "claims": [{"id": "R1.1.a", "paragraph": "R1.1"}]}'
        )
    assert e.value.problems == [
        "In claim 1, quote: Field required.",
        "In claim 1, type: Field required.",
    ]


def test_quote_must_be_word_for_word_and_unique():
    claims = [
        {**GOOD[0], "quote": "Rats pressed the lever more quickly"},
        {**GOOD[1], "quote": "Each block"},
    ]  # fmt: skip
    problems = check_answer(answer(claims), PARAGRAPHS)
    assert any("R1.1.a is not in paragraph R1.1 word for word" in p for p in problems)
    assert any("R1.2.a appears 2 times" in p for p in problems)


def test_ids_follow_the_paragraph_label():
    claims = [{**GOOD[0], "id": "R1.2.a"}, {**GOOD[1], "id": "R1.2.b"}]
    problems = check_answer(answer(claims), PARAGRAPHS)
    assert problems == [
        (
            "Claim R1.2.a is in paragraph R1.1, so its ID should be R1.1 followed by "
            "a letter (R1.1.a, R1.1.b, ...)."
        )
    ]


def test_duplicate_and_taken_ids():
    problems = check_answer(
        answer([GOOD[0], GOOD[0]]), PARAGRAPHS, known_claims={"R1.1.a"}
    )
    assert "The ID R1.1.a is used for more than one claim." in problems
    assert "The ID R1.1.a is already used by a claim in the record." in problems


def test_overlapping_claims():
    claims = [
        *GOOD,
        {**GOOD[0], "id": "R1.1.b", "quote": "faster in block A"},
    ]
    problems = check_answer(answer(claims), PARAGRAPHS)
    assert "Claims R1.1.a and R1.1.b overlap in paragraph R1.1." in problems


def test_restates_must_name_a_known_claim():
    claims = [*GOOD[:1], {**GOOD[1], "restates": "R9.9.z"}]
    assert check_answer(answer(claims), PARAGRAPHS) == [
        "Claim R1.2.a restates R9.9.z, which is not a known claim."
    ]
    claims = [*GOOD[:1], {**GOOD[1], "restates": "R0.1.a"}]
    assert check_answer(answer(claims), PARAGRAPHS, known_claims={"R0.1.a"}) == []


def test_uncovered_sentence_is_reported_and_left_out_text_covers_it():
    problems = check_answer(answer(GOOD[:1]), PARAGRAPHS)
    assert problems == [
        (
            "In paragraph R1.2, this sentence has text that no claim or left-out item "
            "covers (40): 'Each block had 40 trials.'"
        )
    ]
    left = [
        {"paragraph": "R1.2", "quote": "40 trials", "reason": "repeats the Methods"}
    ]
    assert check_answer(answer(GOOD[:1], left), PARAGRAPHS) == []


def test_left_out_quote_and_paragraph_are_checked():
    left = [
        {"paragraph": "R1.3", "quote": "x", "reason": "r"},
        {"paragraph": "R1.2", "quote": "fifty trials", "reason": "r"},
    ]
    problems = check_answer(answer(GOOD, left), PARAGRAPHS)
    assert problems == [
        "Left-out item 1 names paragraph R1.3, which was not given.",
        "The quote for left-out item 2 is not in paragraph R1.2 word for word: 'fifty trials'",
    ]


def test_outdated_instructions_are_flagged():
    problems = check_answer(answer(GOOD, version="segment v0"), PARAGRAPHS)
    assert problems == [
        "The answer names instructions 'segment v0'; the current instructions are 'segment v2'."
    ]


# --- Handoffs ---------------------------------------------------------------

EXTRACT = [
    {"section": "Methods › Task", "paragraph": 1, "text": "Rats pressed a lever."},
    {"section": "Results › Speed", "paragraph": 1, "text": PARAGRAPHS["R1.1"]},
    {"section": "Results › Speed", "paragraph": 2, "text": PARAGRAPHS["R1.2"]},
    {"section": "Figure 1 legend", "paragraph": 1, "text": "Lever presses were faster in block A."},
]  # fmt: skip


def workspace_with(tmp_path, extract=EXTRACT):
    path = tmp_path / "work" / "extract" / "paragraphs.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(extract), encoding="utf-8")
    (tmp_path / "audit.yaml").write_text(
        "materials:\n  manuscript:\n    path: manuscript.pdf\n", encoding="utf-8"
    )
    return tmp_path


def accept(ws, handoff, claims, left_out=()):
    h = Handoff.model_validate_json(
        (ws / HANDOFFS / f"{handoff}.json").read_text(encoding="utf-8")
    )
    a = Accepted(
        handoff=h.name,
        paragraphs=tuple(h.paragraphs),
        drafted_by="test",
        imported="2026-01-01",
        answer=answer(claims, left_out),
    )
    (ws / ANSWERS).mkdir(parents=True, exist_ok=True)
    (ws / ANSWERS / f"{h.name}.json").write_text(a.model_dump_json(), encoding="utf-8")


def test_results_are_handed_off_first_without_methods(tmp_path):
    ws = workspace_with(tmp_path)
    [md] = write_handoffs(ws)
    assert md.name == "segment-R1.1.md"
    text = md.read_text(encoding="utf-8")
    assert text.startswith("# Split the text into claims")
    assert "### Paragraph `R1.2` (Results › Speed ¶2)" in text
    assert "Rats pressed a lever." not in text
    assert "Lever presses were faster" not in text


def test_legends_follow_with_the_results_claims(tmp_path):
    ws = workspace_with(tmp_path)
    write_handoffs(ws)
    left = [{"paragraph": "R1.2", "quote": "40 trials", "reason": "design"}]
    accept(ws, "segment-R1.1", GOOD[:1], left)
    [md] = write_handoffs(ws)
    assert md.name == "segment-F1.1.md"
    text = md.read_text(encoding="utf-8")
    assert f"- R1.1.a: {GOOD[0]['quote']}" in text
    # the answered handoff is kept; nothing else is left over
    assert sorted(p.name for p in (ws / HANDOFFS).iterdir()) == [
        "segment-F1.1.json", "segment-F1.1.md", "segment-R1.1.json", "segment-R1.1.md",
    ]  # fmt: skip
    accept(ws, "segment-F1.1", [])
    assert write_handoffs(ws) == []


def test_batches_respect_the_size_limit(tmp_path):
    paras = read_paragraphs(workspace_with(tmp_path) / "work/extract/paragraphs.json")
    names = [h.name for h in plan_handoffs(paras, max_chars=80)]
    assert names == ["segment-R1.1", "segment-R1.2"]
    assert [h.name for h in plan_handoffs(paras)] == ["segment-R1.1"]


# --- Import -----------------------------------------------------------------

DAY = datetime.date(2026, 1, 2)


def reply(claims=(), left_out=()):
    body = json.dumps(
        {
            "instructions": "segment v2",
            "claims": list(claims),
            "left_out": list(left_out),
        }
    )
    return f"Here is my answer.\n```json\n{body}\n```\n"


def test_import_saves_a_good_reply_and_moves_on_to_legends(tmp_path):
    ws = workspace_with(tmp_path)
    write_handoffs(ws)
    left = [{"paragraph": "R1.2", "quote": "40 trials", "reason": "design"}]
    path, problems = import_answer(ws, reply(GOOD[:1], left), "Model X 1.0", today=DAY)
    assert problems == []
    saved = Accepted.model_validate_json(path.read_text(encoding="utf-8"))
    assert (saved.handoff, saved.drafted_by, saved.imported) == (
        "segment-R1.1",
        "Model X 1.0",
        "2026-01-02",
    )
    assert saved.paragraphs == ("R1.1", "R1.2")
    assert pending_handoffs(ws) == []
    [h] = plan_handoffs(
        read_paragraphs(ws / "work/extract/paragraphs.json"), read_accepted(ws)
    )
    assert h.name == "segment-F1.1"


def test_import_returns_problems_and_saves_nothing(tmp_path):
    ws = workspace_with(tmp_path)
    write_handoffs(ws)
    path, problems = import_answer(ws, reply(GOOD[:1]), "Model X")
    assert path is None
    assert len(problems) == 1 and "covers (40)" in problems[0]
    assert not (ws / ANSWERS).exists()
    assert import_answer(ws, "no json here", "Model X")[1][0].startswith(
        "The answer is not valid JSON"
    )


def test_import_needs_a_waiting_handoff(tmp_path):
    ws = workspace_with(tmp_path)
    assert import_answer(ws, reply(GOOD), "M")[1] == [
        "No handoff is waiting for an answer; run rigoraudit handoff segment."
    ]
    write_handoffs(ws)
    claim = {**GOOD[0], "id": "R7.1.a", "paragraph": "R7.1", "quote": "x"}
    assert "not all in any one handoff" in import_answer(ws, reply([claim]), "M")[1][0]
    assert import_answer(ws, reply(GOOD), "M", handoff="segment-R9.9")[1] == [
        "No handoff named segment-R9.9 is waiting for an answer."
    ]


def test_ambiguous_reply_asks_for_the_handoff(tmp_path):
    ws = workspace_with(tmp_path)
    write_handoffs(ws, max_chars=80)
    problems = import_answer(ws, reply(), "M")[1]
    assert problems == [
        (
            "The answer could belong to more than one handoff "
            "(segment-R1.1, segment-R1.2); say which with --handoff."
        )
    ]
    claim = GOOD[0]
    assert import_answer(ws, reply([claim]), "M")[1] == []


def test_cli_import_prints_problems_to_paste_back(tmp_path, capsys):
    ws = workspace_with(tmp_path)
    cli.main(["handoff", "segment", str(ws)])
    assert "segment-R1.1.md" in capsys.readouterr().out
    bad = tmp_path / "reply.txt"
    bad.write_text(reply(GOOD[:1]), encoding="utf-8")
    with pytest.raises(SystemExit):
        cli.main(["import", "segment", str(bad), str(ws), "--by", "M"])
    out = capsys.readouterr().out
    assert "Please correct these problems" in out and "- In paragraph R1.2" in out
    bad.write_text(reply(GOOD), encoding="utf-8")
    cli.main(["import", "segment", str(bad), str(ws), "--by", "M"])
    out = capsys.readouterr().out
    assert out.startswith("Accepted segment-R1.1: 2 claims and 0 left-out pieces")
    assert "Next: run rigoraudit handoff segment" in out


# --- Claim types -------------------------------------------------------------

CITED_TEXT = {
    "R1.1": "Rats were faster in block A, as in earlier work (Lee et al., 2019)."
}


def test_cited_types_need_citations_found_in_the_paragraph():
    base = {"id": "R1.1.a", "paragraph": "R1.1", "quote": CITED_TEXT["R1.1"]}
    good = {**base, "type": "comparison", "citations": ["Lee et al., 2019"]}
    assert check_answer(answer([good]), CITED_TEXT) == []
    assert check_answer(
        answer([{**base, "type": "referenced_result"}]), CITED_TEXT
    ) == ["Claim R1.1.a is a referenced_result, so it needs citations."]
    wrong = {**good, "citations": ["Lee, 2019"]}
    assert check_answer(answer([wrong]), CITED_TEXT) == [
        "The citation 'Lee, 2019' for claim R1.1.a is not in paragraph R1.1 word for word."
    ]


def test_depends_on_and_no_stated_support():
    a = {**GOOD[0], "type": "interpretation", "depends_on": ["R1.1.a"]}
    assert check_answer(answer([a, GOOD[1]]), PARAGRAPHS) == [
        "Claim R1.1.a cannot depend on itself."
    ]
    b = {**GOOD[1], "type": "interpretation", "depends_on": ["R1.1.a", "R5.5.a"]}
    assert check_answer(answer([GOOD[0], b]), PARAGRAPHS) == [
        "Claim R1.2.a depends on R5.5.a, which is not a known claim."
    ]
    c = {**GOOD[1], "type": "no_stated_support", "depends_on": ["R1.1.a"]}
    [problem] = check_answer(answer([GOOD[0], c]), PARAGRAPHS)
    assert "cannot have citations or depends_on" in problem
    bad_type = {"instructions": "segment v2", "claims": [{**GOOD[0], "type": "result"}]}
    with pytest.raises(AnswerError, match="type"):
        parse_answer(json.dumps(bad_type))


# --- Record claims -----------------------------------------------------------

EXAMPLE = Path(__file__).parent.parent / "examples" / "example-audit"


def test_record_claims_follow_paragraphs_extracted_again(tmp_path):
    ws = workspace_with(tmp_path)
    write_handoffs(ws)
    left = [{"paragraph": "R1.2", "quote": "40 trials", "reason": "design"}]
    accept(ws, "segment-R1.1", GOOD[:1], left)
    again = [dict(e) for e in EXTRACT]
    again[1]["text"] = "Overall, " + PARAGRAPHS["R1.1"].replace("block A", "block A†")
    (ws / "work/extract/paragraphs.json").write_text(
        json.dumps(again), encoding="utf-8"
    )
    [c] = record_claims(ws, "manuscript.txt")
    assert c.anchor.quote == GOOD[0]["quote"].replace("block A", "block A†")
    assert again[1]["text"][c.anchor.char_start : c.anchor.char_end] == c.anchor.quote


def test_record_claims_match_the_example_audits_hand_built_claims(tmp_path):
    extract = json.loads(
        (EXAMPLE / "work/extract/paragraphs.json").read_text(encoding="utf-8")
    )
    ws = workspace_with(tmp_path, extract)
    gold = AuditRecord.model_validate_json(
        (EXAMPLE / "record/record.json").read_text(encoding="utf-8")
    )
    write_handoffs(ws)
    claims = [
        {"id": c.id, "paragraph": c.id.rsplit(".", 1)[0], "quote": c.anchor.quote,
         "type": c.type.value, "citations": list(c.citations), "depends_on": list(c.depends_on)}
        for c in gold.claims
    ]  # fmt: skip
    left = json.loads(
        (EXAMPLE / "record/coverage_exclusions.json").read_text(encoding="utf-8")
    )
    left_out = left["exclusions"]
    assert import_answer(ws, reply(claims, left_out), "test")[1] == []
    built = record_claims(ws, "manuscript.txt")
    assert [(c.id, c.type, c.anchor) for c in built] == [
        (c.id, c.type, c.anchor) for c in gold.claims
    ]
    assert all(c.trace.value == "pending" for c in built)
