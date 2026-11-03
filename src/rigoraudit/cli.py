# Copyright (c) 2026, Joshua I. Gold
# SPDX-License-Identifier: BSD-2-Clause
"""Command-line entry point: ``rigoraudit``."""

from __future__ import annotations

import argparse
import getpass
import subprocess
import time
from collections.abc import Sequence
from pathlib import Path

from rigoraudit import (
    breaks,
    check,
    compare,
    crosscheck,
    decompose,
    derive,
    docs,
    equations,
    extract,
    feedback,
    guide,
    header,
    materials,
    osf,
    report,
    segment,
    server,
    settings,
    show,
    trace,
)
from rigoraudit.handoffs import paste_back
from rigoraudit.paragraphs import PARAGRAPHS
from rigoraudit.words import plural

STEPS = {
    "breaks": breaks,
    "docs": docs,
    "segment": segment,
    "decompose": decompose,
    "trace": trace,
    "derive": derive,
    "compare": compare,
    "crosscheck": crosscheck,
    "header": header,
}
"""The steps an assistant does, in the order they are done."""


def _default_reviewer() -> str:
    try:
        name = subprocess.run(
            ["git", "config", "user.name"], capture_output=True, text=True, check=False
        ).stdout.strip()
    except OSError:
        name = ""
    return name or getpass.getuser()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="rigoraudit",
        description="Audit a paper together with its code and data. Every command "
        "works on one audit's folder (its workspace): the current folder, unless "
        "you name another.",
    )
    commands = parser.add_subparsers(dest="command", required=True, metavar="command")

    def command(name: str, help: str) -> argparse.ArgumentParser:
        return commands.add_parser(name, help=help, description=help)

    command(
        "audit",
        "the guided audit: takes you through every step in order, and picks up "
        "where you left off; makes the folder if it does not exist",
    )
    ex = command(
        "extract",
        f"write the paper's paragraphs to {PARAGRAPHS}, from the publisher's XML "
        "or the PDF",
    )
    ex.add_argument(
        "--replace",
        action="store_true",
        help="replace an existing paragraphs file (it may hold your corrections)",
    )
    ex.add_argument(
        "--grobid",
        metavar="URL",
        help="read the PDF with the GROBID server at URL, if there is no "
        "publisher's XML (default: the manifest's settings › extract › grobid)",
    )
    ho = command(
        "handoff", "write the files to give an assistant for one step of the audit"
    )
    ho.add_argument("step", choices=list(STEPS), help="the step")
    ho.add_argument(
        "--script",
        action="append",
        dest="scripts",
        metavar="FILE",
        default=[],
        help="docs: a script the run will start, relative to materials/, whose "
        "opening comment is read too; repeat for more (adds to the manifest's "
        "settings › run › scripts)",
    )
    ho.add_argument(
        "--max-chars",
        type=int,
        metavar="N",
        default=segment.MAX_CHARS,
        help=f"segment and decompose: paragraph text per file (default: "
        f"{segment.MAX_CHARS})",
    )
    im = command(
        "import", "check an assistant's reply to a handoff, and save it if it passes"
    )
    im.add_argument("step", choices=list(STEPS), help="the step")
    im.add_argument("reply", type=Path, help="the reply, saved as a text file")
    im.add_argument(
        "--by",
        required=True,
        help="who or what wrote the reply: your name, or the assistant's (with its model, if known)",
    )
    im.add_argument(
        "--handoff", help="the handoff it answers (default: worked out from the reply)"
    )
    command(
        "materials",
        f"list every file in materials/, with what each data file holds, and "
        f"what the code reads, in {materials.LIST}",
    )
    command(
        "record",
        f"build the record, {compare.RECORD}, from the accepted answers (not for "
        f"an audit with its own {compare.SCRIPT})",
    )
    command(
        "check",
        "check every quote, code line, checksum, and value in the record against "
        "the materials, and list checkable statements no claim covers",
    )
    sh = command(
        "show",
        "print everything the audit holds on one claim: what each source says, "
        "the findings, the gaps that name it, and the review actions on it",
    )
    sh.add_argument("claim", help="the claim's ID, e.g. R1.2.a")
    command(
        "report",
        f"write the report page, {report.PAGE}: the paper beside a card for each "
        "claim, from the reviewed record",
    )
    rv = command(
        "review",
        "show the report in your browser, with review actions on each claim and "
        "finding (served on this computer only)",
    )
    rv.add_argument(
        "--reviewer", metavar="NAME", help="your name (default: git's user.name)"
    )
    rv.add_argument("--port", type=int, default=8765, help="(default: 8765)")
    command(
        "equations",
        "write work/equations.html: each display equation as printed, beside your "
        "typed-in version from derivations/equations.yaml",
    )
    of = command(
        "osf",
        f"download an OSF project's files, checking each one, and list them in "
        f"{osf.LISTING}",
    )
    of.add_argument("link", help="the project's link, e.g. https://osf.io/<id>/")
    of.add_argument("dest", type=Path, help="the folder to put the files in")
    of.add_argument(
        "--list",
        action="store_true",
        help="only list the files and their sizes; download nothing",
    )
    size = of.add_mutually_exclusive_group()
    size.add_argument(
        "--max-mb",
        type=float,
        default=osf.MAX_BYTES / 1e6,
        help="leave out files larger than this, in MB "
        f"(default: {osf.MAX_BYTES / 1e6:g})",
    )
    size.add_argument(
        "--all", action="store_true", help="download every file, whatever its size"
    )
    fb = command(
        "feedback",
        "show the latest feedback report and how to send it (nothing is sent)",
    )
    fb.add_argument(
        "--include",
        type=Path,
        help="add this file's text to the report, marked as audit material",
    )
    for name, sub in commands.choices.items():
        if name != "osf":  # after the command's own positional arguments
            sub.add_argument(
                "workspace",
                type=Path,
                nargs="?",
                default=Path("."),
                help="the audit's folder (default: the current folder)",
            )
    return parser


def main(argv: list[str] | None = None) -> None:
    args = _parser().parse_args(argv)
    if args.command == "osf":
        _osf(args.link, args.dest, args.list, None if args.all else args.max_mb)
        return
    workspace = args.workspace
    # a missing or malformed file is the user's to fix: say which, in a line
    try:
        if args.command == "audit":
            guide.Guide(workspace).run()
        elif args.command == "extract":
            _recorded(
                workspace,
                "extract",
                "extract",
                lambda: _extract(workspace, args.replace, args.grobid),
            )
        elif args.command == "handoff":
            _recorded(
                workspace,
                "handoff",
                args.step,
                lambda: _handoff(args.step, workspace, args.max_chars, args.scripts),
            )
        elif args.command == "import":
            _recorded(
                workspace,
                "import",
                args.step,
                lambda: _import(
                    args.step, workspace, args.reply, args.by, args.handoff
                ),
            )
        elif args.command == "materials":
            materials.write_list(workspace, settings.load(workspace))
            print(f"Wrote {materials.LIST}.")
        elif args.command == "record":
            path = compare.write_record(workspace, settings.load(workspace))
            print(f"Wrote {path.relative_to(workspace)}.")
        elif args.command == "check":
            result = check.run(workspace)
            print(check.describe(result))
            if not result.passed:
                raise SystemExit(1)
        elif args.command == "show":
            print(show.render(workspace, args.claim), end="")
        elif args.command == "report":
            page = report.write(workspace).resolve()
            print(
                f"Wrote the report. To read it, open this file in your browser:\n{page}"
            )
        elif args.command == "review":
            server.serve(
                workspace, args.reviewer or _default_reviewer(), port=args.port
            )
        elif args.command == "equations":
            print(equations.write_page(workspace))
        elif args.command == "feedback":
            if args.include:
                path = feedback.include(workspace, args.include)
                print(f"Added {args.include.name} to {path.relative_to(workspace)}.\n")
            print(feedback.explain(workspace))
    except (FileNotFoundError, ValueError) as e:
        raise SystemExit(str(e)) from e


def _recorded(workspace: Path, command: str, step: str, run) -> None:
    """Run a step's command and add what happened to the feedback report.

    ``run`` returns ``(outcome, problems, handoff)``; problems mean the reply
    was sent back, and the command exits with status 1.
    """
    if not (workspace / settings.MANIFEST).is_file():
        if run()[1]:
            raise SystemExit(1)
        return
    start = time.monotonic()
    try:
        outcome, problems, handoff = run()
    except Exception as e:
        feedback.record(
            workspace,
            command,
            step=step,
            outcome="failed",
            seconds=time.monotonic() - start,
            error=e,
        )
        raise
    feedback.record(
        workspace,
        command,
        step=step,
        outcome=outcome,
        seconds=time.monotonic() - start,
        problems=problems,
        handoff=handoff,
    )
    if problems:
        raise SystemExit(1)


def _approve_run(script: Path, concerns: Sequence[str]) -> bool:
    answer = input(
        f"The reply passed its checks. Its script is saved as {script}. "
        f"{derive.concerns_text(concerns)}{derive.RUN_WARNING} Run it now? [y/N] "
    )
    return answer.strip().lower() in ("y", "yes")


def _osf(link: str, dest: Path, only_list: bool, max_mb: float | None) -> None:
    node = osf.node_id(link)
    if node is None:
        raise SystemExit(f"not an OSF project link: {link}")
    try:
        files = osf.list_files(node)
    except OSError as e:
        raise SystemExit(f"could not list OSF project {node}: {e}") from e
    if only_list:
        for f in files:
            print(f"{osf.human_size(f.size):>10}  {f.path}")
        total = osf.human_size(sum(f.size for f in files))
        print(f"{plural(len(files), 'file')}, {total}")
        return
    max_bytes = None if max_mb is None else int(max_mb * 1e6)
    try:
        result = osf.fetch(node, dest, max_bytes, files=files)
    except (OSError, ValueError) as e:
        raise SystemExit(
            f"the download stopped ({e}); run the same command again to pick "
            "up where it stopped"
        ) from e
    print(f"{result.describe()} The list is in {dest / osf.LISTING}.")


def _extract(workspace: Path, replace: bool, server: str | None):
    if (workspace / PARAGRAPHS).is_file() and not replace:
        print(
            f"{PARAGRAPHS} is already there and may hold your corrections, so it "
            "was left as it is. Add --replace to write it again."
        )
        return "nothing to do", [], None
    s = settings.load(workspace)
    if missing := settings.missing_paper(workspace, s, "extract"):
        raise FileNotFoundError(missing)
    result = extract.extract(workspace, s.manuscript, server or s.grobid, s.supplement)
    print(extract.describe(result))
    if note := breaks.rough_note(workspace):
        print(note)
    return f"wrote ({result.route})", [], None


def _handoff(step: str, workspace: Path, max_chars: int, scripts: list[str] = ()):
    if step == "breaks":
        written = breaks.write_handoffs(workspace)
    elif step == "docs":
        written = docs.write_handoffs(workspace, settings.load(workspace), scripts)
    elif step == "segment":
        written = segment.write_handoffs(
            workspace, settings.load(workspace).scope, max_chars
        )
    elif step == "decompose":
        written = decompose.write_handoffs(workspace, max_chars)
    elif step == "trace":
        written = trace.write_handoffs(workspace, settings.load(workspace))
    elif step == "derive":
        written = derive.write_handoffs(workspace, settings.load(workspace))
    elif step == "compare":
        written = compare.write_handoffs(workspace, settings.load(workspace))
    elif step == "crosscheck":
        record = crosscheck.record_for(workspace, settings.load(workspace))
        if record is None:
            print(f"There is no record yet: run {compare.SCRIPT} first.")
            return "nothing to do", [], None
        written = crosscheck.write_handoffs(workspace, record)
    else:
        written = header.write_handoffs(workspace, settings.load(workspace))
    if not written:
        print(f"Nothing to hand off for {step}: every item has an accepted answer.")
        return "nothing to do", [], None
    print(
        f"Wrote {plural(len(written), 'file')} to give your assistant, one at a time:"
    )
    for path in written:
        print(f"  {path.relative_to(workspace)}")
    print(
        "\nFor each one: paste the whole file into the chat (or attach it), save the"
        "\nreply as a text file, and give it to the tool to check:"
        f"\n  rigoraudit import {step} <reply file> --by <who wrote it>"
    )
    return f"wrote {len(written)}", [], None


def _import(step: str, workspace: Path, reply: Path, by: str, handoff: str | None):
    module = STEPS[step]
    pending = module.pending_handoffs(workspace)
    text = reply.read_text(encoding="utf-8")
    if step == "trace":
        saved, problems = trace.import_answer(
            workspace, settings.load(workspace), text, by, handoff
        )
    elif step == "derive":
        saved, problems = derive.import_answer(
            workspace,
            settings.load(workspace),
            text,
            by,
            handoff,
            approve=_approve_run,
            announce=lambda p: print(f"Running {p} (it passed the script checks) ..."),
        )
        if saved is None and not problems:
            print("Not run, so not saved. Import the reply again to run it.")
            return "not run", [], handoff
    else:
        saved, problems = module.import_answer(workspace, text, by, handoff)
    if problems:
        print(
            f"The reply has {plural(len(problems), 'problem')} and was not saved. "
            "Paste the text\nbetween the lines back to the assistant, then import "
            "its new reply.\n"
        )
        print(paste_back(problems))
        guess = handoff or (pending[0].name if len(pending) == 1 else None)
        return "sent back", problems, guess
    if step == "trace" and saved.parent.name == trace.ASKED.name:
        asked = trace.Asked.model_validate_json(saved.read_text(encoding="utf-8"))
        why = (
            "could not open the repository, so it gets an index of the code"
            if asked.no_access
            else f"asked for code from {plural(len(asked.requests), 'place')}"
        )
        print(f"The assistant {why} ({asked.handoff}).")
        _handoff("trace", workspace, 0)
        return "asked for code", [], asked.handoff
    accepted = module.Accepted.model_validate_json(saved.read_text(encoding="utf-8"))
    if step == "breaks":
        print(
            f"Accepted the paragraph breaks: {plural(accepted.split, 'paragraph')} "
            f"split in two and {plural(accepted.joined, 'pair')} joined into one, "
            f"in {PARAGRAPHS}. The answer is saved in "
            f"{saved.relative_to(workspace)}.\nNext: rigoraudit handoff segment"
        )
        return "accepted", [], accepted.handoff
    if step == "header":
        print(
            f"Accepted the header and wrote it to {report.HEADER}; edit that file "
            f"to change it. The answer is saved in {saved.relative_to(workspace)}."
        )
        return "accepted", [], accepted.handoff
    if step == "docs":
        what = (
            f"{plural(len(accepted.files), 'file')} read, "
            f"{plural(len(accepted.answer.disagreements), 'disagreement')} noted"
        )
        if accepted.unchecked:
            what += f" ({plural(len(accepted.unchecked), 'PDF')} not checked)"
    elif step == "segment":
        what = (
            f"{plural(len(accepted.answer.claims), 'claim')} and "
            f"{plural(len(accepted.answer.left_out), 'left-out piece')}"
        )
    elif step == "derive":
        claims = accepted.answer.claims
        what = (
            f"{plural(sum(len(c.values) for c in claims), 'value')} recomputed, "
            f"{sum(len(c.cannot) for c in claims)} that cannot be, for "
            f"{plural(len(claims), 'claim')}"
        )
    elif step == "compare":
        what = (
            f"{plural(len(accepted.findings), 'finding')} for "
            f"{plural(len(accepted.claims), 'claim')}"
        )
    elif step == "crosscheck":
        a = accepted.answer
        what = (
            f"{plural(len(a.groups), 'group')} of values, "
            f"{plural(len(a.set_aside), 'candidate')} set aside"
        )
    elif step == "trace":
        # a procedure cites for the claim as a whole, a new result per facet
        parts = [p for c in accepted.answer.claims for p in (c, *c.facets)]
        what = (
            f"{plural(sum(len(p.methods) for p in parts), 'Methods passage')} and "
            f"{plural(sum(len(p.code) for p in parts), 'code passage')} for "
            f"{plural(len(accepted.answer.claims), 'claim')}"
        )
    else:
        what = (
            f"{plural(sum(len(c.facets) for c in accepted.answer.claims), 'facet')} "
            f"of {plural(len(accepted.answer.claims), 'claim')}"
        )
    print(
        f"Accepted {accepted.handoff}: {what}, saved to {saved.relative_to(workspace)}."
    )
    waiting = module.pending_handoffs(workspace)
    if waiting:
        print(f"Still waiting for an answer: {', '.join(h.name for h in waiting)}.")
    else:
        print(f"Next: run rigoraudit handoff {step} for anything left to do.")
    return "accepted", [], accepted.handoff
