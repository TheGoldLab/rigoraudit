# Copyright (c) 2026, Joshua I. Gold
# SPDX-License-Identifier: BSD-2-Clause

import json
import re
from pathlib import Path

import pytest

from miragold import cli, decompose, instructions, segment
from miragold.decompose import (
    AnswerError,
    check_answer,
    parse_answer,
    read_printed,
    results_observations,
)
from miragold.schema import Facet, Relation

TEXT = (
    "Rats pressed faster in block A (Figure 2). Twelve rats completed 40 trials each."
)
CLAIMS = {
    "R1.1.a": "Rats pressed faster in block A",
    "R1.1.b": "Twelve rats completed 40 trials each.",
}
WHERE = {"R1.1.a": "R1.1", "R1.1.b": "R1.1"}
PARAS = {"R1.1": TEXT}


def answer(claims, version="decompose v4"):
    return parse_answer(json.dumps({"instructions": version, "claims": claims}))


GOOD = [
    {"id": "R1.1.a", "facets": [
        {"facet": "quantity", "quote": "pressed faster", "states": "Rats pressed faster."},
        {"facet": "condition", "quote": "in block A", "states": "In block A."},
        {"facet": "display", "quote": "(Figure 2)", "states": "Shown in Figure 2."},
    ]},
    {"id": "R1.1.b", "facets": [
        {"facet": "population", "quote": "Twelve rats", "states": "There were 12 rats.",
         "values": [{"name": "rats", "printed": "Twelve"}]},
        {"facet": "quantity", "quote": "40 trials each", "states": "Each completed 40 trials.",
         "values": [{"name": "trials", "printed": "40", "subject": "per rat"}]},
    ]},
]  # fmt: skip


def test_example_in_the_instructions_passes():
    text = instructions.load("decompose").text
    example = text[text.index("## Example") :]
    [(label, quote)] = re.findall(r"Paragraph `([^`]+)`:\n\n((?:>.*\n)+)", example)
    paragraph = " ".join(
        line.removeprefix("> ").strip() for line in quote.strip().splitlines()
    )
    claims = dict(re.findall(r'`(R2\.1\.[a-z])` "([^"]+)"', example.replace("\n", " ")))
    assert set(claims) == {"R2.1.a", "R2.1.b"}
    assert all(q in paragraph for q in claims.values())
    where = dict.fromkeys(claims, label)
    assert check_answer(parse_answer(example), claims, where, {label: paragraph}) == []


@pytest.mark.parametrize(
    ("text", "value", "unit", "relation", "decimals"),
    [
        ("3,600", 3600, None, Relation.EQ, 0),
        ("87%", 87, "%", Relation.EQ, 0),
        ("120 ms", 120, "ms", Relation.EQ, 0),
        ("< 0.01", 0.01, None, Relation.LT, 2),
        ("~4.50 s", 4.5, "s", Relation.APPROX, 2),
        ("∼100 ms", 100, "ms", Relation.APPROX, 0),
        ("Twelve", 12, None, Relation.EQ, 0),
        ("−0.3", -0.3, None, Relation.EQ, 1),
        # powers of ten, the superscript flattened in the PDF's text or not
        ("<10−317", 1e-317, None, Relation.LT, 317),
        ("10⁻⁵", 1e-5, None, Relation.EQ, 5),
        ("< 10^-5", 1e-5, None, Relation.LT, 5),
        ("2.3×10−5 s", 2.3e-5, "s", Relation.EQ, 6),
        ("2.3e-5", 2.3e-5, None, Relation.EQ, 6),
        # no leading zero, as in many journals' style for p
        ("= .047", 0.047, None, Relation.EQ, 3),
        # fractions show no decimal places
        ("13/16", 13 / 16, None, Relation.EQ, None),
        ("3 / 4 trials", 0.75, "trials", Relation.EQ, None),
    ],
)
def test_values_are_read_from_printed_text(text, value, unit, relation, decimals):
    p = read_printed(text)
    assert (p.value, p.unit, p.relation, p.decimals) == (
        value,
        unit,
        relation,
        decimals,
    )


@pytest.mark.parametrize(
    ("quote", "printed", "units"),
    [
        ("latency 168.25 ± 4.1 ms", ("168.25", "4.1 ms"), ["ms", "ms"]),
        ("5–10% of trials", ("5", "10%"), ["%", "%"]),
        ("from 2 to 6 s", ("2", "6 s"), ["s", "s"]),
        # not joined, or no unit to carry: left as printed
        ("12 rats ran 40 trials", ("12", "40 trials"), [None, "trials"]),
        ("3.1 ± 0.2 (SEM)", ("3.1", "0.2"), [None, None]),
        # a number inside another one is not the value
        ("15 ± 4 ms and 5 Hz", ("5 Hz", "4 ms"), ["Hz", "ms"]),
    ],
)
def test_a_value_takes_the_unit_printed_after_it(quote, printed, units):
    values = [
        decompose.StatedValue(name=f"v{i}", printed=p) for i, p in enumerate(printed)
    ]
    assert [p.unit for p in decompose.read_stated(values, quote)] == units


@pytest.mark.parametrize(
    # "10-5" may be a range; 10^-400 is too small to store
    "text",
    [
        "0.45 ± 0.03",
        "many",
        "12 and 15",
        "5–10%",
        "",
        "10-5",
        "<10−400",
        "3/0",
        "3/4/5",
    ],
)
def test_text_that_is_not_one_number(text):
    assert read_printed(text) is None


def test_good_answer_has_no_problems():
    assert check_answer(answer(GOOD), CLAIMS, WHERE, PARAS) == []


def test_copied_tests_are_checked():
    text = "Rats pressed faster in block A, t(22) = 2.10, p = .047 (n = 24 rats)."
    claims = {"R1.1.a": "Rats pressed faster in block A"}
    facets = [
        {
            "facet": "quantity",
            "quote": "t(22) = 2.10, p = .047 (n = 24 rats)",
            "states": "Rats pressed faster.",
        }
    ]
    good = {
        "quote": "t(22) = 2.10, p = .047",
        "statistic": "t",
        "value": "2.10",
        "df": ["22"],
        "p": "= .047",
        "n": "24",
        "n_quote": "n = 24 rats",
    }

    def problems(**test):
        a = answer([{"id": "R1.1.a", "facets": facets, "tests": [{**good, **test}]}])
        return check_answer(a, claims, {"R1.1.a": "R1.1"}, {"R1.1": text})

    assert problems() == []
    assert [p.kind for p in problems(quote="t(22) = 2.15")] == ["quote-not-found"]
    assert [p.kind for p in problems(p="= .05")] == ["value-not-in-quote"]
    assert [p.kind for p in problems(df=["22", "1"])] == ["df-count"]
    assert [p.kind for p in problems(n_quote=None)] == ["value-not-in-quote"]
    assert [p.kind for p in problems(statistic=None)] == ["statistic-missing"]
    assert [p.kind for p in problems(statistic=None, value=None)] == ["test-unnamed"]


def test_a_test_printed_with_p_only_is_copied_by_its_name():
    text = "Rats pressed faster in block A (permutation test, p = 0.003)."
    claims = {"R1.1.a": "Rats pressed faster in block A"}
    facets = [{"facet": "quantity", "quote": "permutation test, p = 0.003",
               "states": "Rats pressed faster."}]  # fmt: skip
    test = {"quote": "p = 0.003", "named": "permutation test", "p": "= 0.003"}
    a = answer([{"id": "R1.1.a", "facets": facets, "tests": [test]}])
    assert check_answer(a, claims, {"R1.1.a": "R1.1"}, {"R1.1": text}) == []


def test_every_claim_answered_once_and_only_those_given():
    extra = {"id": "R9.1.a", "facets": GOOD[0]["facets"]}
    problems = check_answer(answer([GOOD[0], GOOD[0], extra]), CLAIMS, WHERE, PARAS)
    assert problems == [
        "Claim R1.1.a is answered more than once.",
        "Claim R9.1.a was not given; answer only the claims given.",
        "Claim R1.1.b has no answer; give its facets.",
    ]


def test_quotes_values_and_numbers_are_checked():
    b = {"id": "R1.1.b", "facets": [
        {"facet": "population", "quote": "Twelve rats", "states": "s",
         "values": [{"name": "rats", "printed": "12"}]},
        {"facet": "population", "quote": "ed", "states": "s"},
        {"facet": "quantity", "quote": "40 trials", "states": "s",
         "values": [{"name": "trials", "printed": "40 trials"}]},
    ]}  # fmt: skip
    problems = check_answer(answer([GOOD[0], b]), CLAIMS, WHERE, PARAS)
    assert problems == [
        "Claim R1.1.b gives the population facet more than once.",
        "The value '12' (rats) is not in the population quote for claim R1.1.b word for word.",
        (
            "The population quote for claim R1.1.b appears 2 times in paragraph R1.1; "
            "make it longer so it appears once: 'ed'"
        ),
    ]
    c = {
        "id": "R1.1.b",
        "facets": [{"facet": "population", "quote": "Twelve rats", "states": "s"}],
    }
    [problem] = check_answer(answer([GOOD[0], c]), CLAIMS, WHERE, PARAS)
    assert problem.startswith(
        "Claim R1.1.b states numbers that no facet's quote contains (40)"
    )


def test_bad_facet_name_is_described():
    bad = [{"id": "R1.1.a", "facets": [{"facet": "size", "quote": "q", "states": "s"}]}]
    with pytest.raises(
        AnswerError, match="In claim 1, facet 1, facet: Input should be"
    ):
        parse_answer(json.dumps({"instructions": "decompose v4", "claims": bad}))


# --- From segment answers to observations ------------------------------------

EXAMPLE = Path(__file__).parent.parent / "examples" / "example-audit"


def test_example_audit_from_segment_to_results_observations(tmp_path, capsys):
    extract = tmp_path / "work" / "extract" / "paragraphs.json"
    extract.parent.mkdir(parents=True)
    extract.write_text(
        (EXAMPLE / "work/extract/paragraphs.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    segment.write_handoffs(tmp_path)
    seg = {
        "instructions": "segment v3",
        "claims": [
            {"id": "R1.2.a", "paragraph": "R1.2", "type": "new_result",
             "quote": "Twelve mice completed 3,600 trials over 10 sessions."},
            {"id": "R1.2.b", "paragraph": "R1.2", "type": "new_result",
             "quote": "Accuracy rose from 60% in session 1 to 87% in session 10"},
        ],
        "left_out": [{"paragraph": "R1.1", "quote": "(4 and 8 kHz)", "reason": "task"}],
    }  # fmt: skip
    assert segment.import_answer(tmp_path, json.dumps(seg), "test")[1] == []

    cli.main(["handoff", "decompose", str(tmp_path)])
    assert "decompose-R1.2.a.md" in capsys.readouterr().out
    reply = tmp_path / "reply.txt"
    dec = {
        "instructions": "decompose v4",
        "claims": [
            {"id": "R1.2.a", "facets": [
                {"facet": "population", "quote": "Twelve mice", "states": "12 mice.",
                 "values": [{"name": "mice", "printed": "Twelve"}]},
                {"facet": "quantity", "quote": "3,600 trials over 10 sessions",
                 "states": "3,600 trials over 10 sessions.",
                 "values": [{"name": "trials", "printed": "3,600"},
                            {"name": "sessions", "printed": "10"}]},
            ]},
            {"id": "R1.2.b", "facets": [
                {"facet": "quantity", "quote": "rose from 60% in session 1 to 87% in session 10",
                 "states": "Accuracy rose from 60% to 87%.",
                 "values": [{"name": "accuracy", "printed": "60%", "subject": "session 1"},
                            {"name": "accuracy", "printed": "87%", "subject": "session 10"}]},
                {"facet": "display", "quote": "(Figure 1)", "states": "Shown in Figure 1."},
            ]},
        ],
    }  # fmt: skip
    reply.write_text(json.dumps(dec), encoding="utf-8")
    cli.main(["import", "decompose", str(reply), str(tmp_path), "--by", "test"])
    assert capsys.readouterr().out.startswith(
        "Accepted decompose-R1.2.a: 4 facets of 2 claims"
    )
    assert decompose.write_handoffs(tmp_path) == []

    obs = results_observations(tmp_path, "manuscript.txt")
    values = {
        (v.name, v.subject): (v.value, v.unit)
        for v in obs["R1.2.b"][Facet.QUANTITY].values
    }
    assert values == {
        ("accuracy", "session 1"): (60, "%"),
        ("accuracy", "session 10"): (87, "%"),
    }
    a = obs["R1.2.a"][Facet.POPULATION].anchor
    assert (a.section, a.paragraph, a.quote, a.page) == (
        "Results › Learning",
        2,
        "Twelve mice",
        2,
    )
