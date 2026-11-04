# Copyright (c) 2026, Joshua I. Gold
# SPDX-License-Identifier: BSD-2-Clause

import json
from fractions import Fraction

import pytest

from miragold.values import flatten, read_values, sha256, write_values


def test_flatten_nests_keys_and_converts_numeric_types():
    # numpy scalars register as numbers.Integral / numbers.Real, like Fraction
    flat = flatten({"durations": {"An": {"n": 19754, "mean": Fraction(901, 2)}}})
    assert flat == {"durations/An/n": 19754, "durations/An/mean": 450.5}
    assert type(flat["durations/An/n"]) is int
    assert type(flat["durations/An/mean"]) is float


def test_flatten_numbers_list_items_and_keeps_true_false():
    flat = flatten({"onsets": [3, 5.5], "pairs": [{"a": 1}, [True, "x"]], "ok": False})
    assert flat == {
        "onsets/0": 3,
        "onsets/1": 5.5,
        "pairs/0/a": 1,
        "pairs/1/0": True,
        "pairs/1/1": "x",
        "ok": False,
    }
    assert type(flat["pairs/1/0"]) is bool


class _ArrayLike:
    """Stands in for a numpy array or scalar, which convert with tolist()."""

    def __init__(self, value):
        self.value = value

    def tolist(self):
        return self.value


def test_flatten_converts_numpy_like_values():
    assert flatten({"a": _ArrayLike([1, 2]), "b": _ArrayLike(True)}) == {
        "a/0": 1,
        "a/1": 2,
        "b": True,
    }


@pytest.mark.parametrize("bad", [float("nan"), None, [], [1, None], {1, 2}])
def test_flatten_rejects_non_scalars_and_nan(bad):
    with pytest.raises((TypeError, ValueError)):
        flatten({"x": bad})


@pytest.mark.parametrize("name", ["a/b", ""])
def test_flatten_rejects_bad_key_parts(name):
    with pytest.raises(ValueError):
        flatten({name: 1})


def test_write_values_records_script_and_input_checksums(tmp_path):
    inputs = tmp_path / "derivations" / "output" / "t.csv"
    inputs.parent.mkdir(parents=True)
    inputs.write_text("a\n1\n", encoding="utf-8")
    script = tmp_path / "derivations" / "behavior.py"
    script.write_text("", encoding="utf-8")
    out = tmp_path / "derivations" / "output" / "values" / "behavior.json"

    write_values(out, {"n": 1}, script=script, inputs=[inputs], workspace=tmp_path)
    doc = read_values(out)
    assert doc == {
        "script": "derivations/behavior.py",
        "script_sha256": sha256(script),
        "inputs": {"derivations/output/t.csv": sha256(inputs)},
        "values": {"n": 1},
    }


def test_read_values_rejects_other_json(tmp_path):
    path = tmp_path / "x.json"
    path.write_text(json.dumps({"values": {}}), encoding="utf-8")
    with pytest.raises(ValueError):
        read_values(path)


def test_an_input_in_a_linked_folder_keeps_its_path_in_the_workspace(tmp_path):
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / "t.csv").write_text("a\n1\n", encoding="utf-8")
    ws = tmp_path / "audit"
    (ws / "materials").mkdir(parents=True)
    (ws / "materials" / "data").symlink_to(elsewhere)
    script = ws / "derivations" / "behavior.py"
    script.parent.mkdir()
    script.write_text("", encoding="utf-8")
    out = ws / "derivations" / "output" / "values" / "behavior.json"
    data = ws / "materials" / "data" / "t.csv"

    write_values(out, {"n": 1}, script=script, inputs=[data], workspace=ws)
    assert list(read_values(out)["inputs"]) == ["materials/data/t.csv"]
    with pytest.raises(ValueError, match="is not in the workspace"):
        write_values(
            out, {"n": 1}, script=script, inputs=[elsewhere / "t.csv"], workspace=ws
        )
