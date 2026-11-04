# Copyright (c) 2026, Joshua I. Gold
# SPDX-License-Identifier: BSD-2-Clause

import doctest
import importlib.util
import sys
from pathlib import Path

from miragold.schema import ClaimType

SCRIPT = Path(__file__).parent.parent / "scripts" / "compare_claims.py"
spec = importlib.util.spec_from_file_location("compare_claims", SCRIPT)
cc = importlib.util.module_from_spec(spec)
sys.modules["compare_claims"] = cc  # dataclasses look the module up by name
spec.loader.exec_module(cc)

R, P = ClaimType.NEW_RESULT, ClaimType.PROCEDURE
REPEATED = "Bars show the median across sessions."


def claim(cid, quote, section="Results", kind=R, facets=None):
    return cc.Claim(cid, kind, section, quote, None, facets or {})


def kinds(ref, guided):
    return {
        (tuple(c.id for c in g.ref), tuple(c.id for c in g.guided)): g.kind
        for g in cc.match(ref, guided)
    }


def test_the_doctests_pass():
    assert doctest.testmod(cc).failed == 0


def test_claims_are_sorted_by_how_their_quotes_overlap():
    ref = [
        claim("a", "Response times fell steadily across the four training days"),
        claim("b", "the slower group caught up by the last block"),
        claim("c", "lever presses were rarer in the dark phase of the cycle"),
        claim("d", "accuracy rose with longer viewing of the grating stimulus"),
    ]
    guided = [
        claim("1", "Response times fell steadily across the four training days."),
        claim(
            "2",
            "As shown in Figure 2, the slower group caught up by the last block, "
            "though only after a long pause between the sessions.",
        ),
        claim("3", "lever presses were rarer"),
        claim("4", "in the dark phase of the cycle"),
        claim("5", "pupil size did not track the reward on the previous trial"),
    ]
    assert kinds(ref, guided) == {
        (("a",), ("1",)): "same",
        (("b",), ("2",)): "different extent",
        (("c",), ("3", "4")): "split differently",
        (("d",), ()): "missed",
        ((), ("5",)): "extra",
    }


def test_claims_in_different_sections_are_not_linked():
    ref = [claim("a", "the slower group caught up by the last block")]
    guided = [
        claim("1", "the slower group caught up by the last block", "Figure 2 legend")
    ]
    assert kinds(ref, guided) == {
        (("a",), ()): "missed, unaudited section",
        ((), ("1",)): "extra, unaudited section",
    }


def test_a_figure_title_is_matched_with_its_legend():
    ref = [
        claim("a", "Context shapes choice", "Figure 3 title", ClaimType.INTERPRETATION)
    ]
    guided = [claim("1", "Context shapes choice.", "Figure 3 legend")]
    groups = cc.match(ref, guided)
    assert [g.kind for g in groups] == ["same"]
    assert cc.differences(ref[0], guided[0]) == [
        "type: reference interpretation, guided new_result"
    ]


def test_a_repeated_sentence_does_not_join_matched_pairs():
    longer = f"Dots mark single sessions. {REPEATED}"
    ref = [
        claim("a", REPEATED, "Figure 1 legend", P),
        claim("b", longer, "Figure 1 legend", P),
    ]
    guided = [
        claim("1", REPEATED, "Figure 1 legend", P),
        claim("2", longer, "Figure 1 legend", P),
    ]
    assert kinds(ref, guided) == {(("a",), ("1",)): "same", (("b",), ("2",)): "same"}


def test_differences_name_facets_and_values():
    r = claim(
        "a", "mean shift was 12 ms", facets={"quantity": ("12 ms", ("shift 12ms",))}
    )
    g = claim(
        "1",
        "mean shift was 12 ms",
        facets={"quantity": ("12 ms", ("shift 12",)), "display": ("Figure 2", ())},
    )
    assert cc.differences(r, g) == [
        "display: only the guided run quotes it: “Figure 2”",
        "quantity values: reference shift 12ms; guided shift 12",
    ]
