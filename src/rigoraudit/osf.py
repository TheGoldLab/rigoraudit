# Copyright (c) 2026, Joshua I. Gold
# SPDX-License-Identifier: BSD-2-Clause
"""Fetching the authors' files from an OSF project (osf.io).

OSF has no commits, so what was fetched is pinned by a list instead:
:data:`LISTING`, written beside the files, gives each file's path, size,
SHA-256, OSF version, and date modified, and says which files were left out
for being over the size limit (usually data, fetched separately if needed).
Every downloaded file is checked against the SHA-256 OSF gives for it.

Only the project's own OSF storage is read: not its components (child
projects) or add-on storage such as GitHub or Dropbox.
"""

from __future__ import annotations

import hashlib
import json
import re
import urllib.request
from collections.abc import Callable, Iterator
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath

from rigoraudit.words import plural

API = "https://api.osf.io/v2"
LISTING = "osf_files.json"
"""What was fetched, written in the destination folder."""
MAX_BYTES = 10_000_000
"""Files larger than this are listed but not fetched, unless asked for."""
NODE = re.compile(r"osf\.io/([a-z0-9]{5,})(?:[/?#]|$)", re.IGNORECASE)
NOT_NODES = {"download", "preprints", "registries", "search", "institutions"}
USER_AGENT = "rigoraudit (https://github.com/TheGoldLab/rigoraudit)"

GetJson = Callable[[str], dict]
Fetch = Callable[[str, Path], None]


def node_id(link: str) -> str | None:
    """The project's id in an OSF link (``https://osf.io/ab3cd/``), or ``None``."""
    m = NODE.search(link)
    if m is None or m.group(1).lower() in NOT_NODES:
        return None
    return m.group(1).lower()


@dataclass(frozen=True)
class File:
    path: str
    """Relative to the project's storage, with ``/`` between folders."""
    size: int
    sha256: str | None
    version: int | None
    modified: str | None
    download: str


@dataclass(frozen=True)
class Fetched:
    node: str
    fetched: list[File]
    kept: list[File]
    """Already in the folder with the right SHA-256, so not fetched again."""
    left_out: list[File]

    def describe(self) -> str:
        """One sentence on what was fetched, e.g. for the guide to show."""
        got = self.fetched + self.kept
        text = (
            f"The folder has {plural(len(got), 'file')} from OSF project {self.node} "
            f"({_total(got)}): "
        )
        text += (
            ", ".join(
                part
                for part in (
                    f"{len(self.fetched)} downloaded now" if self.fetched else "",
                    f"{len(self.kept)} already there" if self.kept else "",
                )
                if part
            )
            or "none"
        )
        if self.left_out:
            text += (
                f". Left out {plural(len(self.left_out), 'file')} over the size limit "
                f"({_total(self.left_out)})"
            )
        return text + "."


def _total(files: list[File]) -> str:
    return human_size(sum(f.size for f in files))


def human_size(n: int) -> str:
    for unit in ("bytes", "KB", "MB", "GB"):
        if n < 1000 or unit == "GB":
            return f"{n} {unit}" if unit == "bytes" else f"{n:.1f} {unit}"
        n /= 1000
    raise AssertionError


def _get_json(url: str) -> dict:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.load(response)


def _fetch(url: str, dest: Path) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=60) as response, dest.open("wb") as f:
        while chunk := response.read(1 << 20):
            f.write(chunk)


def _pages(url: str, get_json: GetJson) -> Iterator[dict]:
    while url:
        page = get_json(url)
        yield from page.get("data", [])
        url = (page.get("links") or {}).get("next")


def list_files(node: str, get_json: GetJson = _get_json) -> list[File]:
    """Every file in the project's OSF storage, folders walked, sorted by path."""
    files = []
    folders = [f"{API}/nodes/{node}/files/osfstorage/"]
    while folders:
        for item in _pages(folders.pop(), get_json):
            a = item["attributes"]
            if a["kind"] == "folder":
                folders.append(
                    item["relationships"]["files"]["links"]["related"]["href"]
                )
                continue
            path = a["materialized_path"].lstrip("/")
            if not path or any(p in ("", ".", "..") for p in path.split("/")):
                raise ValueError(f"OSF gave an unusable file path: {path!r}")
            files.append(
                File(
                    path=path,
                    size=a.get("size") or 0,
                    sha256=((a.get("extra") or {}).get("hashes") or {}).get("sha256"),
                    version=a.get("current_version"),
                    modified=a.get("date_modified"),
                    download=item["links"]["download"],
                )
            )
    return sorted(files, key=lambda f: f.path)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(1 << 20):
            digest.update(chunk)
    return digest.hexdigest()


def fetch(
    node: str,
    dest: Path,
    max_bytes: int | None = MAX_BYTES,
    files: list[File] | None = None,
    get_json: GetJson = _get_json,
    get_file: Fetch = _fetch,
) -> Fetched:
    """Download the project's files into ``dest`` and write :data:`LISTING`.

    Files over ``max_bytes`` (``None``: no limit) are left out. A file already
    in ``dest`` with OSF's SHA-256 is kept, so a stopped fetch can be rerun.
    A file whose SHA-256 does not match OSF's raises ``ValueError``, and is
    not kept.
    """
    if files is None:
        files = list_files(node, get_json)
    fetched, kept, left_out = [], [], []
    for f in files:
        if max_bytes is not None and f.size > max_bytes:
            left_out.append(f)
            continue
        target = dest.joinpath(*PurePosixPath(f.path).parts)
        if f.sha256 and target.is_file() and sha256(target) == f.sha256:
            kept.append(f)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        partial = target.with_name(target.name + ".part")
        get_file(f.download, partial)
        if f.sha256 and sha256(partial) != f.sha256:
            partial.unlink()
            raise ValueError(
                f"{f.path}: the downloaded file does not match OSF's SHA-256"
            )
        partial.replace(target)
        fetched.append(f)
    got = {f.path for f in fetched + kept}
    listing = {
        "source": f"https://osf.io/{node}/",
        "storage": "osfstorage",
        "max_bytes": max_bytes,
        "files": [
            {**asdict(f), "fetched": f.path in got}
            for f in sorted(files, key=lambda f: f.path)
        ],
    }
    for entry in listing["files"]:
        del entry["download"]
    dest.mkdir(parents=True, exist_ok=True)
    (dest / LISTING).write_text(json.dumps(listing, indent=1) + "\n", encoding="utf-8")
    return Fetched(node, fetched, kept, left_out)
