# Copyright (c) 2026, Joshua I. Gold
# SPDX-License-Identifier: BSD-2-Clause
"""Every file in the materials, and what the code reads (decision 0014).

:func:`list_files` lists each file under ``materials/``, wherever it is
(data saved inside the code repository included), with its kind, its size,
and, for a data file, what it holds: the variables of a MATLAB file (and
the fields of each structure), the columns of a table, the arrays of a
NumPy archive; for an archive (``.zip``, ``.tar.gz``), the files inside it. :func:`code_reads` finds each call in the code that reads a
file named in the code itself (``load(fullfile(outDir, 'trial_lists'))``,
``pd.read_csv("trials.csv")``) and says whether the file is in the
materials, made by the code, or neither. Calls that build the name while
the code runs are counted, not followed.

The guide writes both to :data:`LIST` at every run, so that nothing is
called missing without a look at what is there, and the derive step's
handoffs list the files with what they hold. :func:`gap_notes` points out
names a gap gives that are in the materials, for ``rigoraudit check`` to
show. Like the code index, the reads are found by line patterns, not by
running the code: a map, not a record.
"""

from __future__ import annotations

import fnmatch
import json
import re
import tarfile
import zipfile
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

import scipy.io
from scipy.io.matlab import MatReadError

from rigoraudit import codeindex, docs
from rigoraudit.osf import human_size
from rigoraudit.settings import Gap, Settings
from rigoraudit.words import plural

LIST = PurePosixPath("work", "materials", "files.md")
"""The list of the materials, written at every run of the guide."""
DATA_SUFFIXES = {
    ".mat", ".csv", ".tsv", ".npy", ".npz", ".h5", ".hdf5", ".nc", ".nwb",
    ".xlsx", ".xls", ".json", ".pkl", ".pickle", ".parquet", ".feather",
    ".rds", ".rdata", ".rda", ".sav", ".dta", ".dat", ".bin", ".txt", ".zarr",
}  # fmt: skip
ARCHIVE_SUFFIXES = (".zip", ".tar", ".tar.gz", ".tgz", ".tar.bz2", ".tar.xz")
"""Archives whose files are listed; ``.7z``, ``.rar``, and ``.gz`` are
listed as archives without their files."""
OTHER_ARCHIVES = (".7z", ".rar", ".gz", ".bz2", ".xz")
MAX_TAR = 500_000_000
"""Bytes: a larger compressed tar file is listed without its files, since
listing them means reading it all (a zip file's list is at its end)."""
MAX_LOOK = 2_000_000_000
"""Bytes: a larger data file is listed without looking inside."""
MAX_STRUCT = 50_000_000
"""Bytes: in a larger MATLAB file, structures are listed without fields."""
MAX_NAMES = 30
"""Names listed for one file."""


@dataclass(frozen=True)
class Material:
    path: str
    """Relative to ``materials/``, with ``/``."""
    kind: str
    """``paper``, ``code``, ``documentation``, ``data``, ``archive``, or ``other``."""
    size: int
    holds: str = ""
    """For a data file: its variables, columns, or arrays; for an archive, its
    files; or why they are not listed."""
    names: tuple[str, ...] = ()
    """The names in ``holds``, struct fields included, and the names of an
    archive's files."""


@dataclass(frozen=True)
class Read:
    file: str
    """The code file, relative to ``materials/``."""
    line: int
    call: str
    """The function that reads (``load``, ``read_csv``)."""
    name: str | None
    """The file read, as the code names it (``*`` for a part built while the
    code runs); ``None`` if the code builds the whole name."""
    found: tuple[str, ...] = ()
    """Files in the materials with that name."""
    made: tuple[str, ...] = ()
    """Where the code saves a file with that name (``file:line``)."""


def walk(workspace: Path) -> list[Path]:
    """Every file under ``materials/``, leaving out the code's history;
    linked folders are followed, each once."""
    root = workspace / "materials"
    files, seen = [], set()
    for folder, dirs, names in root.walk(follow_symlinks=True):
        if folder.resolve() in seen:
            dirs.clear()  # a link back to a folder already listed
            continue
        seen.add(folder.resolve())
        dirs[:] = sorted(d for d in dirs if not d.startswith("."))
        files += [folder / n for n in names if not n.startswith(".")]
    return sorted(p for p in files if p.is_file())


def _kind(rel: PurePosixPath, size: int, settings: Settings) -> str:
    paper = PurePosixPath(settings.manuscript).parent
    if rel.as_posix() in (settings.manuscript, settings.supplement) or (
        paper != PurePosixPath(".") and rel.is_relative_to(paper)
    ):
        return "paper"
    suffix = rel.suffix.lower()
    if suffix in codeindex.LANGUAGES or suffix == codeindex.NOTEBOOK:
        return "code"
    name = rel.name.lower()
    if name.endswith(ARCHIVE_SUFFIXES + OTHER_ARCHIVES):
        return "archive"
    if docs._kind(rel.name, size) is not None:
        return "documentation"
    return "data" if suffix in DATA_SUFFIXES else "other"


def _mat(path: Path) -> tuple[str, tuple[str, ...]]:
    try:
        variables = scipy.io.whosmat(str(path))
    except (NotImplementedError, ValueError, OSError, MatReadError):
        with path.open("rb") as f:
            head = f.read(128)
        if b"MATLAB 7.3" in head:
            return "a MATLAB 7.3 file; its variables are not listed here", ()
        return "not readable as a MATLAB file", ()
    names, shown = [], []
    for name, shape, cls in variables:
        what = f"{'×'.join(map(str, shape))} {cls}"
        if cls == "struct" and path.stat().st_size <= MAX_STRUCT:
            try:
                value = scipy.io.loadmat(str(path), variable_names=[name])[name]
                fields = value.dtype.names or ()
            except (NotImplementedError, ValueError, OSError, MatReadError):
                fields = ()
            if fields:
                what += f": {', '.join(fields)}"
                names += fields
        names.append(name)
        shown.append(f"{name} ({what})")
    return "variables: " + _some(shown), tuple(names)


def _some(items: Sequence[str]) -> str:
    more = len(items) - MAX_NAMES
    return ", ".join(items[:MAX_NAMES]) + (f", and {more} more" if more > 0 else "")


def holds(path: Path) -> tuple[str, tuple[str, ...]]:
    """What a data file holds, in words, and the names in it."""
    size = path.stat().st_size
    suffix = path.suffix.lower()
    if size > MAX_LOOK:
        return f"too large to look inside here ({human_size(size)})", ()
    try:
        if suffix == ".mat":
            return _mat(path)
        if suffix in (".csv", ".tsv"):
            with path.open(encoding="utf-8", errors="replace") as f:
                first = f.readline().strip()
            cells = [
                c.strip(' "') for c in first.split("\t" if suffix == ".tsv" else ",")
            ]
            return "first row: " + _some(cells), tuple(cells)
        if suffix == ".npz":
            with zipfile.ZipFile(path) as z:
                arrays = [n.removesuffix(".npy") for n in z.namelist()]
            return "arrays: " + _some(arrays), tuple(arrays)
        if suffix == ".json" and size <= MAX_STRUCT:
            value = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(value, dict):
                keys = [str(k) for k in value]
                return "keys: " + _some(keys), tuple(keys)
            if isinstance(value, list) and value and isinstance(value[0], dict):
                keys = [str(k) for k in value[0]]
                return (
                    f"{len(value)} {'entry' if len(value) == 1 else 'entries'}, the first "
                    "with keys: " + _some(keys),
                    tuple(keys),
                )
    except (OSError, ValueError, zipfile.BadZipFile):
        return "not readable as its name suggests", ()
    return "", ()


def archive_holds(path: Path) -> tuple[str, tuple[str, ...]]:
    """The files inside an archive, in words, and their names."""
    name = path.name.lower()
    if not name.endswith(ARCHIVE_SUFFIXES):
        return f"its files are not listed here (a {path.suffix} file)", ()
    try:
        if name.endswith(".zip"):
            with zipfile.ZipFile(path) as z:
                inside = [i.filename for i in z.infolist() if not i.is_dir()]
        elif path.stat().st_size > MAX_TAR and not name.endswith(".tar"):
            size = human_size(path.stat().st_size)
            return f"too large to list its files here ({size})", ()
        else:
            with tarfile.open(path) as tar:
                inside = [m.name for m in tar.getmembers() if m.isfile()]
    except (OSError, zipfile.BadZipFile, tarfile.TarError):
        return "not readable as its name suggests", ()
    inside = [n for n in inside if not PurePosixPath(n).name.startswith(".")]
    names = tuple(dict.fromkeys(PurePosixPath(n).name for n in inside))
    return f"{plural(len(inside), 'file')}: " + _some(inside), names


def list_files(workspace: Path, settings: Settings) -> list[Material]:
    """Every file in the materials, with its kind, size, and what it holds."""
    root = workspace / "materials"
    out = []
    for p in walk(workspace):
        rel = PurePosixPath(p.relative_to(root).as_posix())
        size = p.stat().st_size
        kind = _kind(rel, size, settings)
        what, names = (
            holds(p)
            if kind == "data"
            else archive_holds(p)
            if kind == "archive"
            else ("", ())
        )
        out.append(Material(rel.as_posix(), kind, size, what, names))
    return out


# --- What the code reads ----------------------------------------------------

_CALLS = {
    ".m": (
        (
            r"load|importdata|readtable|readtimetable|readmatrix|readcell|csvread"
            r"|dlmread|xlsread|matfile|h5read|h5info|imread|audioread|dir"
        ),
        r"save|writetable|writematrix|writecell|csvwrite|dlmwrite|xlswrite|h5write",
    ),
    ".py": (
        (
            r"(?:np\.|numpy\.)?load|loadtxt|genfromtxt|read_\w+|loadmat|open_dataset"
            r"|File|open"
        ),
        r"save|savez|savez_compressed|savetxt|savemat|to_\w+|dump",
    ),
    ".r": (
        r"read\.\w+|read_\w+|readRDS|load|fread|readxl::read_\w+",
        r"write\.\w+|write_\w+|saveRDS|save|fwrite",
    ),
    ".jl": (
        r"matread|load|readdlm|CSV\.read|CSV\.File|h5open|jldopen",
        r"matwrite|save|writedlm|CSV\.write",
    ),
}
_JOIN = re.compile(
    r"^(?:fullfile|os\.path\.join|file\.path|joinpath|Path)\s*\((.*)\)$", re.DOTALL
)
_STRING = re.compile(
    r"""(?P<f>[fFrRbB]{0,2})(?P<q>["'])(?P<s>(?:(?!(?P=q)).)*)(?P=q)"""
)
_MODE = re.compile(r"""^\s*["'][wax]""")
_DATA_GLOB = re.compile(r"\.\w+$")


def _call(lines: Sequence[str], n: int, start: int, comment: str = "") -> list[str]:
    """The top-level arguments of the call whose ``(`` ends at ``start`` on
    line ``n`` (0-based), following it over at most ten lines; ``comment``
    starts a comment outside a string."""
    args, depth, cur, quote = [], 1, [], None
    for k in range(n, min(n + 10, len(lines))):
        text = lines[k][start:] if k == n else lines[k]
        text = text.replace("...", " ") if text.rstrip().endswith("...") else text
        prev = ""
        for ch in text:
            if quote:
                cur.append(ch)
                if ch == quote:
                    quote = None
            elif ch in "'\"" and not (
                ch == "'" and (prev.isalnum() or prev in ")]}._")
            ):
                quote = ch
                cur.append(ch)
            elif ch in "([{":
                depth += 1
                cur.append(ch)
            elif ch in ")]}":
                depth -= 1
                if depth == 0:
                    args.append("".join(cur).strip())
                    return args
                cur.append(ch)
            elif ch == "," and depth == 1:
                args.append("".join(cur).strip())
                cur = []
            elif comment and ch == comment:
                break  # a comment to the end of the line
            else:
                cur.append(ch)
            if not ch.isspace():
                prev = ch
        quote = None
    return args


def _name(arg: str) -> str | None:
    """The file an argument names, ``*`` for the parts built while the code
    runs; ``None`` if no part is written out."""
    name = _written(arg)
    if name is None:
        return None
    name = re.sub(r"\*+", "*", name.replace("\\", "/"))
    if re.match(r"^(?:[A-Za-z]:/|/|~)", name):
        name = name.rsplit("/", 1)[-1]  # a path on the authors' computer
    name = re.sub(r"/+", "/", name.rsplit("../", 1)[-1])
    name = name.removeprefix("*/").removeprefix("./")
    return name if re.search(r"[A-Za-z0-9]", name) else None


def _written(arg: str) -> str | None:
    arg = arg.strip()
    if m := _JOIN.match(arg):
        parts = [_written(a) for a in _call([m.group(1) + ")"], 0, 0)]
        while parts and parts[0] is None:
            parts.pop(0)  # a folder held in a variable
        if not parts:
            return None
        return "/".join((p or "*").strip("/") for p in parts)
    pieces, at = [], 0
    for m in _STRING.finditer(arg):
        if arg[at : m.start()].strip(" +[]/"):
            pieces.append("*")
        s = m.group("s")
        if "f" in m.group("f").lower():
            s = re.sub(r"\{[^}]*\}", "*", s)
        pieces.append(s)
        at = m.end()
    if not any(p != "*" for p in pieces):
        return None
    if arg[at:].strip(" +[]/"):
        pieces.append("*")
    return "".join(pieces)


def _calls_in(
    file: str, lines: Sequence[str]
) -> list[tuple[str, int, str, str | None]]:
    """``(read or write, line, call, name)`` for each call in a code file."""
    suffix = codeindex.code_suffix(file, list(lines))
    if suffix not in _CALLS:
        return []
    comment = codeindex.LANGUAGES[suffix]["comment"]
    reads, writes = _CALLS[suffix]
    pattern = re.compile(rf"(?<![\w.])(?:(\w+)\.)?({reads}|{writes})\s*\(")
    is_write = re.compile(rf"^(?:{writes})$")
    command = re.compile(r"^\s*(load|save)\s+([^\s;,%(]+)") if suffix == ".m" else None
    out = []
    for n, line in enumerate(lines):
        if line.lstrip().startswith(comment):  # type: ignore[arg-type]
            continue
        if command and (m := command.match(line)) and not m.group(2).startswith("-"):
            name = _name(f"'{m.group(2)}'") or m.group(2)
            name += "" if PurePosixPath(name).suffix else ".mat"
            out.append(
                ("write" if m.group(1) == "save" else "read", n + 1, m.group(1), name)
            )
            continue
        for m in pattern.finditer(line):
            call = m.group(2)
            if (
                suffix == ".py"
                and call in ("load", "dump")
                and m.group(1) in ("json", "pickle", "yaml")
            ):
                continue  # reads an open file, not a name
            args = _call(lines, n, m.end(), comment)  # type: ignore[arg-type]
            if not args:
                continue
            name = _name(args[0])
            write = bool(is_write.match(call))
            if call in ("open", "File", "h5open", "jldopen") and len(args) > 1:
                write = bool(_MODE.match(args[1]))
            if (
                suffix == ".m"
                and call in ("load", "save", "matfile")
                and name
                and not PurePosixPath(name).suffix
            ):
                name += ".mat"
            if call == "dir" and not (name and _DATA_GLOB.search(name)):
                continue  # a folder listing that is not of data
            out.append(("write" if write else "read", n + 1, call, name))
    return out


def _matches(name: str, paths: Sequence[str]) -> tuple[str, ...]:
    want = name.lower().split("/")
    return tuple(
        p
        for p in paths
        if len(parts := p.lower().split("/")) >= len(want)
        and all(fnmatch.fnmatchcase(a, b) for a, b in zip(parts[-len(want) :], want))
    )


def code_reads(
    workspace: Path, settings: Settings, files: Sequence[Material] | None = None
) -> list[Read]:
    """Each read call in the code, with the files in the materials it names
    and where the code saves a file of that name."""
    root = workspace / "materials"
    files = list_files(workspace, settings) if files is None else files
    paths = [f.path for f in files if f.kind != "code"]
    calls = []
    for f in files:
        if f.kind == "code":
            lines = codeindex.read_lines(root / f.path)
            calls += [(f.path, *c) for c in _calls_in(f.path, lines)]
    saved: dict[str, list[str]] = defaultdict(list)
    for file, how, line, _, name in calls:
        if (
            how == "write"
            and name
            and re.search(r"[A-Za-z0-9]", PurePosixPath(name).stem)
        ):
            saved[PurePosixPath(name).name.lower()].append(f"{file}:{line}")
    out = []
    for file, how, line, call, name in calls:
        if how != "read":
            continue
        if name is None:
            out.append(Read(file, line, call, None))
            continue
        base = PurePosixPath(name).name.lower()
        made = tuple(
            w
            for k, where in saved.items()
            if fnmatch.fnmatchcase(k, base) or fnmatch.fnmatchcase(base, k)
            for w in where
        )
        out.append(Read(file, line, call, name, _matches(name, paths), made))
    return out


# --- The list, for people and assistants ------------------------------------


def describe(f: Material) -> str:
    """One file, for a list: path, size, and what it holds."""
    return f"{f.path} ({human_size(f.size)})" + (f": {f.holds}" if f.holds else "")


def _where(reads: Sequence[Read]) -> str:
    places = [f"`{r.file}` line {r.line}" for r in reads]
    more = len(places) - 3
    return ", ".join(places[:3]) + (f", and {more} more" if more > 0 else "")


def render(workspace: Path, settings: Settings) -> str:
    """The list of the materials and of what the code reads, as Markdown."""
    files = list_files(workspace, settings)
    reads = code_reads(workspace, settings, files)
    kinds = defaultdict(int)
    for f in files:
        kinds[f.kind] += 1
    out = [
        "# The materials",
        "",
        (
            "Written by rigoraudit at every run of `rigoraudit audit`; do not edit. "
            "Every file in `materials/` (paths relative to it), and what the code "
            "reads. Look here before recording anything as missing."
        ),
        "",
        ", ".join(plural(n, f"{k} file") for k, n in sorted(kinds.items())) + ".",
    ]
    by_name: dict[str, list[Read]] = defaultdict(list)
    for r in reads:
        if r.name:
            by_name[r.name].append(r)
    groups = (
        ("Read by the code, but not in the materials, and not made by the code",
         lambda rs: not rs[0].found and not rs[0].made),
        ("Read by the code, and made by it (not shared)",
         lambda rs: not rs[0].found and rs[0].made),
        ("Read by the code, and in the materials", lambda rs: rs[0].found),
    )  # fmt: skip
    out += ["", "## What the code reads"]
    for title, test in groups:
        names = sorted(n for n, rs in by_name.items() if test(rs))
        out += ["", f"### {title} ({len(names)})", ""]
        for n in names:
            rs = by_name[n]
            line = f"- `{n}`: read in {_where(rs)}"
            if rs[0].found:
                line += f"; in the materials as {', '.join(f'`{p}`' for p in rs[0].found[:3])}"
                if len(rs[0].found) > 3:
                    line += f", and {len(rs[0].found) - 3} more"
            elif rs[0].made:
                line += f"; saved in {', '.join(f'`{w}`' for w in rs[0].made[:3])}"
            out.append(line)
        if not names:
            out.append("(none)")
    built = [r for r in reads if r.name is None]
    if built:
        out += [
            "",
            (
                f"{plural(len(built), 'read')} build the file's name while the code "
                f"runs, so are not followed here: {_where(built)}."
            ),
        ]
    out += ["", "## Files"]
    folder = None
    for f in files:
        parent = PurePosixPath(f.path).parent.as_posix()
        if parent != folder:
            folder = parent
            out += [
                "",
                f"### `{parent}/`" if parent != "." else "### The top folder",
                "",
            ]
        out.append(
            f"- `{PurePosixPath(f.path).name}` ({f.kind}, {human_size(f.size)})"
            + (f": {f.holds}" if f.holds else "")
        )
    return "\n".join(out) + "\n"


def write_list(workspace: Path, settings: Settings) -> bool:
    """Write :data:`LIST`; say whether what it says has changed."""
    path = workspace / LIST
    text = render(workspace, settings)
    if path.is_file() and path.read_text(encoding="utf-8") == text:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return True


def gap_notes(workspace: Path, settings: Settings, gaps: Sequence[Gap]) -> list[str]:
    """For each gap that names things in the materials, one note listing
    them: a data file, a name saved in one, a function defined inside a
    code file of another name, or a package folder (``+name``). Code files a
    gap names are left out: gaps name the scripts they are about."""
    files = list_files(workspace, settings)
    root = workspace / "materials"
    where: dict[str, set[str]] = defaultdict(set)
    for f in files:
        p = PurePosixPath(f.path)
        for part in p.parent.parts:
            if part.startswith(("+", "@")):
                where[part.lower()].add(f"{p.parent.as_posix()}/")
        if f.kind == "code":
            lines = codeindex.read_lines(root / f.path)
            if codeindex.code_suffix(f.path, lines) not in codeindex.LANGUAGES:
                continue
            for name, line in codeindex.index_lines(f.path, lines).functions:
                if name.lower() != p.stem.lower():
                    where[name.lower()].add(f"{f.path} line {line}")
            continue
        if f.kind == "data":
            where[p.name.lower()].add(f.path)
            where[p.stem.lower()].add(f.path)
        for name in f.names:
            where[name.lower()].add(f"{f.path} holds it")
    out = []
    for i, g in enumerate(gaps, start=1):
        named = []
        for word in dict.fromkeys(re.findall(r"[+@]?[A-Za-z_][\w.]*\w", g.missing)):
            key = word.lower()
            if len(key) < 4 or not re.search(r"[_.\d+@]|[a-z][A-Z]", word):
                continue
            if key not in where:
                continue
            found = sorted(where[key])
            more = f", and {len(found) - 1} more" if len(found) > 1 else ""
            named.append(f"{word} ({found[0]}{more})")
        if named:
            out.append(f"Gap {i} names {'; '.join(named)}, in the materials.")
    return out
