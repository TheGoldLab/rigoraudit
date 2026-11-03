# Copyright (c) 2026, Joshua I. Gold
# SPDX-License-Identifier: BSD-2-Clause

import hashlib
import json

import pytest

from rigoraudit import osf

API = "https://api.osf.io/v2/nodes/ab3cd/files/osfstorage/"
CONTENT = {
    "README.md": b"Run fit.py.\n",
    "code/fit.py": b"print('fit')\n",
    "data/trials.csv": b"x" * 2000,
}


def entry(path, content=None, sha=None):
    """One item of an OSF listing: a file, or a folder when ``content`` is None."""
    name = path.rstrip("/").rsplit("/", 1)[-1]
    if content is None:
        return {"attributes": {"kind": "folder", "name": name,
                               "materialized_path": f"/{path}"},
                "relationships": {"files": {"links": {"related": {
                    "href": f"{API}{name}/"}}}},
                "links": {}}  # fmt: skip
    return {"attributes": {"kind": "file", "name": name, "materialized_path": f"/{path}",
                           "size": len(content), "current_version": 2,
                           "date_modified": "2025-01-02T03:04:05",
                           "extra": {"hashes": {"sha256": sha or hashlib.sha256(content).hexdigest()}}},
            "relationships": {}, "links": {"download": f"https://osf.io/download/{path}"}}  # fmt: skip


class FakeOsf:
    """The listing in two pages, with two folders; counts the downloads."""

    def __init__(self, bad_sha=None, path=None):
        top = path or "README.md"
        self.pages = {
            API: {"data": [entry(top, CONTENT["README.md"], bad_sha), entry("code/")],
                  "links": {"next": f"{API}?page=2"}},
            f"{API}?page=2": {"data": [entry("data/")], "links": {"next": None}},
            f"{API}code/": {"data": [entry("code/fit.py", CONTENT["code/fit.py"])]},
            f"{API}data/": {"data": [entry("data/trials.csv", CONTENT["data/trials.csv"])]},
        }  # fmt: skip
        self.downloads = []

    def get_json(self, url):
        return self.pages[url]

    def get_file(self, url, dest):
        path = url.removeprefix("https://osf.io/download/")
        self.downloads.append(path)
        dest.write_bytes(CONTENT[path])


@pytest.mark.parametrize(
    ("link", "node"),
    [
        ("https://osf.io/ab3cd/", "ab3cd"),
        ("https://osf.io/AB3CD", "ab3cd"),
        ("osf.io/ab3cd/files/osfstorage", "ab3cd"),
        ("https://osf.io/download/xy9zw/", None),
        ("https://github.com/example/repo", None),
    ],
)
def test_the_project_id_is_read_from_its_link(link, node):
    assert osf.node_id(link) == node


def test_every_file_is_listed_across_pages_and_folders():
    files = osf.list_files("ab3cd", FakeOsf().get_json)
    assert [(f.path, f.size, f.version) for f in files] == [
        ("README.md", 12, 2),
        ("code/fit.py", 13, 2),
        ("data/trials.csv", 2000, 2),
    ]


def test_large_files_are_left_out_and_everything_is_listed(tmp_path):
    fake = FakeOsf()
    result = osf.fetch("ab3cd", tmp_path, 1000, None, fake.get_json, fake.get_file)
    assert (tmp_path / "code" / "fit.py").read_bytes() == CONTENT["code/fit.py"]
    assert not (tmp_path / "data").exists()
    assert [f.path for f in result.left_out] == ["data/trials.csv"]
    listing = json.loads((tmp_path / osf.LISTING).read_text())
    assert listing["source"] == "https://osf.io/ab3cd/"
    assert [(f["path"], f["fetched"]) for f in listing["files"]] == [
        ("README.md", True),
        ("code/fit.py", True),
        ("data/trials.csv", False),
    ]
    assert listing["files"][2]["sha256"] == hashlib.sha256(b"x" * 2000).hexdigest()
    assert result.describe() == (
        "The folder has 2 files from OSF project ab3cd (25 bytes): 2 downloaded "
        "now. Left out 1 file over the size limit (2.0 KB)."
    )


def test_a_rerun_fetches_only_what_is_missing(tmp_path):
    fake = FakeOsf()
    osf.fetch("ab3cd", tmp_path, 1000, None, fake.get_json, fake.get_file)
    (tmp_path / "README.md").write_text("changed")
    fake.downloads.clear()
    result = osf.fetch("ab3cd", tmp_path, None, None, fake.get_json, fake.get_file)
    assert sorted(fake.downloads) == ["README.md", "data/trials.csv"]
    assert [f.path for f in result.kept] == ["code/fit.py"]
    assert (tmp_path / "README.md").read_bytes() == CONTENT["README.md"]


def test_a_file_that_does_not_match_its_checksum_is_not_kept(tmp_path):
    fake = FakeOsf(bad_sha="0" * 64)
    with pytest.raises(ValueError, match="README.md: the downloaded file does not"):
        osf.fetch("ab3cd", tmp_path, None, None, fake.get_json, fake.get_file)
    assert not (tmp_path / "README.md").exists()
    assert not list(tmp_path.glob("*.part"))


def test_a_path_out_of_the_folder_is_refused():
    with pytest.raises(ValueError, match="unusable file path"):
        osf.list_files("ab3cd", FakeOsf(path="../README.md").get_json)


@pytest.mark.parametrize(
    ("n", "text"), [(999, "999 bytes"), (1500, "1.5 KB"), (9_100_000_000, "9.1 GB")]
)
def test_sizes_are_written_for_people(n, text):
    assert osf.human_size(n) == text
