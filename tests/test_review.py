# Copyright (c) 2026, Joshua I. Gold
# SPDX-License-Identifier: BSD-2-Clause

import datetime
import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest
from conftest import DRAFTER

from rigoraudit import review
from rigoraudit.schema import (
    AuditRecord,
    Basis,
    Claim,
    ClaimType,
    Comparison,
    CrossFinding,
    CrossValue,
    DataAnchor,
    Derivation,
    Finding,
    Kind,
    ManuscriptAnchor,
    Observation,
    Obtained,
    Rule,
    Source,
    Status,
    Trace,
    Value,
)
from rigoraudit.server import ReviewError, make_handler, save_entry

QUOTE = "C = 41 sessions"
PARAGRAPH = QUOTE + " and 12 mice in total."
OVERRIDE = {"operation": "override", "target_kind": "finding",
            "target": "F3.B.a/population/sessions", "status": "consistent",
            "reason": "x", "reviewer": "y"}  # fmt: skip


def record(observed: int = 40, summary: str = "Legend 41; data 40.") -> AuditRecord:
    anchor = ManuscriptAnchor(
        file="m.pdf", section="Figure 3 legend", paragraph=3, char_start=0,
        char_end=len(QUOTE), quote=QUOTE,
    )  # fmt: skip
    stated = Value(name="sessions", value=41)
    seen = Value(name="sessions", value=observed, key="sessions/C")
    finding = Finding(
        id="F3.B.a/population/sessions",
        claim_id="F3.B.a",
        basis=Basis.EXACT,
        summary=summary,
        observations=(
            Observation(source=Source.RESULTS, statement="41.", anchor=anchor,
                        obtained=Obtained.QUOTED, values=(stated,)),
            Observation(
                source=Source.DATA, statement=f"{observed}.", obtained=Obtained.RECOMPUTED,
                values=(seen,),
                anchor=DataAnchor(file="data/t.mat", quote=f"C {observed}", produced_by=Derivation(
                    script="derivations/b.py", output="derivations/output/b.json")),
            ),
        ),
        comparisons=(Comparison(kind=Kind.EXACT, stated=(stated,), observed=(seen,)),),
    )  # fmt: skip
    claim = Claim(
        id="F3.B.a", type=ClaimType.NEW_RESULT, anchor=anchor, trace=Trace.TRACED
    )
    return AuditRecord(drafted_by=DRAFTER, claims=(claim,), findings=(finding,))


def override(rec: AuditRecord, status=Status.CONSISTENT, day=1) -> review.Entry:
    finding = rec.findings[0]
    return review.Entry(
        operation=review.Operation.OVERRIDE, target_kind=review.Target.FINDING,
        target=finding.id, status=status, reason="Off by one is a labeling slip.",
        reviewer="A. Reviewer", date=datetime.date(2026, 10, day),
        fingerprint=review.fingerprint(finding),
    )  # fmt: skip


# --- Overrides ----------------------------------------------------------------


def test_fingerprint_tracks_evidence_not_wording():
    base = review.fingerprint(record().findings[0])
    assert review.fingerprint(record(summary="Reworded.").findings[0]) == base
    assert review.fingerprint(record(observed=39).findings[0]) != base


def test_latest_override_applies_until_the_finding_changes():
    rec = record()
    first, second = (
        override(rec, Status.CONSISTENT, 1),
        override(rec, Status.DIFFERS, 2),
    )
    reviews, orphans = review.current(rec, (first, second))
    assert reviews["F3.B.a/population/sessions"].override is second
    assert reviews["F3.B.a/population/sessions"].applies
    assert orphans == ()

    changed, _ = review.current(record(observed=39), (first, second))
    assert changed["F3.B.a/population/sessions"].stale


def test_overrides_of_missing_findings_are_reported():
    o = override(record()).model_copy(update={"target": "R9.9/claim"})
    reviews, orphans = review.current(record(), (o,))
    assert reviews == {} and orphans == (o,)


def test_log_appends_and_round_trips(tmp_path):
    path = tmp_path / review.LOG
    assert review.load(path) == ()
    rec = record()
    review.add(path, override(rec, day=1))
    review.add(path, override(rec, Status.DIFFERS, day=2))
    log = review.load(path)
    assert [o.status for o in log] == [Status.CONSISTENT, Status.DIFFERS]
    assert (
        json.loads(path.read_text(encoding="utf-8"))["entries"][0]["reviewer"]
        == "A. Reviewer"
    )


# --- Server -------------------------------------------------------------------


@pytest.fixture
def served(tmp_path):
    (tmp_path / "record.json").write_text(record().model_dump_json(), encoding="utf-8")
    (tmp_path / "paragraphs.json").write_text(json.dumps([{
        "section": "Figure 3 legend", "paragraph": 3, "page": 2, "text": PARAGRAPH,
    }]), encoding="utf-8")  # fmt: skip
    (tmp_path / "report.html").write_text(
        '<html><body><li data-finding-id="F3.B.a/population/sessions"></li></body></html>',
        encoding="utf-8",
    )
    renders = []
    handler = make_handler(
        tmp_path / "report.html", tmp_path / "record.json",
        tmp_path / review.LOG, lambda: renders.append(1), "A. Reviewer",
        tmp_path / "paragraphs.json", tmp_path / "materials",
    )  # fmt: skip
    code = tmp_path / "materials" / "code"
    code.mkdir(parents=True)
    (code / "fit.py").write_text(
        "sessions = load()\nn = len(sessions)\n", encoding="utf-8"
    )
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}", tmp_path, renders
    httpd.shutdown()
    httpd.server_close()


def post(url: str, payload: dict) -> tuple[int, dict]:
    req = urllib.request.Request(
        url + "/api/review", data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"}, method="POST",
    )  # fmt: skip
    try:
        with urllib.request.urlopen(req) as res:
            return res.status, json.loads(res.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def test_page_gets_override_buttons(served):
    url, _, _ = served
    with urllib.request.urlopen(url + "/") as res:
        page = res.read().decode()
    assert "Override…" in page and '"A. Reviewer"' in page
    assert page.index("<script>") < page.index("</body>")


def test_page_is_served_with_a_query_string(served):
    url, _, _ = served
    with urllib.request.urlopen(url + "/?outcomes=differs&order=effect") as res:
        assert res.status == 200 and "Override…" in res.read().decode()


def test_override_is_saved_with_fingerprint_and_rerendered(served):
    url, root, renders = served
    status, body = post(url, {"operation": "override", "target_kind": "finding",
                              "target": "F3.B.a/population/sessions",
                              "status": "consistent", "reason": "Labeling slip.",
                              "reviewer": "A. Reviewer"})  # fmt: skip
    assert status == 200
    saved = review.load(root / review.LOG)
    assert len(saved) == 1 and saved[0].reason == "Labeling slip."
    assert saved[0].fingerprint == review.fingerprint(record().findings[0])
    assert body["target"] == "F3.B.a/population/sessions"
    assert renders == [1]


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ({**OVERRIDE, "target": "R9.9/claim"}, "No finding"),
        ({**OVERRIDE, "reason": "  "}, "required"),
        ({**OVERRIDE, "status": "wrong"}, "not a valid"),
        ({**OVERRIDE, "operation": "split"}, "not an operation on a finding"),
    ],
)  # fmt: skip
def test_bad_requests_are_refused(served, payload, message):
    url, root, renders = served
    status, body = post(url, payload)
    assert status == 400 and message in body["error"]
    assert review.load(root / review.LOG) == ()
    assert renders == []


# --- Log entries ----------------------------------------------------------------


def entry(**kwargs) -> review.Entry:
    return review.Entry(
        **{
            "target_kind": review.Target.CLAIM,
            "target": "F3.B.a",
            "reason": "Two results in one sentence.",
            "reviewer": "A. Reviewer",
            "date": datetime.date(2026, 10, 1),
            "fingerprint": review.fingerprint(record().claims[0]),
        }
        | kwargs
    )


def part(claim_id: str) -> Claim:
    return record().claims[0].model_copy(update={"id": claim_id})


def test_claim_fingerprint_tracks_type_and_quote():
    c = record().claims[0]
    assert review.fingerprint(c.model_copy(update={"id": "X1"})) == review.fingerprint(
        c
    )
    retyped = c.model_copy(update={"type": ClaimType.PROCEDURE})
    assert review.fingerprint(retyped) != review.fingerprint(c)


def test_operations_fit_their_target():
    with pytest.raises(ValueError, match="not an operation on a claim"):
        entry(operation=review.Operation.OVERRIDE, status=Status.CONSISTENT)
    with pytest.raises(ValueError, match="not an operation on a finding"):
        entry(operation=review.Operation.SPLIT, target_kind=review.Target.FINDING)


def test_entries_take_only_their_payload():
    entry(operation=review.Operation.CONFIRM)
    with pytest.raises(ValueError, match="takes nothing else"):
        entry(operation=review.Operation.CONFIRM, type=ClaimType.PROCEDURE)
    with pytest.raises(ValueError, match="new type, quote, or both"):
        entry(operation=review.Operation.EDIT)
    entry(operation=review.Operation.EDIT, type=ClaimType.PROCEDURE)


def test_split_parts_get_new_ids_from_the_original():
    entry(operation=review.Operation.SPLIT, claims=(part("F3.B.a1"), part("F3.B.a2")))
    with pytest.raises(ValueError, match="start with F3.B.a"):
        entry(operation=review.Operation.SPLIT, claims=(part("F3.B.a"), part("X2")))
    with pytest.raises(ValueError, match="at least two"):
        entry(operation=review.Operation.SPLIT, claims=(part("F3.B.a1"),))


def test_merge_and_add_rules():
    entry(operation=review.Operation.MERGE, absorbs=("F3.B.b",))
    with pytest.raises(ValueError, match="absorb itself"):
        entry(operation=review.Operation.MERGE, absorbs=("F3.B.a",))
    added = {"operation": review.Operation.ADD, "fingerprint": None, "target": "F3.C.a"}
    entry(**added, claims=(part("F3.C.a"),))
    with pytest.raises(ValueError, match="target's ID"):
        entry(**added, claims=(part("F3.C.b"),))
    with pytest.raises(ValueError, match="fingerprint"):
        entry(**added | {"fingerprint": "abc"}, claims=(part("F3.C.a"),))


def test_only_overrides_are_applied():
    rec = record()
    confirm = entry(
        operation=review.Operation.CONFIRM,
        target_kind=review.Target.FINDING,
        target=rec.findings[0].id,
        fingerprint=review.fingerprint(rec.findings[0]),
    )
    assert review.current(rec, (confirm,)) == ({}, ())


# --- Applying the log -------------------------------------------------------------


def two_claims() -> AuditRecord:
    """F3.B.a (traced, one finding) and F3.B.b, which depends on it."""
    rec = record()
    other = part("F3.B.b").model_copy(
        update={"type": ClaimType.INTERPRETATION, "depends_on": ("F3.B.a",),
                "trace": Trace.VIA_DEPENDENCIES}
    )  # fmt: skip
    return rec.model_copy(update={"claims": (*rec.claims, other)})


def on(rec: AuditRecord, op, target="F3.B.a", **kwargs) -> review.Entry:
    item = next(i for i in (*rec.claims, *rec.findings) if i.id == target)
    kind = review.Target.CLAIM if isinstance(item, Claim) else review.Target.FINDING
    return entry(operation=op, target=target, target_kind=kind,
                 fingerprint=review.fingerprint(item), **kwargs)  # fmt: skip


def test_confirm_and_override_leave_the_draft_as_it_is():
    rec = two_claims()
    out = review.apply(rec, (on(rec, review.Operation.CONFIRM), override(rec)))
    assert out.record == rec and len(out.applied) == 2


def test_split_resets_findings_and_repoints_dependents():
    rec = two_claims()
    parts = (part("F3.B.a1"), part("F3.B.a2"))
    out = review.apply(rec, (on(rec, review.Operation.SPLIT, claims=parts),))
    assert [c.id for c in out.record.claims] == ["F3.B.a1", "F3.B.a2", "F3.B.b"]
    assert out.record.findings == ()
    assert {c.trace for c in out.record.claims[:2]} == {Trace.PENDING}
    assert out.record.claims[2].depends_on == ("F3.B.a1", "F3.B.a2")
    assert out.retired == {"F3.B.a"}


def test_retired_ids_are_never_reused():
    rec = two_claims()
    split = on(rec, review.Operation.SPLIT, claims=(part("F3.B.a1"), part("F3.B.a2")))
    add = entry(operation=review.Operation.ADD, target="F3.B.a", fingerprint=None,
                claims=(part("F3.B.a"),))  # fmt: skip
    out = review.apply(rec, (split, add))
    assert out.applied == (split,)
    assert out.refused[0][0] == add and "never reused" in out.refused[0][1]


def test_entries_on_a_changed_target_are_stale():
    rec = two_claims()
    old = on(rec, review.Operation.REMOVE, target="F3.B.b")
    edit = on(rec, review.Operation.EDIT, target="F3.B.b", type=ClaimType.NEW_RESULT)
    out = review.apply(rec, (edit, old))
    assert out.applied == (edit,) and out.stale == (old,)


def test_entries_that_break_the_record_are_refused():
    rec = two_claims()
    out = review.apply(rec, (on(rec, review.Operation.REMOVE),))
    assert out.record == rec and "unknown" in out.refused[0][1]


def test_merge_retires_the_absorbed_claim():
    rec = two_claims()
    out = review.apply(rec, (on(rec, review.Operation.MERGE, absorbs=("F3.B.b",)),))
    assert [c.id for c in out.record.claims] == ["F3.B.a"]
    assert out.record.claims[0].trace is Trace.PENDING and out.record.findings == ()
    assert out.retired == {"F3.B.b"}


def test_finding_operations_keep_the_trace_in_step():
    rec = two_claims()
    f = rec.findings[0]
    removed = review.apply(rec, (on(rec, review.Operation.REMOVE, target=f.id),))
    assert removed.record.claims[0].trace is Trace.PENDING
    add = entry(operation=review.Operation.ADD, target_kind=review.Target.FINDING,
                target=f.id, fingerprint=None, finding=f)  # fmt: skip
    back = review.apply(removed.record, (add,))
    assert back.record == rec


def pick(text: str) -> dict:
    start = PARAGRAPH.index(text)
    return {"section": "Figure 3 legend", "paragraph": 3, "start": start,
            "end": start + len(text), "text": text}  # fmt: skip


def test_split_from_selections_is_saved_and_applied(served):
    url, root, _ = served
    status, body = post(url, {
        "operation": "split", "target_kind": "claim", "target": "F3.B.a",
        "reason": "Two counts.", "reviewer": "A. Reviewer",
        "parts": [{"id": "F3.B.a1", "type": "new_result", "quote": pick(QUOTE)},
                  {"id": "F3.B.a2", "type": "new_result", "quote": pick("12 mice")}],
    })  # fmt: skip
    assert status == 200, body
    reviewed = review.apply(record(), review.load(root / review.LOG)).record
    parts = reviewed.claims
    assert [c.id for c in parts] == ["F3.B.a1", "F3.B.a2"]
    assert parts[1].anchor.quote == "12 mice" and parts[1].anchor.page == 2
    assert parts[1].drafted_by.name == "A. Reviewer"
    # The next action sees the reviewed record: the split claim is gone
    status, body = post(url, {"operation": "confirm", "target_kind": "claim",
                              "target": "F3.B.a", "reason": "x", "reviewer": "y"})  # fmt: skip
    assert status == 400 and "No claim" in body["error"]


def test_selection_must_match_the_extraction(served):
    url, root, _ = served
    stale = pick("12 mice") | {"text": "13 mice"}
    status, body = post(url, {"operation": "add", "target_kind": "claim",
                              "id": "F3.B.b", "type": "new_result", "quote": stale,
                              "reason": "Missed.", "reviewer": "y"})  # fmt: skip
    assert status == 400 and "does not match" in body["error"]
    assert review.load(root / review.LOG) == ()


def test_add_and_refused_reuse(served):
    url, _, _ = served
    add = {"operation": "add", "target_kind": "claim", "id": "F3.B.b",
           "type": "new_result", "quote": pick("12 mice"), "reason": "Missed.",
           "reviewer": "y"}  # fmt: skip
    assert post(url, add)[0] == 200
    status, body = post(url, add)
    assert status == 400 and "never reused" in body["error"]


# --- Edit trace and Add finding from the page -------------------------------------

FID = "F3.B.a/population/sessions"
TRACE = {"operation": "edit_trace", "target_kind": "finding", "target": FID,
         "reason": "The code counts the sessions too.", "reviewer": "A. Reviewer"}  # fmt: skip
CODE = {"source": "code", "statement": "Counts the sessions loaded.",
        "file": "fit.py", "lines": [2, 2]}  # fmt: skip


def reviewed(root):
    return review.apply(record(), review.load(root / review.LOG)).record


def test_evidence_is_added_from_the_code_and_kept_by_choice(served):
    url, root, _ = served
    status, body = post(url, TRACE | {"keep": [0, 1], "add": [CODE]})
    assert status == 200, body
    [f] = reviewed(root).findings
    added = f.observations[-1]
    assert (
        added.anchor.file == "code/fit.py" and added.anchor.quote == "n = len(sessions)"
    )
    assert added.drafted_by.name == "A. Reviewer"
    assert f.status is Status.DIFFERS  # still computed from the comparisons


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"keep": [0]}, "at least two sources"),
        ({"keep": [0, 1]}, "Nothing was changed"),
        ({"keep": [0, 1, 5]}, "out of step"),
        ({"keep": [0, 1], "add": [CODE | {"lines": [2, 9]}]}, "has 2 lines"),
        ({"keep": [0, 1], "add": [CODE | {"file": "../secret.py"}]}, "outside"),
        ({"keep": [0, 1], "add": [CODE | {"source": "data"}]}, "derivation"),
    ],
)  # fmt: skip
def test_a_trace_edit_that_would_not_hold_is_refused(served, change, message):
    url, root, _ = served
    status, body = post(url, TRACE | change)
    assert status == 400 and message in body["error"], body
    assert review.load(root / review.LOG) == ()


def test_a_finding_is_added_to_a_claim_with_a_new_id(served):
    url, root, _ = served
    add = {"operation": "add", "target_kind": "finding", "target": "F3.B.a",
           "reason": "The mice are not checked.", "reviewer": "A. Reviewer",
           "claim": "F3.B.a", "facet": "population", "status": "not_verifiable",
           "why": "The data do not name the mice.", "effect": "indirect",
           "summary": "The legend states 12 mice; the data do not identify mice.",
           "evidence": [{"source": "results", "statement": "12 mice.",
                         "quote": pick("12 mice")}]}  # fmt: skip
    status, body = post(url, add)
    assert status == 200, body
    assert body["target"] == "F3.B.a/population"
    new = reviewed(root).findings[-1]
    assert new.id == "F3.B.a/population" and new.reason.startswith("The data")
    assert new.observations[0].anchor.quote == "12 mice"
    # a second one on the same facet gets the next ID
    status, body = post(url, add)
    assert status == 200 and body["target"] == "F3.B.a/population-2"
    status, body = post(url, add | {"status": "consistent"})
    assert status == 400 and "at least two sources" in body["error"]
    status, body = post(url, add | {"evidence": []})
    assert status == 400 and "at least one piece of evidence" in body["error"]


# --- Cross-claim findings --------------------------------------------------------


def cross(other: int = 50) -> CrossFinding:
    anchor = record().claims[0].anchor
    values = tuple(
        CrossValue(claim_id=cid, value=Value(name="mice", value=n), anchor=anchor)
        for cid, n in (("F3.B.a", 52), ("R1.1.a", other))
    )
    return CrossFinding(
        id="x/F3.B.a/R1.1.a/mice", claim_ids=("F3.B.a", "R1.1.a"),
        rules=(Rule.SAME_MEANING,), status=Status.DIFFERS, values=values,
        summary="F3.B.a and R1.1.a give mice as 52 and 50.", reason="All mice.",
    )  # fmt: skip


def test_a_cross_claim_finding_is_confirmed_or_overridden(tmp_path):
    path, log = tmp_path / "record.json", tmp_path / review.LOG
    path.write_text(record().model_dump_json(), encoding="utf-8")
    ask = {"target_kind": "cross", "target": cross().id, "reason": "Same mice.",
           "reviewer": "A. Reviewer"}  # fmt: skip
    found = lambda rec: (cross(),)
    save_entry(path, log, {**ask, "operation": "confirm"}, cross=found)
    save_entry(path, log, {**ask, "operation": "override", "status": "consistent"},
               cross=found)  # fmt: skip
    entries = review.load(log)
    # the record is left as it is, and the latest entry is in force
    applied = review.apply(record(), entries)
    assert applied.record == record() and not applied.stale and not applied.applied
    reviews, orphans = review.current_cross((cross(),), entries)
    assert reviews[cross().id].override.status is Status.CONSISTENT and not orphans
    assert review.current(record(), entries) == ({}, ())
    # a change in a value makes it stale; a finding no longer found, an orphan
    assert review.current_cross((cross(other=51),), entries)[0][cross().id].stale
    assert len(review.current_cross((), entries)[1]) == 2
    with pytest.raises(ReviewError, match="No cross-claim finding"):
        save_entry(path, log, {**ask, "operation": "confirm"})
    with pytest.raises(ReviewError, match="not an operation on a cross"):
        save_entry(path, log, {**ask, "operation": "remove"}, cross=found)
