# Copyright (c) 2026, Joshua I. Gold
# SPDX-License-Identifier: BSD-2-Clause

import numpy as np
import scipy.io

from rigoraudit import materials
from rigoraudit.settings import Gap, Settings

S = Settings(manuscript="paper/paper.pdf")


def workspace(tmp_path, files):
    for rel, text in files.items():
        p = tmp_path / "materials" / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    return tmp_path


def test_data_saved_in_the_code_folder_is_listed_with_what_it_holds(tmp_path):
    ws = workspace(tmp_path, {"paper/paper.pdf": "", "code/run.m": "x = 1;"})
    saved = tmp_path / "materials/code/results/selected.mat"
    saved.parent.mkdir(parents=True)
    scipy.io.savemat(saved, {"chosen": {"left": np.arange(3), "right": np.arange(2)}})
    (tmp_path / "materials/data").mkdir()
    (tmp_path / "materials/data/trials.csv").write_text(
        "session,rt\n1,0.5\n", encoding="utf-8"
    )
    by_path = {f.path: f for f in materials.list_files(ws, S)}
    assert by_path["paper/paper.pdf"].kind == "paper"
    assert by_path["code/run.m"].kind == "code"
    mat = by_path["code/results/selected.mat"]
    assert mat.kind == "data"
    assert "chosen (1×1 struct: left, right)" in mat.holds
    assert {"chosen", "left", "right"} <= set(mat.names)
    assert by_path["data/trials.csv"].holds == "first row: session, rt"


def test_reads_are_matched_to_files_saves_and_nothing(tmp_path):
    # in the materials; saved below; on the authors' computer only;
    # commented out; a name built while running; command form
    code = r"""load(fullfile(outDir, 'selected'))
load(fullfile(outDir, ['fit_S' num2str(s)]), 'w')
save(fullfile(outDir, ['fit_S' num2str(s)]), 'w')
load('C:\work\palette')
% load('commented_out')
load(matName);
load ../results/other.mat"""
    ws = workspace(
        tmp_path,
        {
            "paper/paper.pdf": "",
            "code/a.m": code,
            "code/results/selected.mat": "",
            "code/b.py": "import pandas as pd\nd = pd.read_csv('data/trials.csv')\n"
            "open('out.txt', 'w')\n",
            "data/trials.csv": "a\n",
        },
    )
    reads = {r.name: r for r in materials.code_reads(ws, S)}
    assert reads["selected.mat"].found == ("code/results/selected.mat",)
    assert reads["fit_S*.mat"].made == ("code/a.m:3",)
    assert not reads["palette.mat"].found and not reads["palette.mat"].made
    assert reads[None].line == 6
    assert reads["results/other.mat"].found == ()
    assert reads["data/trials.csv"].found == ("data/trials.csv",)
    assert "commented_out.mat" not in reads and "out.txt" not in reads
    text = materials.render(ws, S)
    assert "not in the materials, and not made by the code (2)" in text
    assert "- `palette.mat`: read in `code/a.m` line 4" in text


def test_gap_notes_name_data_and_functions_but_not_scripts(tmp_path):
    ws = workspace(
        tmp_path,
        {
            "paper/paper.pdf": "",
            "code/run_all.m": "function run_all\nfunction smooth_rates\n",
            "code/+stats/fit.m": "",
            "code/out/cell_lists.csv": "cell_id\n",
        },
    )
    gaps = (
        Gap(missing="run_all.m calls smooth_rates, which is not included."),
        Gap(missing="The +stats package, and the saved cell_lists.csv."),
        Gap(missing="The list of cell_id values."),
    )
    notes = materials.gap_notes(ws, S, gaps)
    assert [n.split(",")[0] for n in notes] == [
        "Gap 1 names smooth_rates",
        "Gap 2 names +stats",
        "Gap 2 names cell_lists.csv",
        "Gap 3 names cell_id",
    ]


def test_the_list_is_written_only_when_it_changes(tmp_path):
    ws = workspace(tmp_path, {"paper/paper.pdf": ""})
    assert materials.write_list(ws, S)
    assert not materials.write_list(ws, S)
    (tmp_path / "materials/new.csv").write_text("x\n", encoding="utf-8")
    assert materials.write_list(ws, S)
    assert "`new.csv` (data" in (ws / materials.LIST).read_text(encoding="utf-8")


def test_an_archive_is_listed_with_the_files_inside_it(tmp_path):
    import tarfile
    import zipfile

    ws = workspace(tmp_path, {"paper/paper.pdf": "", "data/notes.7z": "x"})
    with zipfile.ZipFile(tmp_path / "materials/data/raw.zip", "w") as z:
        z.writestr("raw/session_1.mat", "")
        z.writestr("raw/session_2.mat", "")
    inner = tmp_path / "fits.csv"
    inner.write_text("a\n", encoding="utf-8")
    with tarfile.open(tmp_path / "materials/data/fits.tar.gz", "w:gz") as tar:
        tar.add(inner, arcname="fits/fits.csv")
    by_path = {f.path: f for f in materials.list_files(ws, S)}
    raw = by_path["data/raw.zip"]
    assert raw.kind == "archive"
    assert raw.holds == "2 files: raw/session_1.mat, raw/session_2.mat"
    assert raw.names == ("session_1.mat", "session_2.mat")
    assert by_path["data/fits.tar.gz"].holds == "1 file: fits/fits.csv"
    assert (
        by_path["data/notes.7z"].holds == "its files are not listed here (a .7z file)"
    )
