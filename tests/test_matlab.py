# Copyright (c) 2026, Joshua I. Gold
# SPDX-License-Identifier: BSD-2-Clause

from pathlib import Path

import pytest

from rigoraudit import matlab


def test_matlab_is_found_on_the_path_or_where_it_is_installed(tmp_path, monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/matlab")
    assert matlab.find() == Path("/usr/bin/matlab")

    monkeypatch.setattr("shutil.which", lambda name: None)
    for release in ("MATLAB_R2025b.app", "MATLAB_R2026a.app"):
        (tmp_path / release / "bin").mkdir(parents=True)
        (tmp_path / release / "bin" / "matlab").touch()
    monkeypatch.setattr(matlab, "PLACES", (f"{tmp_path}/MATLAB_*.app/bin/matlab",))
    assert matlab.find() == tmp_path / "MATLAB_R2026a.app" / "bin" / "matlab"


def test_without_matlab_a_script_stops_and_says_why(tmp_path, monkeypatch):
    monkeypatch.setattr(matlab, "find", lambda: None)
    with pytest.raises(FileNotFoundError, match="MATLAB was not found"):
        matlab.run("x = 1", tmp_path)
