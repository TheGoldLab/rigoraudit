# Copyright (c) 2026, Joshua I. Gold
# SPDX-License-Identifier: BSD-2-Clause

import pytest

from miragold import settings

MANIFEST = """\
materials:
  manuscript:
    path: materials/manuscript/paper.pdf
    supplement: materials/manuscript/figures.pdf
    sha256: aaa
    also:
      - {path: manuscript/figures.pdf, sha256: bbb}
  code:
    path: code
    received_from: https://github.com/someone/analysis (cloned)
    commit: 0123456789abcdef0123456789abcdef01234567 (the last push)
  data:
    path: data
    files:
      - path: data/trials.csv
        sha256: ccc
      - path: data/notes.txt
"""


def load(tmp_path, text):
    (tmp_path / settings.MANIFEST).write_text(text, encoding="utf-8")
    return settings.load(tmp_path)


def test_what_is_read_from_the_manifest(tmp_path):
    s = load(tmp_path, MANIFEST)
    assert s.manuscript == "manuscript/paper.pdf"
    assert s.supplement == "manuscript/figures.pdf"
    assert s.code.repository == "https://github.com/someone/analysis"
    assert s.code.commit == "0123456789abcdef0123456789abcdef01234567"
    assert s.checksums == {
        "manuscript/paper.pdf": "aaa",
        "manuscript/figures.pdf": "bbb",
        "data/trials.csv": "ccc",
    }
    assert s.scope == settings.DEFAULT_SCOPE


def test_the_audited_sections(tmp_path):
    s = load(
        tmp_path, MANIFEST + "settings:\n  scope: [Results, 'Figure \\d+ legend$']\n"
    )
    assert s.scope == ("Results", r"Figure \d+ legend$")
    with pytest.raises(ValueError, match="not a pattern"):
        load(tmp_path, MANIFEST + "settings:\n  scope: ['Figure (']\n")


def test_whether_derive_scripts_run_without_asking(tmp_path):
    assert load(tmp_path, MANIFEST).derive_run == "auto"
    s = load(tmp_path, MANIFEST + "settings:\n  derive:\n    run: ask\n")
    assert s.derive_run == "ask"
    with pytest.raises(ValueError, match="derive › run must be auto or ask"):
        load(tmp_path, MANIFEST + "settings:\n  derive:\n    run: never\n")


def test_a_manifest_without_the_manuscript_is_an_error(tmp_path):
    with pytest.raises(FileNotFoundError, match="no audit.yaml"):
        settings.load(tmp_path)
    with pytest.raises(ValueError, match="manuscript › path is missing"):
        load(tmp_path, "materials: {}\n")


def test_the_gaps_in_the_materials(tmp_path):
    s = load(tmp_path, MANIFEST)
    assert s.gaps == ()
    s = load(
        tmp_path,
        MANIFEST
        + "gaps:\n"
        + "  - missing: No trial list.\n    instead: Rebuilt.\n    claims: R1.2.a\n"
        + "  - missing: No code for Figure 2.\n",
    )
    assert s.gaps == (
        settings.Gap("No trial list.", "Rebuilt.", ("R1.2.a",)),
        settings.Gap("No code for Figure 2."),
    )
    with pytest.raises(ValueError, match="gaps, entry 1: give missing:"):
        load(tmp_path, MANIFEST + "gaps:\n  - No code for Figure 2.\n")


def test_the_programs_derive_scripts_may_start(tmp_path):
    assert load(tmp_path, MANIFEST).derive_programs is None
    s = load(tmp_path, MANIFEST + "settings:\n  derive:\n    programs: [matlab]\n")
    assert s.derive_programs == ("matlab",)
    assert load(tmp_path, MANIFEST + "settings:\n  derive:\n    programs: []\n")
    with pytest.raises(ValueError, match="programs may list only matlab"):
        load(tmp_path, MANIFEST + "settings:\n  derive:\n    programs: [bash]\n")


@pytest.mark.parametrize(
    "tail",
    ["", "settings:\n  scope: [Results]\n", "settings:\n  derive:\n    run: ask\n"],
)
def test_the_answer_on_programs_is_written_into_the_manifest(tmp_path, tail):
    load(tmp_path, MANIFEST + tail)
    settings.set_programs(tmp_path, [])
    assert settings.load(tmp_path).derive_programs == ()
    assert MANIFEST in (tmp_path / settings.MANIFEST).read_text(
        encoding="utf-8"
    )  # the rest kept


def test_a_manifest_that_cannot_be_read_says_where(tmp_path):
    with pytest.raises(ValueError, match="cannot be read near line 2"):
        load(tmp_path, "materials: [\n")
    with pytest.raises(ValueError, match="should list entries"):
        load(tmp_path, "- paper.pdf\n")
