# Copyright (c) 2026, Joshua I. Gold
# SPDX-License-Identifier: BSD-2-Clause

import datetime
import re
import shutil
from html import unescape
from pathlib import Path
from types import SimpleNamespace

import pytest

from rigoraudit import report, review
from rigoraudit.schema import (
    RECORD,
    AuditRecord,
    Claim,
    ClaimType,
    Comparison,
    Context,
    CrossFinding,
    CrossValue,
    Kind,
    Rule,
    Status,
    Value,
)

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "example-audit"


@pytest.fixture
def ws(tmp_path):
    """A copy of the example audit, with no review log."""
    ws = tmp_path / "example-audit"
    shutil.copytree(EXAMPLE, ws, ignore=shutil.ignore_patterns("review", "__pycache__"))
    return ws


def draft(ws):
    return AuditRecord.model_validate_json((ws / RECORD).read_text(encoding="utf-8"))


def test_each_claim_and_finding_is_marked_for_the_review_page(ws):
    html, _ = report.render(ws)
    rec = draft(ws)
    for c in rec.claims:
        assert f'data-claim-id="{c.id}"' in html
    for f in rec.findings:
        assert f'data-finding-id="{f.id}"' in html
    assert "{{" not in html
    assert "<title>Example audit: tone discrimination learning · Audit</title>" in html


def test_paragraph_text_less_the_labels_is_the_extracted_text(ws):
    from rigoraudit.paragraphs import read_paragraphs

    html, _ = report.render(ws)
    paragraphs = {(p.section, p.number): p.text for p in
                  read_paragraphs(ws / "work/extract/paragraphs.json")}  # fmt: skip
    shown = re.findall(
        r'<span class="ms-text" data-section="([^"]*)" data-paragraph="(\d+)">(.*?)</span>\n?<',
        html,
    )
    assert shown
    for section, number, inner in shown:
        text = re.sub(r"<sup data-not-text>.*?</sup>", "", inner)
        text = unescape(re.sub(r"<[^>]+>", "", text))
        assert text == paragraphs[(unescape(section), int(number))]


def scope(ws, *patterns):
    """Set the audited sections in the workspace's manifest."""
    manifest = ws / "audit.yaml"
    listed = ", ".join(map(repr, patterns))
    manifest.write_text(
        re.sub(
            r"scope: \[.*?\]",
            f"scope: [{listed}]",
            manifest.read_text(encoding="utf-8"),
        ),
        encoding="utf-8",
    )


def test_only_the_audited_sections_are_shown(ws):
    html, _ = report.render(ws)
    assert 'data-section="Results › Learning"' in html
    assert 'data-section="Methods' not in html
    scope(ws, "Results", "Methods")
    html, _ = report.render(ws)
    assert 'data-section="Methods › Subjects and task"' in html


def test_the_page_shows_the_reviewed_record(ws):
    rec = draft(ws)
    gone = rec.claims[-1]
    review.add(ws / review.LOG, review.Entry(
        operation=review.Operation.REMOVE, target_kind=review.Target.CLAIM,
        target=gone.id, reason="Not a claim.", reviewer="A. Reviewer",
        date=datetime.date(2026, 1, 1), fingerprint=review.fingerprint(gone),
    ))  # fmt: skip
    html, standing = report.render(ws)
    assert f'data-claim-id="{gone.id}"' not in html
    assert "removed" in standing


def test_without_a_header_one_is_made_and_the_page_is_written(ws):
    (ws / report.HEADER).unlink()
    out = report.write(ws)
    assert out == ws / report.PAGE
    html = out.read_text(encoding="utf-8")
    assert "<h1>example-audit</h1>" in html and str(report.HEADER) in html
    assert report.status.BEGIN in (ws / "README.md").read_text(encoding="utf-8")


def test_a_claim_in_a_paragraph_not_extracted_is_an_error(ws):
    path = ws / "work/extract/paragraphs.json"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "Results › Learning", "Results › Training"
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="quote paragraphs not in"):
        report.render(ws)


def test_the_audited_sections_can_be_patterns(ws):
    scope(ws, r"Methods › Subj")
    html, _ = report.render(ws)
    assert 'data-section="Methods › Subjects and task"' in html
    scope(ws, r"Methods$")
    html, _ = report.render(ws)
    assert 'data-section="Methods' not in html


def gaps(ws, text):
    """Set the gaps in the workspace's manifest."""
    manifest = ws / "audit.yaml"
    manifest.write_text(
        re.sub(
            r"gaps:.*?\n\n",
            f"gaps:\n{text}\n",
            manifest.read_text(encoding="utf-8"),
            flags=re.DOTALL,
        ),
        encoding="utf-8",
    )


def test_the_gaps_in_the_materials_head_the_page(ws):
    gaps(
        ws, "  - missing: No trial list.\n    instead: Rebuilt.\n    claims: [R1.2.b]\n"
    )
    html, _ = report.render(ws)
    assert html.index('id="gaps"') < html.index('id="filters"')
    assert 'id="gap-1"' in html and "Instead: Rebuilt." in html
    assert 'href="#card-R1.2.b"' in html
    card = html[html.index('id="card-R1.2.b"') :]
    assert 'href="#gap-1">gap 1</a> in the materials: No trial list.' in card
    assert (
        "#gap-1"
        not in html[html.index('id="card-R1.2.a"') : html.index('id="card-R1.2.b"')]
    )
    gaps(ws, "  []\n")
    html, _ = report.render(ws)
    assert "Gaps in the materials: none listed" in html


def test_without_a_record_says_where_it_should_be(tmp_path):
    with pytest.raises(FileNotFoundError, match="record/record.json is missing"):
        report.render(tmp_path)


def test_a_value_printed_in_two_claims_is_listed_and_on_both_cards(ws, monkeypatch):
    a, b = draft(ws).claims[:2]
    values = tuple(
        CrossValue(claim_id=c.id, value=Value(name="trials", value=n), anchor=c.anchor)
        for c, n in ((a, 400), (b, 410))
    )
    x = CrossFinding(
        id=f"x/{a.id}/{b.id}/trials",
        claim_ids=(a.id, b.id),
        rules=(Rule.SAME_LABEL,),
        status=Status.DIFFERS,
        values=values,
        summary=f"{a.id} and {b.id} give trials as 400 and 410.",
        reason="Trials of all mice, over all sessions.",
    )
    monkeypatch.setattr(report.crosscheck, "current", lambda ws, rec: (x,))
    html, _ = report.render(ws)
    assert '<details class="issues" id="cross" open>' in html
    assert "1 value printed in more than one claim; 1 differs" in html
    cards = re.findall(r'<details class="card.*?</details>', html, re.DOTALL)
    assert sum(x.summary in card for card in cards) == 2
    assert "confirmed: Trials of all mice, over all sessions." in html
    assert f'data-cross-id="{x.id}"' in html
    review.add(ws / review.LOG, review.Entry(
        operation=review.Operation.CONFIRM, target_kind=review.Target.CROSS,
        target=x.id, reason="The same trials.", reviewer="A. Reviewer",
        date=datetime.date(2026, 11, 1), fingerprint=review.fingerprint(x),
    ))  # fmt: skip
    html, _ = report.render(ws)
    assert "Reviewer confirmed: The same trials." in html
    monkeypatch.setattr(report.crosscheck, "current", lambda ws, rec: None)
    html, _ = report.render(ws)
    assert "not done: the crosscheck step waits for an answer" in html


def test_a_finding_that_differs_names_the_values_that_do_not_agree():
    def c(stated, found):
        return Comparison(
            kind=Kind.PRECISION,
            stated=(Value(name="SD", value=stated, decimals=2),),
            observed=(Value(name="SD", value=found),),
        )

    f = SimpleNamespace(comparisons=(c(0.11, 0.111), c(0.2, 0.236)))
    assert (
        report.off_line(f) == '<p class="off">Do not agree: <b>SD 0.20 vs 0.236</b></p>'
    )
    assert report.off_line(SimpleNamespace(comparisons=(c(0.11, 0.111),))) == ""


def test_an_equation_mark_is_followed_by_its_picture(ws):
    import json

    from rigoraudit.extract import EQUATIONS_FILE, FOLDER

    path = ws / "work/extract/paragraphs.json"
    paragraphs = json.loads(path.read_text(encoding="utf-8"))
    claim = draft(ws).claims[0].anchor
    p = next(
        p
        for p in paragraphs
        if (p["section"], p["paragraph"]) == (claim.section, claim.paragraph)
    )
    at = len(p["text"]) + 1
    p["text"] += " [Equation 2]"
    path.write_text(json.dumps(paragraphs), encoding="utf-8")
    (ws / FOLDER / "equations").mkdir()
    (ws / FOLDER / "equations/001.png").write_bytes(b"made-up picture")
    record = {"number": "2", "section": p["section"], "paragraph": p["paragraph"]}
    (ws / EQUATIONS_FILE).write_text(
        json.dumps([{**record, "at": at, "picture": "equations/001.png"}]),
        encoding="utf-8",
    )
    html, _ = report.render(ws)
    assert '[Equation 2]<img class="eqpic" data-eq="0"' in html
    assert html.count("bWFkZS11cCBwaWN0dXJl") == 1  # stored once, as base64

    # a mark whose place is not known is matched by its number
    (ws / EQUATIONS_FILE).write_text(
        json.dumps([{**record, "at": None, "picture": "equations/001.png"}]),
        encoding="utf-8",
    )
    html, _ = report.render(ws)
    assert '[Equation 2]<img class="eqpic" data-eq="0"' in html


def test_a_claim_with_no_stated_support_is_not_waiting_to_be_traced(ws):
    rec = draft(ws)
    first = rec.claims[0]
    alone = Claim(id="Z1", type=ClaimType.NO_STATED_SUPPORT, anchor=first.anchor)
    rec = rec.model_copy(update={"claims": (*rec.claims, alone)})
    (ws / RECORD).write_text(rec.model_dump_json(indent=1), encoding="utf-8")
    html, _ = report.render(ws)
    card = re.search(
        r'<details class="card[^>]*data-claim-id="Z1".*?</details>', html, re.DOTALL
    )
    assert "No stated support</span>" in card[0]
    assert "Not traced yet" not in card[0]
    assert "not traced yet" not in html


def test_a_claim_compared_whole_has_no_table_of_facets(ws):
    f = next(f for f in draft(ws).findings if f.facet)
    assert "<table" in report.facet_table([f])
    assert report.facet_table([f.model_copy(update={"facet": None})]) == ""


def test_a_claim_with_several_tests_lists_them_by_number(ws):
    rec = draft(ws)
    cid = rec.claims[0].id
    context = (
        Context(claim_id=cid, scope="test 1", test="t(11) = 2.10, p = 0.047"),
        Context(
            claim_id=cid, scope="test 2", test="t(11) = 3.20, p = 0.008",
            assumes="Assumes independent observations.",
        ),
    )  # fmt: skip
    (ws / RECORD).write_text(
        rec.model_copy(update={"context": context}).model_dump_json(indent=1),
        encoding="utf-8",
    )
    html, _ = report.render(ws)
    card = re.search(
        rf'<details class="card[^>]*data-claim-id="{cid}".*?</details>', html, re.DOTALL
    )[0]
    legend = card.index('<ul class="tests">')
    assert card.index("Show in text") < legend < card.index('<ol class="findings">')
    assert '<span class="tnum">Test 1</span> “t(11) = 2.10, p = 0.047”</li>' in card
    assert "p = 0.008” <span class=why>Assumes independent observations.</span>" in card
