# Copyright (c) 2026, Joshua I. Gold
# SPDX-License-Identifier: BSD-2-Clause
"""Feedback reports: written every run, sent only by the user (decision 0012).

Each command records what happened to the tool in ``work/feedback/log.jsonl``:
the step, how long it took, how it ended, and the kinds of any problems an
assistant's answer had (``miragold.handoffs.Problem``). Nothing from the
materials goes in: no problem's words, no error message, no path outside
the tool's own code. A failure is recorded by its type and the place in the
tool's code where it happened.

:func:`write_report` turns the log into one Markdown report for the whole
audit, ``work/feedback/report.md``, opening with a summary in plain
sentences. The sections the user writes (*In your words*, and audit
material added with ``miragold feedback --include``) are kept when the
report is rewritten. The tool never sends a report; ``miragold feedback``
says how to.
"""

from __future__ import annotations

import datetime
import json
import platform
import traceback
from collections import Counter
from collections.abc import Iterable
from importlib import metadata
from pathlib import Path, PurePath, PurePosixPath

from miragold import handoffs, instructions

FOLDER = PurePosixPath("work", "feedback")
LOG = FOLDER / "log.jsonl"
REPORT = FOLDER / "report.md"
ISSUES = "https://github.com/TheGoldLab/miragold/issues/new"
EMAIL: str | None = "jigold@pennmedicine.upenn.edu"
"""Where to send a report privately."""
YOUR_WORDS = "In your words"
MATERIAL = "Audit material you added"
_PROMPT = (
    "*(Optional. What were you trying to do, and what went wrong or was "
    "confusing? This section is kept when the report is updated.)*"
)


def _version() -> str:
    try:
        return metadata.version("miragold")
    except metadata.PackageNotFoundError:
        return "unknown"


def _now() -> datetime.datetime:
    return datetime.datetime.now().replace(microsecond=0)


def _read_log(workspace: Path) -> list[dict]:
    path = workspace / LOG
    if not path.is_file():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def record(
    workspace: Path,
    command: str,
    *,
    step: str | None = None,
    outcome: str,
    seconds: float | None = None,
    problems: Iterable[str] = (),
    handoff: str | None = None,
    error: BaseException | None = None,
    now: datetime.datetime | None = None,
) -> None:
    """Add one event to the log and rewrite the report.

    ``outcome`` is a fixed word (``wrote``, ``accepted``, ``sent back``,
    ``asked for code``, ``failed``, ...), never text from the materials.
    ``handoff`` lets the report count tries per answer; it is kept in the log
    but not printed.
    """
    event = {
        "time": (now or _now()).isoformat(),
        "command": command,
        "step": step,
        "instructions": instructions.load(step).label
        if step in ("segment", "decompose", "trace")
        else None,
        "outcome": outcome,
        "seconds": None if seconds is None else round(seconds, 1),
        "kinds": [handoffs.kind(p) for p in problems],
        "handoff": handoff,
        "error": None if error is None else where_it_failed(error),
    }
    path = workspace / LOG
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")
    write_report(workspace)


def where_it_failed(error: BaseException) -> str:
    """The error's type and the innermost place in the tool's own code, e.g.
    ``KeyError at miragold/trace.py:312 (check_requests)``. Not its message,
    which can carry text or file names from the materials."""
    package = PurePath(__file__).parent
    place = "outside the tool's code"
    for frame in traceback.extract_tb(error.__traceback__):
        path = PurePath(frame.filename)
        if path.is_relative_to(package):
            rel = path.relative_to(package.parent).as_posix()
            place = f"{rel}:{frame.lineno} ({frame.name})"
    return f"{type(error).__name__} at {place}"


def _user_sections(path: Path) -> dict[str, str]:
    """The sections the user writes, from an existing report."""
    if not path.is_file():
        return {}
    out, current = {}, None
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            current = line[3:].strip()
            if current in (YOUR_WORDS, MATERIAL):
                out[current] = []
            continue
        if current in out:
            out[current].append(line)
    return {k: "\n".join(v).strip() for k, v in out.items()}


def write_report(workspace: Path) -> Path:
    """Write (or rewrite) the report from the log."""
    events = _read_log(workspace)
    path = workspace / REPORT
    kept = _user_sections(path)
    lines = [
        "# miragold feedback report",
        "",
        (
            "This report was written by the tool and has not been sent anywhere. It "
            "holds what happened to the tool, not what is in your audit: no text, "
            "values, or file names from your materials. Read it before sending it; "
            "`miragold feedback` says how."
        ),
        "",
        "## Summary",
        "",
        *_summary(events),
        "",
        f"## {YOUR_WORDS}",
        "",
        kept.get(YOUR_WORDS) or _PROMPT,
        "",
        "## The tool",
        "",
        f"- miragold {_version()}",
        f"- Python {platform.python_version()}",
        f"- {platform.system()} {platform.release()} ({platform.machine()})",
        "",
        "## What happened",
        "",
        "Each command, for the developers; the summary above says the same in words.",
        "",
        "| Time | Command | Step | Instructions | Outcome | Seconds | Problems |",
        "|---|---|---|---|---|---|---|",
    ]
    for e in events:
        kinds = ", ".join(f"{k} ×{n}" for k, n in Counter(e["kinds"]).items())
        lines.append(
            f"| {e['time'].replace('T', ' ')} | {e['command']} | {e['step'] or ''} | "
            f"{e['instructions'] or ''} | {e['outcome']} | "
            f"{'' if e['seconds'] is None else e['seconds']} | {kinds} |"
        )
    tries = _tries(events)
    if tries:
        lines += ["", "## Tries per accepted answer", ""]
        for step, counts in tries.items():
            lines.append(f"- {step}: {', '.join(map(str, counts))}")
    totals = Counter((e["step"], k) for e in events for k in e["kinds"])
    if totals:
        lines += ["", "## Problems sent back, by kind", ""]
        lines += [f"- {step}: {k} ×{n}" for (step, k), n in sorted(totals.items())]
    failures = [e for e in events if e["error"]]
    if failures:
        lines += ["", "## Failures", ""]
        lines += [f"- {e['command']} {e['step'] or ''}: {e['error']}" for e in failures]
    if MATERIAL in kept:
        lines += [
            "",
            f"## {MATERIAL}",
            "",
            kept[MATERIAL],
        ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return path


def _times(n: int) -> str:
    return "once" if n == 1 else f"{n} times"


def _when(event: dict) -> str:
    day = datetime.datetime.fromisoformat(event["time"])
    return f"{day.day} {day:%B %Y} at {day:%H:%M}"


def _summary(events: list[dict]) -> list[str]:
    """The report in a few plain sentences, for the user deciding whether to
    send it."""
    if not events:
        return ["Nothing has run yet."]
    runs = sum(e["command"] == "audit" for e in events)
    span = f"from {_when(events[0])} to {_when(events[-1])}"
    guide = f"; the guide ran {_times(runs)}" if runs else ""
    out = [f"- This report covers the whole audit so far, {span}{guide}."]
    steps = list(dict.fromkeys(e["step"] for e in events if e["step"]))
    if steps:
        out.append(f"- Steps worked on: {', '.join(steps)}.")
    imports = [e for e in events if e["command"] == "import"]
    accepted = sum(e["outcome"] == "accepted" for e in imports)
    sent_back = sum(e["outcome"] == "sent back" for e in imports)
    if imports:
        out.append(
            f"- The assistant's answers: {accepted} accepted, "
            f"{sent_back} sent back to be fixed."
        )
    retried = [n for counts in _tries(events).values() for n in counts if n > 1]
    if retried:
        out.append(
            f"- {len(retried)} of the accepted answers needed more than one try "
            f"(at most {max(retried)})."
        )
    elif accepted:
        out.append("- Every accepted answer was right the first time.")
    kinds = Counter(k for e in events for k in e["kinds"])
    if kinds:
        reasons = "; ".join(
            f"{k.replace('-', ' ')} ({_times(n)})" for k, n in kinds.most_common()
        )
        out.append(f"- Why answers were sent back: {reasons}.")
    checks = [e for e in events if e["command"] == "check"]
    if checks:
        out.append(
            "- The last check of the record passed."
            if checks[-1]["outcome"] == "passed"
            else "- The last check of the record found problems to fix."
        )
    failures = sum(bool(e["error"]) for e in events)
    out.append(
        f"- The tool itself broke {_times(failures)} (see Failures below)."
        if failures
        else "- The tool itself did not break."
    )
    if failures:
        advice = "This is worth sending: the tool broke, which is a bug."
    elif retried or sent_back:
        advice = (
            "Worth sending if you like: answers that had to be sent back can "
            "show where the instructions to the assistant are unclear."
        )
    else:
        advice = (
            "Nothing here needs sending, unless something confused you; if it "
            "did, say what under *In your words* and send it."
        )
    return [*out, "", advice]


def _tries(events: list[dict]) -> dict[str, list[int]]:
    """For each step, how many replies each accepted answer took."""
    sent: Counter = Counter()
    out: dict[str, list[int]] = {}
    for e in events:
        if e["command"] != "import" or e["handoff"] is None:
            continue
        sent[e["handoff"]] += 1
        if e["outcome"] == "accepted":
            out.setdefault(e["step"], []).append(sent.pop(e["handoff"]))
    return out


def include(workspace: Path, file: Path) -> Path:
    """Add ``file``'s text to the latest report, as audit material."""
    path = workspace / REPORT
    if not path.is_file():
        raise FileNotFoundError("no feedback report yet; run a step first")
    kept = _user_sections(path)
    text = file.read_text(encoding="utf-8", errors="replace").rstrip()
    added = f"From `{file.name}`:\n\n```\n{text}\n```"
    material = "\n\n".join(filter(None, [kept.get(MATERIAL), added]))
    body = path.read_text(encoding="utf-8")
    if MATERIAL in kept:
        body = body[: body.index(f"## {MATERIAL}")].rstrip() + "\n"
    path.write_text(body + f"\n## {MATERIAL}\n\n{material}\n", encoding="utf-8")
    return path


def explain(workspace: Path) -> str:
    """What ``miragold feedback`` prints: the latest report and how to send it."""
    path = workspace / REPORT
    if not path.is_file():
        return "No feedback report yet: it is written when a step first runs."
    has_material = MATERIAL in _user_sections(path)
    lines = [
        f"The feedback report is {REPORT.as_posix()}.",
        "",
        "It holds the tool's version, your Python and operating system, the steps",
        "run and how each ended, and the kinds of problems found in assistants'",
        "answers. It holds no text, values, or file names from your materials"
        + (", except the audit material you added." if has_material else "."),
        "Open it and read it first: its summary says in a few sentences what",
        "happened and whether it is worth sending. You can add your own words.",
        "",
        "Nothing is sent unless you send it. To send it:",
        (
            f"- as a public issue on the tool's page: {ISSUES}"
            "  (paste the report in; anyone can read it)"
        ),
        f"- privately, by email: {EMAIL}"
        if EMAIL
        else "- privately, by email: the address is not set in this version",
    ]
    if has_material:
        lines += [
            "",
            (
                "The report includes audit material you added, so send it by email, "
                "not as a public issue."
            ),
        ]
    return "\n".join(lines)
