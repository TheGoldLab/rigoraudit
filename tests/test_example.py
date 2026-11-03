# Copyright (c) 2026, Joshua I. Gold
# SPDX-License-Identifier: BSD-2-Clause
"""The example audit rebuilds from its materials, matches what is committed, and passes its checks."""

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from rigoraudit import cli, status
from rigoraudit.schema import RECORD, AuditRecord
from rigoraudit.values import sha256
from rigoraudit.verify import Outcome

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "example-audit"
BUILT = (
    "work/materials/files.md",
    "work/extract/paragraphs.json",
    "work/extract/published.txt",
    "work/extract/outline.json",
    "record/record.json",
    "report/audit.html",
    "work/checks.json",
    "work/crosscheck/findings.json",
    "README.md",
)


@pytest.fixture(scope="module")
def rebuilt(tmp_path_factory) -> Path:
    """A copy of the example, rebuilt from its materials by its own scripts and
    the tool's commands, as rebuild.sh runs them."""
    ws = tmp_path_factory.mktemp("example") / "example-audit"
    shutil.copytree(EXAMPLE, ws, ignore=shutil.ignore_patterns("review", "__pycache__"))
    for line in (EXAMPLE / "rebuild.sh").read_text(encoding="utf-8").splitlines():
        if m := re.match(r"uv run python \$W/(\S+)", line):
            subprocess.run(
                [sys.executable, ws / m[1]],
                check=True,
                capture_output=True,
                env=os.environ | {"PYTHONUTF8": "1"},
            )
        elif m := re.match(r"uv run rigoraudit (\w+) \$W", line):
            cli.main([m[1], str(ws)])
    return ws


def test_rebuild_matches_what_is_committed(rebuilt):
    for path in BUILT:
        assert (rebuilt / path).read_text(encoding="utf-8") == (
            EXAMPLE / path
        ).read_text(encoding="utf-8"), path
    # The values, apart from the script checksum, which a copy shares anyway
    out = "derivations/output/values/trials.json"
    assert json.loads((rebuilt / out).read_text(encoding="utf-8")) == json.loads(
        (EXAMPLE / out).read_text(encoding="utf-8")
    )


def test_manifest_checksums_match_the_materials():
    # Each checksum belongs to the nearest path above it
    pairs, path = [], None
    for line in (EXAMPLE / "audit.yaml").read_text(encoding="utf-8").splitlines():
        if m := re.match(r"\s*-?\s*path: (\S+)$", line):
            path = m.group(1)
        elif m := re.match(r"\s*sha256: (\w+)$", line):
            pairs.append((path, m.group(1)))
    assert len(pairs) == 3
    for path, digest in pairs:
        assert sha256(EXAMPLE / "materials" / path) == digest, path


def test_every_check_passes(rebuilt):
    checks = status.load_checks(rebuilt)
    assert checks.anchors == {Outcome.VERIFIED: 10}
    assert checks.items > 0 and checks.uncovered == 0


def test_statuses_are_those_the_readme_describes(rebuilt):
    record = AuditRecord.model_validate_json(
        (rebuilt / RECORD).read_text(encoding="utf-8")
    )
    assert {f.id: f.status for f in record.findings} == {
        "R1.2.a/population": "consistent",
        "R1.2.a/quantity": "differs",
        "R1.2.b/quantity": "consistent",
        "R1.2.b/analysis": "differs",
    }
