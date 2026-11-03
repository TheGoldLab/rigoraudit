# Copyright (c) 2026, Joshua I. Gold
# SPDX-License-Identifier: BSD-2-Clause

import datetime
from collections import Counter

from conftest import DRAFTER
from test_review import override, record

from rigoraudit import review, status
from rigoraudit.coverage import Report
from rigoraudit.schema import Drafter, DrafterKind, Status
from rigoraudit.verify import AnchorCheck, Outcome


def anchors(*outcomes: Outcome) -> list[AnchorCheck]:
    return [AnchorCheck("somewhere", "manuscript", o, "", "q") for o in outcomes]


def checks(*outcomes: Outcome, rec=None, uncovered=None, items=None) -> status.Checks:
    rec = rec or record()
    found = {o: n for o, n in Counter(outcomes).items()}
    return status.Checks(
        record_digest=status.digest(rec),
        anchors=found,
        uncovered=uncovered,
        items=items,
    )


def confirm(rec, day=1) -> review.Entry:
    c = rec.claims[0]
    return review.Entry(
        operation=review.Operation.CONFIRM,
        target_kind=review.Target.CLAIM,
        target=c.id,
        reason="Boundaries and type are right.",
        reviewer="A. Reviewer",
        date=datetime.date(2026, 10, day),
        fingerprint=review.fingerprint(c),
    )


def test_fresh_record_says_what_is_left():
    text = status.paragraph(record(), checks=checks(Outcome.VERIFIED, Outcome.VERIFIED))
    assert text == (
        "1 claim, 1 finding. Drafted by A. Reviewer, 2026-01-01. Mechanical "
        "checks pass: 2 anchors verified; coverage not checked. Reviewed: 0 of "
        "1 claim, 0 of 1 finding. Independent annotation: none. Authors: not "
        "contacted. Next: review 1 claim and 1 finding, claims first."
    )


def test_checks_not_run_or_failing_come_first():
    assert "Mechanical checks: not run." in status.paragraph(record())
    text = status.paragraph(
        record(), checks=checks(Outcome.MISMATCH, Outcome.STALE, Outcome.VERIFIED)
    )
    assert "fail: 1 anchor does not match, 1 anchor comes from a stale" in text
    assert text.endswith("Next: make the mechanical checks pass.")


def test_review_actions_are_counted_and_stale_ones_set_apart():
    rec = record()
    entries = (confirm(rec), override(rec, Status.CONSISTENT))
    text = status.paragraph(rec, entries, checks=checks(Outcome.VERIFIED))
    assert "Reviewed: 1 of 1 claim, 1 of 1 finding (1 confirmed, 1 overridden)." in text
    assert text.endswith("Next: an independent annotation of a sample.")

    changed = record(observed=39)
    text = status.paragraph(
        changed, entries, checks=checks(Outcome.VERIFIED, rec=changed)
    )
    assert "0 of 1 finding (1 confirmed); 1 review action needs re-review." in text


def test_other_drafters_coverage_and_last_levels():
    rec = record()
    model = Drafter(
        kind=DrafterKind.MODEL, name="Model X", model_id="x-1", stage="trace",
        date=datetime.date(2026, 1, 2),
    )  # fmt: skip
    rec = rec.model_copy(
        update={"findings": (rec.findings[0].model_copy(update={"drafted_by": model}),)}
    )
    text = status.paragraph(
        rec,
        (confirm(rec), override(rec)),
        checks=checks(Outcome.VERIFIED, Outcome.UNCHECKED, rec=rec, uncovered=0),
        independent="1 claim, full agreement",
        authors="sent 2026-10-01; no reply",
    )
    assert "1 item drafted by someone else." in text
    assert "1 anchor verified, 1 with nothing to check against." in text
    assert "Next:" not in text
    assert rec.drafted_by == DRAFTER


def test_block_is_replaced_in_place():
    first = status.update_block("# Audit\n", "Old.")
    assert first == f"# Audit\n\n{status.BEGIN}\nOld.\n{status.END}\n"
    second = status.update_block(first + "More.\n", "New.")
    assert "Old." not in second and second.endswith(f"{status.END}\nMore.\n")


def test_checks_are_saved_together_and_go_stale(tmp_path):
    rec = record()
    status.save_checks(tmp_path, rec, anchors=anchors(Outcome.VERIFIED))
    status.save_checks(tmp_path, rec, coverage=Report(n_items=4, gaps=(), unused=()))
    saved = status.load_checks(tmp_path)
    assert saved == checks(Outcome.VERIFIED, uncovered=0, items=4)
    assert "checks pass: 1 anchor verified." in status.paragraph(rec, checks=saved)
    changed = record(observed=39)
    assert "not run on this version" in status.paragraph(changed, checks=saved)
    status.save_checks(
        tmp_path, changed, coverage=Report(n_items=4, gaps=(), unused=())
    )
    assert status.load_checks(tmp_path).anchors is None


def test_split_parts_count_as_reviewed():
    from test_review import on, part, two_claims

    rec = two_claims()
    split = on(rec, review.Operation.SPLIT, claims=(part("F3.B.a1"), part("F3.B.a2")))
    text = status.paragraph(rec, (split,))
    assert text.startswith("3 claims, 0 findings.")
    assert "Reviewed: 2 of 3 claims, 0 of 0 findings (1 split)." in text


def test_checks_count_only_when_run_on_the_reviewed_record():
    from test_review import on, two_claims

    rec = two_claims()
    remove = on(rec, review.Operation.REMOVE, "F3.B.b")
    on_draft = checks(Outcome.VERIFIED, rec=rec)
    assert "not run on this version" in status.paragraph(
        rec, (remove,), checks=on_draft
    )
    reviewed = review.apply(rec, (remove,)).record
    on_reviewed = checks(Outcome.VERIFIED, rec=reviewed)
    text = status.paragraph(rec, (remove,), checks=on_reviewed)
    assert "Mechanical checks pass" in text


def test_the_reviewed_record_is_read_with_the_workspace_log(tmp_path):
    from test_review import on, two_claims

    rec = two_claims()
    assert review.reviewed(rec, tmp_path) == rec
    review.add(tmp_path / review.LOG, on(rec, review.Operation.REMOVE, "F3.B.b"))
    assert len(review.reviewed(rec, tmp_path).claims) == len(rec.claims) - 1
