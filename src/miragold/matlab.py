# Copyright (c) 2026, Joshua I. Gold
# SPDX-License-Identifier: BSD-2-Clause
"""Start MATLAB from a derivation script.

A derivation that runs the authors' MATLAB code calls :func:`run` rather
than starting MATLAB itself::

    from miragold import matlab

    matlab.run("addpath('code'); make_figure_2", folder=MATERIALS)

:func:`find` looks for MATLAB on the command path, then where it is
usually installed. The derive step's script checks let a script use this
module without asking only if the manifest allows it
(``settings: derive: programs: [matlab]``). MATLAB itself is not checked:
the code it runs can do anything a program can.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

PLACES = (
    "/Applications/MATLAB_*.app/bin/matlab",
    "/usr/local/MATLAB/*/bin/matlab",
    "C:/Program Files/MATLAB/*/bin/matlab.exe",
)
"""Where MATLAB is usually installed, newest release last when sorted."""


def find() -> Path | None:
    """MATLAB's program file, or ``None`` if it is not on this computer."""
    if on_path := shutil.which("matlab"):
        return Path(on_path)
    for pattern in PLACES:
        anchor = Path(pattern.split("*")[0]).parent
        rest = str(Path(pattern).relative_to(anchor))
        found = sorted(anchor.glob(rest)) if anchor.is_dir() else []
        if found:
            return found[-1]
    return None


def run(code: str, folder: Path) -> None:
    """Run MATLAB ``code`` with ``folder`` as MATLAB's current folder, and
    wait for it; an error in the code stops the script."""
    program = find()
    if program is None:
        raise FileNotFoundError(
            "MATLAB was not found on this computer (on the command path, or in "
            "the usual places). Install it, or put its bin folder on the path."
        )
    subprocess.run([str(program), "-batch", code], cwd=folder, check=True)
