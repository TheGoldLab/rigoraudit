import json

from rigoraudit import breaks, cli, handoffs
from rigoraudit.paragraphs import PARAGRAPHS

TOOK = "Mice licked more after the reward tone."
LATER = "Licking began 120 ms after onset."
CUT = "The rate was fitted with a line"
GOES_ON = "where t is the time from onset."
NEXT = "We next asked whether the mice learned the order."


def entry(text, n, section="Results", **extra):
    return {
        "section": section,
        "paragraph": n,
        "text": text,
        "pages": [n],
        "approximate": True,
        **extra,
    }


def workspace(tmp_path, entries):
    path = tmp_path / PARAGRAPHS
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(entries))
    return tmp_path


ENTRIES = [
    entry(f"{TOOK} {NEXT}", 1, doubts=[len(TOOK) + 1]),
    entry(CUT, 2),
    entry(GOES_ON, 3),
    entry(LATER, 4),
]


def reply(**decisions):
    return json.dumps(
        {
            "instructions": "breaks v2",
            "decisions": [
                {"spot": s, "new_paragraph": v} for s, v in decisions.items()
            ],
        }
    )


def test_find_spots():
    spots = breaks.find_spots(ENTRIES)
    # the doubt inside paragraph 1, and the break after the unfinished
    # sentence; the break before LATER is not in doubt
    assert [(s.id, s.index, s.offset) for s in spots] == [
        ("B1", 0, len(TOOK) + 1),
        ("B2", 2, 0),
    ]
    assert spots[0].before == TOOK and spots[0].after == NEXT
    assert spots[1].before == CUT and spots[1].place == "Results ¶3"
    assert breaks.find_spots([{**e, "approximate": False} for e in ENTRIES]) == []


def test_rough_note_when_many_breaks_are_in_doubt(tmp_path):
    # two spots in four paragraphs is many; one in four is not
    assert "unsure about 2 paragraph breaks in 4" in breaks.rough_note(
        workspace(tmp_path, ENTRIES)
    )
    calm = [{**ENTRIES[0], "doubts": []}, *ENTRIES[1:]]
    assert breaks.rough_note(workspace(tmp_path / "calm", calm)) == ""


def test_import_splits_and_joins(tmp_path):
    ws = workspace(tmp_path, ENTRIES)
    (md,) = breaks.write_handoffs(ws)
    assert f"### B1 (Results ¶1)\n\n> …{TOOK} ‖ {NEXT}…" in md.read_text()
    saved, problems = breaks.import_answer(ws, reply(B1=True, B2=False), "someone")
    assert problems == []
    accepted = breaks.Accepted.model_validate_json(saved.read_text())
    assert (accepted.split, accepted.joined) == (1, 1)
    got = json.loads((ws / PARAGRAPHS).read_text())
    assert [(e["paragraph"], e["text"]) for e in got] == [
        (1, TOOK),
        (2, NEXT),
        (3, f"{CUT} {GOES_ON}"),
        (4, LATER),
    ]
    assert got[2]["pages"] == [2, 3]
    assert got[2]["page_starts"] == [[0, 2], [len(CUT) + 1, 3]]
    assert not any("doubts" in e for e in got)
    assert breaks.plan_handoffs(ws) == []


def test_import_keeps_what_was_right(tmp_path):
    ws = workspace(tmp_path, ENTRIES)
    breaks.write_handoffs(ws)
    _, problems = breaks.import_answer(ws, reply(B1=False, B2=True), "someone")
    assert problems == []
    got = json.loads((ws / PARAGRAPHS).read_text())
    assert [e["text"] for e in got] == [e["text"] for e in ENTRIES]


def test_import_problems(tmp_path):
    ws = workspace(tmp_path, ENTRIES)
    breaks.write_handoffs(ws)
    _, problems = breaks.import_answer(
        ws,
        json.dumps(
            {
                "instructions": "breaks v2",
                "decisions": [
                    {"spot": "B1", "new_paragraph": True},
                    {"spot": "B1", "new_paragraph": False},
                    {"spot": "B9", "new_paragraph": True},
                ],
            }
        ),
        "someone",
    )
    assert [handoffs.kind(p) for p in problems] == [
        "unknown-spot",
        "repeated-spot",
        "missing-spot",
    ]
    assert json.loads((ws / PARAGRAPHS).read_text()) == ENTRIES


def test_import_refuses_changed_paragraphs(tmp_path):
    ws = workspace(tmp_path, ENTRIES)
    breaks.write_handoffs(ws)
    (ws / PARAGRAPHS).write_text(json.dumps(ENTRIES[:3]))
    _, problems = breaks.import_answer(ws, reply(B1=True, B2=False), "someone")
    assert [handoffs.kind(p) for p in problems] == ["paragraphs-changed"]


def test_no_spots_in_the_front_matter_or_after_a_legend_title():
    title = "A made-up figure"  # a title the tool split off, with no full stop
    entries = [
        entry(CUT, 1, "Front matter"),
        entry(GOES_ON, 2, "Front matter"),
        entry(title, 1, "Figure 1 legend"),
        entry("panel A shows accuracy.", 2, "Figure 1 legend"),
        entry(CUT, 3, "Figure 1 legend"),
        entry(GOES_ON, 4, "Figure 1 legend"),
    ]
    assert [(s.index, s.offset) for s in breaks.find_spots(entries)] == [(5, 0)]


def test_command_says_what_changed_and_what_comes_next(tmp_path, capsys):
    ws = workspace(tmp_path, ENTRIES)
    breaks.write_handoffs(ws)
    answer = tmp_path / "reply.txt"
    answer.write_text(reply(B1=True, B2=False))
    cli.main(["import", "breaks", str(answer), str(ws), "--by", "someone"])
    out = capsys.readouterr().out
    assert out.startswith(
        "Accepted the paragraph breaks: 1 paragraph split in two and 1 pair "
        f"joined into one, in {PARAGRAPHS}."
    )
    assert out.rstrip().endswith("Next: rigoraudit handoff segment")
