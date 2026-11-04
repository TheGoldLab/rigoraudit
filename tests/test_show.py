# Copyright (c) 2026, Joshua I. Gold
# SPDX-License-Identifier: BSD-2-Clause

import pytest
from test_compare import PRECISION, SILENT, answer, derived  # noqa: F401  (fixtures)
from test_derive import ws  # noqa: F401  (fixture)

from miragold import cli, compare, settings, show
from miragold.schema import RECORD


def test_before_compare_it_gives_what_each_source_says(derived):  # noqa: F811
    text = show.render(derived, "R1.1.a")
    assert text.startswith("# Claim R1.1.a\n")
    assert "## What each source says" in text
    assert "- `O1` (results, quoted; Results, paragraph 1)" in text
    assert "## Findings" not in text


def test_findings_name_their_observations_and_comparisons(derived):  # noqa: F811
    _, problems = compare.import_answer(derived, answer(PRECISION, SILENT), "T")
    assert problems == []
    text = show.render(derived, "R1.1.a")
    assert "### `R1.1.a/quantity`: consistent" in text
    assert "- Observations: O1, O2" in text
    assert "- Compared by reported precision" in text
    assert "— agrees" in text
    assert "- Why it cannot be compared: The data do not record the block." in text


def test_it_says_when_the_saved_record_is_older(derived):  # noqa: F811
    compare.write_record(derived, settings.load(derived))
    assert "Note:" not in show.render(derived, "R1.1.a")
    compare.import_answer(derived, answer(PRECISION, SILENT), "T")
    assert f"Note: {RECORD} is older" in show.render(derived, "R1.1.a")


def test_an_unknown_claim_names_the_form_of_an_id(derived, capsys):  # noqa: F811
    with pytest.raises(SystemExit, match="no claim R9.9.z.*look like R1.1.a"):
        cli.main(["show", "R9.9.z", str(derived)])
    cli.main(["show", "R1.1.a", str(derived)])
    assert capsys.readouterr().out.startswith("# Claim R1.1.a")
