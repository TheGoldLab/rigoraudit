# Copyright (c) 2026, Joshua I. Gold
# SPDX-License-Identifier: BSD-2-Clause
import json

import pytest

from miragold import equations, pictures
from miragold.cli import main
from miragold.extract import EQUATIONS_FILE, PICTURES

# a 1×1 PNG
PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
    "1f15c4890000000d49444154789c6360000002000154a24f5d0000000049454e44ae426082"
)


@pytest.fixture
def workspace(tmp_path):
    (tmp_path / PICTURES).mkdir(parents=True)
    (tmp_path / PICTURES / "001.png").write_bytes(PNG)
    listed = [
        {"page": 2, "number": "1", "section": "Methods", "paragraph": 3,
         "text": "x = a + b (1)", "picture": "equations/001.png"},
        {"page": None, "number": None, "section": "Methods", "paragraph": 4,
         "text": "y = c", "picture": None},
    ]  # fmt: skip
    (tmp_path / EQUATIONS_FILE).write_text(json.dumps(listed), encoding="utf-8")
    return tmp_path


def test_read_typed_takes_text_or_latex_and_note(tmp_path):
    path = tmp_path / "equations.yaml"
    assert equations.read_typed(path) == {}
    path.write_text(
        "1: 'x = a + b'\n'1+1':\n  latex: |\n    y = c\n  note: unclear\n",
        encoding="utf-8",
    )
    assert equations.read_typed(path) == {
        "1": equations.Typed("x = a + b"),
        "1+1": equations.Typed("y = c", "unclear"),
    }
    path.write_text("1:\n  tex: x\n", encoding="utf-8")
    with pytest.raises(ValueError, match="equation 1"):
        equations.read_typed(path)


def test_page_puts_picture_beside_typed_version(workspace):
    (workspace / equations.TYPED).parent.mkdir()
    (workspace / equations.TYPED).write_text(
        "1: '\\frac{a}{b} < c'\n9: 'z'\n", encoding="utf-8"
    )
    text, n, done, unmatched = equations.page(workspace)
    assert (n, done, unmatched) == (2, 1, ["9"])
    assert 'data-tex="\\frac{a}{b} &lt; c"' in text
    assert text.count("data:image/png;base64,") == 1
    assert "No picture: not found in the PDF." in text
    assert "Equation 1+1" in text and "no number printed" in text
    assert "Not typed in yet" in text
    # KaTeX and its fonts are in the page, so it opens without a connection
    assert "katex.render" in text and "fonts/" not in text
    assert "data:font/woff2;base64," in text


def test_picture_and_typed_version_drawn_the_same_size(workspace):
    # a picture of 60 by 30 points, of an equation set in 12 point type
    width, height = 60 * pictures.SCALE, 30 * pictures.SCALE
    (workspace / PICTURES / "001.png").write_bytes(
        pictures.png(bytes(width * height), width, height)
    )
    listed = json.loads((workspace / EQUATIONS_FILE).read_text(encoding="utf-8"))
    listed[0]["size"] = 12
    (workspace / EQUATIONS_FILE).write_text(json.dumps(listed), encoding="utf-8")
    (workspace / equations.TYPED).parent.mkdir()
    (workspace / equations.TYPED).write_text("1: x\n'1+1': y\n", encoding="utf-8")
    text = equations.page(workspace)[0]
    z = equations.ZOOM
    assert f'width="{round(60 * z)}" height="{round(30 * z)}"' in text
    assert f'style="font-size: {12 * z:.1f}px"' in text
    # an equation listed without a size gets the usual one
    assert f'style="font-size: {equations.SIZE * z:.1f}px"' in text


def test_equations_command(workspace, capsys):
    main(["equations", str(workspace)])
    assert (workspace / equations.PAGE).is_file()
    assert "2 equations, 0 typed in" in capsys.readouterr().out
    with pytest.raises(SystemExit, match="run miragold extract first"):
        main(["equations", str(workspace / "elsewhere")])
