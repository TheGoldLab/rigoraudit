# Copyright (c) 2026, Joshua I. Gold
# SPDX-License-Identifier: BSD-2-Clause
"""The guided audit: ``miragold audit`` (decision 0011).

The guide works out from the files in the workspace which steps are done,
says where the audit stands, and takes the user through the next ones in
order, using the same functions as the separate commands:

1. **Workspace.** Creates the folders and a manifest to fill in, if there
   is none.
2. **Materials.** Checks the manuscript is there, and downloads the code
   from the repository the manifest names if it is not, as a git clone at
   the manifest's commit so every check can read the code at that commit.
   Then lists every file in the materials, with what each data file holds,
   and what the code reads (:mod:`miragold.materials`).
3. **Extract.** Writes the paragraphs file from the publisher's XML, or
   from the PDF alone; paragraphs cut from a PDF are a best guess, so the
   guide offers to stop for the user to look them over, unless a coding
   assistant does the tasks.
4. **Breaks** (PDF only, optional). Offers to have the assistant decide
   the paragraph breaks the tool is unsure of.
5. **Docs, segment, decompose, trace, derive, compare, crosscheck,
   header.** For each handoff: the file to give
   the assistant, then the path of the saved reply, which is checked; a
   reply with problems gets the block to paste back. A coding assistant
   instead runs the guide itself and writes its replies to each step's
   inbox, ``work/<step>/inbox/``; every run checks what is there, and writes
   the problems with a reply beside it. The authors' code is
   not run until their documentation has been read (decision 0013), and
   a script the assistant writes to recompute values is run only once the
   user has read it and agreed (:mod:`miragold.derive`).
6. **Record, check, and report.** Builds the record from the accepted
   answers (:func:`miragold.compare.write_record`), unless the workspace
   has its own ``record/record.py``; checks it (:mod:`miragold.check`);
   and, if every check passes, writes the report.

It can be stopped at any prompt (press Enter) and picks up where it left
off. A script the script checks flag (or every script, with ``derive:
run: ask``) runs only when the user, at the terminal, agrees; a run with no
one at the terminal (a coding assistant's) leaves it waiting. Each run writes its own feedback report (decision 0012). ``ask`` and
``say`` stand in for ``input`` and ``print``, so tests can drive it.
"""

from __future__ import annotations

import dataclasses
import itertools
import json
import os
import shutil
import subprocess
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from miragold import (
    api,
    breaks,
    check,
    clipboard,
    compare,
    crosscheck,
    decompose,
    derive,
    docs,
    extract,
    feedback,
    handoffs,
    header,
    instructions,
    materials,
    matlab,
    osf,
    report,
    segment,
    settings,
    trace,
)
from miragold.paragraphs import PARAGRAPHS, read_paragraphs
from miragold.schema import RECORD, AuditRecord
from miragold.words import plural

FOLDERS = ("materials", "work", "derivations", "record", "review", "report", "notes")
CHOICES = PurePosixPath("work", "guide.json")
"""What the user chose once for this audit (who writes the answers, and
whether the tool asks a model itself)."""
TRIES = 3
"""Replies a model gets for one task in API mode before the user takes over."""
INBOX = "inbox"
"""Where a coding assistant writes its replies, in ``work/<step>/``."""
PROBLEMS = ".problems.txt"
"""The ending of the file beside a reply that lists its problems."""
TEMPLATE = """\
# This audit's manifest: what was received, from where, and the settings.
# Fill in the entries marked FILL IN, then run miragold audit again.
materials:
  manuscript:
    path: manuscript/paper.pdf      # FILL IN: the paper, in materials/
    # Put the article's XML file beside the PDF if there is one: its
    # paragraphs are exact (docs/guide.md, "Getting the article's XML").
    received_from: ""               # where it came from (journal page, preprint)
  code:
    path: code                      # the tool downloads the code here
    repository: ""                  # FILL IN, if public: https://github.com/<owner>/<repo>
                                    # or an OSF project: https://osf.io/<id>/
    commit: ""                      # FILL IN for GitHub: the version the paper used (40 characters)
    received_from: ""
  data:
    path: data                      # put the data in materials/data/
    received_from: ""
notes: []                           # anything a reader of the audit should know
gaps: []                            # what could not be run or checked from the materials:
                                    # - missing: what is not there, or what did not run
                                    #   instead: what the audit did about it
                                    #   claims: [the claims it affects]
settings:
  scope: [Results, Figure, Table]   # the sections audited, by the start of their names
  trace:
    code_access: auto               # auto, repository, or index
  run:
    scripts: []                     # the authors' scripts the run will start
  derive:
    run: auto                       # auto: run scripts that pass the checks; ask: ask first
  assistant:
    model: claude-opus-5-5          # the model the tool asks, if you use an API key
"""


class Stop(Exception):
    """The user stopped the guide; it picks up here next time."""


class Waiting(Stop):
    """The guide waits for the assistant or the user; the message says which."""


@dataclass
class Guide:
    workspace: Path
    ask: Callable[[str], str] = input
    say: Callable[[str], None] = print
    by: str = ""
    model: str = settings.MODEL
    talk: Callable[[str], api.Conversation] = api.Conversation
    """Starts a conversation with a model, for API mode."""
    interactive: bool = dataclasses.field(default_factory=lambda: sys.stdin.isatty())
    """Whether a person is at the terminal, who can agree to run scripts."""
    clip: clipboard.Clipboard | None = dataclasses.field(
        default_factory=lambda: clipboard.find()
    )
    """The clipboard, to carry tasks and replies to a chat; none to use files."""
    explained: bool = False
    """Whether the user has been told how the clipboard is used."""
    held: list[tuple[Path, list[str]]] = dataclasses.field(default_factory=list)
    """Scripts waiting for the user to agree, from replies in an inbox, each
    with what the script checks found."""
    approving: bool = False

    # --- Talking to the user ---------------------------------------------

    def yes(self, question: str) -> bool:
        answer = self.ask(f"{question} [y/N] ").strip().lower()
        return answer in ("y", "yes")

    def record(self, command: str, **event) -> None:
        feedback.record(self.workspace, command, **event)

    def rel(self, path: Path) -> str:
        return path.relative_to(self.workspace).as_posix()

    # --- Workspace and materials ------------------------------------------

    def make_workspace(self) -> bool:
        """Create the workspace if it has no manifest; ``True`` if it did."""
        manifest = self.workspace / settings.MANIFEST
        if manifest.is_file():
            return False
        for folder in FOLDERS:
            (self.workspace / folder).mkdir(parents=True, exist_ok=True)
        manifest.write_text(TEMPLATE, encoding="utf-8")
        self.say(
            f"Made a new audit workspace in {self.workspace}, with folders for "
            f"the materials and the work, and a manifest to fill in:\n"
            f"  {self.rel(manifest)}\n\n"
            "Put the paper in materials/ (and the data in materials/data/), fill "
            "in the entries marked FILL IN, then run miragold audit again."
        )
        return True

    def check_materials(self, s: settings.Settings) -> bool:
        if missing := settings.missing_paper(self.workspace, s, "audit"):
            self.say(missing)
            return False
        code = s.code
        if code is None:
            self.say(
                "The manifest names no code, so the audit will check the paper "
                "against its data only."
            )
            return True
        root = self.workspace / "materials" / code.path
        node = osf.node_id(code.repository) if code.repository else None
        if node and root.is_dir() and not (root / osf.LISTING).is_file():
            # files but no list: a download that stopped, or code put there
            return self.fetch_osf(node, root, resume=any(root.iterdir()))
        if root.is_dir() and any(root.iterdir()):
            if code.commit and not (root / ".git").exists():
                self.say(
                    f"Note: materials/{code.path} is not a git copy, so code is "
                    f"checked as it is there, not at commit {code.commit[:7]}."
                )
            return True
        if node:
            return self.fetch_osf(node, root)
        if not (code.repository and code.commit):
            self.say(
                f"There is no code in materials/{code.path}. Either put the "
                "authors' code there, or give its repository and commit in "
                f"{settings.MANIFEST} so the tool can download it."
            )
            return False
        self.say(
            f"The code is not in materials/{code.path} yet, so the tool is "
            f"downloading it from {code.repository} at commit {code.commit[:7]}, "
            "the version the paper used. This needs the internet and may take a "
            "few minutes for a large repository."
        )
        start = time.monotonic()
        try:
            download(code.repository, code.commit, root)
        except subprocess.CalledProcessError as e:
            self.record("audit", step="download", outcome="failed", error=e)
            self.say(
                "The download did not work. Check the repository and commit in "
                f"{settings.MANIFEST}, or put the code in materials/{code.path} "
                "yourself, then run miragold audit again."
            )
            return False
        self.record(
            "audit",
            step="download",
            outcome="downloaded",
            seconds=time.monotonic() - start,
        )
        self.say(f"Downloaded the code to materials/{code.path}.")
        return True

    def list_materials(self, s: settings.Settings) -> bool:
        """List every file in the materials, and what the code reads."""
        if materials.write_list(self.workspace, s):
            self.say(
                f"Listed every file in materials/, with what each data file "
                f"holds and what the code reads, in {materials.LIST.as_posix()}. "
                "Look there before recording anything as missing."
            )
        return True

    def fetch_osf(self, node: str, root: Path, resume: bool = False) -> bool:
        """Fetch the code from an OSF project (:mod:`miragold.osf`).

        ``resume``: there are files in ``root`` but no list of a finished
        download; answering no uses them as they are.
        """
        try:
            files = osf.list_files(node)
        except OSError as e:
            self.record("audit", step="download", outcome="failed", error=e)
            self.say(
                f"The tool could not list the files of OSF project {node}. Check "
                f"the link in {settings.MANIFEST} and the internet connection, or "
                f"put the code in {self.rel(root)} yourself, then run miragold "
                "audit again."
            )
            return False
        small = [f for f in files if f.size <= osf.MAX_BYTES]
        large = [f for f in files if f.size > osf.MAX_BYTES]
        text = (
            f"The code is to go in {self.rel(root)}. OSF project {node} has "
            f"{plural(len(files), 'file')} ({osf.human_size(sum(f.size for f in files))})."
        )
        if large:
            text += (
                f" The tool will download the {plural(len(small), 'file')} under "
                f"{osf.human_size(osf.MAX_BYTES)} each "
                f"({osf.human_size(sum(f.size for f in small))}) and leave out "
                f"the {plural(len(large), 'larger file')} (usually data), listing "
                f"them in {self.rel(root)}/{osf.LISTING}. To get those too, "
                f"run: miragold osf https://osf.io/{node}/ {self.rel(root)} --all"
            )
        self.say(text)
        if resume and not self.yes(
            f"There are files in {self.rel(root)} already, but no list of "
            "what was downloaded, so the download may not have finished. "
            "Finish it now? (Files already there are not downloaded again. "
            "Answer no to use the folder as it is.)"
        ):
            return True
        start = time.monotonic()
        try:
            result = osf.fetch(node, root, osf.MAX_BYTES, files)
        except (OSError, ValueError) as e:
            self.record("audit", step="download", outcome="failed", error=e)
            self.say(
                "The download did not work. Run miragold audit again to pick "
                "up where it stopped, or put the code in "
                f"{self.rel(root)} yourself."
            )
            return False
        self.record(
            "audit",
            step="download",
            outcome="downloaded (osf)",
            seconds=time.monotonic() - start,
        )
        self.say(result.describe())
        return True

    def check_extract(self, s: settings.Settings) -> bool:
        if (self.workspace / PARAGRAPHS).is_file():
            return True
        self.say("Extracting the paper's text into paragraphs ...")
        start = time.monotonic()
        try:
            result = extract.extract(
                self.workspace, s.manuscript, s.grobid, s.supplement
            )
        except extract.READ_ERRORS as e:
            self.record("audit", step="extract", outcome="failed", error=e)
            self.say(
                f"The tool could not read the paper's text from materials/"
                f"{s.manuscript} ({type(e).__name__}). Check that it is the "
                "published PDF, or make the paragraphs file yourself (docs/guide.md, "
                "step 2), then run miragold audit again."
            )
            return False
        self.record(
            "audit",
            step="extract",
            outcome=f"wrote ({result.route})",
            seconds=time.monotonic() - start,
        )
        self.say(extract.describe(result))
        if note := breaks.rough_note(self.workspace):
            self.say(note)
        if result.route != "xml":
            self.by = self.by or self.who(s)
            if self.choice("mode") == "files":
                return True  # the paragraphs can be fixed by hand at any time
            return self.yes(
                "Go on to the next step now? (Answer no to look over the "
                "paragraphs first, or to look for the XML; run miragold "
                "audit again when done.)"
            )
        return True

    # --- Assistant steps --------------------------------------------------

    def who(self, s: settings.Settings) -> str:
        """Who writes the answers, and how they come back; asked once per audit."""
        path = self.workspace / CHOICES
        choices = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
        if not choices.get("by"):
            self.say(
                "\nThe next steps need judgment, so an assistant does them (a chat "
                "in your browser, or a coding assistant on this computer), one "
                "task at a time, and the tool checks every answer."
            )
            kind = ""
            while kind not in ("1", "2", "3"):
                kind = self.ask(
                    "Which kind of assistant will you use?\n"
                    "  1  a chat in your web browser, such as Claude or ChatGPT\n"
                    "  2  a coding assistant on this computer, such as Claude "
                    "Code, Codex, or Cursor\n"
                    f"  3  none: the tool sends each task to {s.model} itself, "
                    "which costs money\n"
                    "Type 1, 2, or 3: "
                ).strip()
                if not kind:
                    raise Stop
                if kind == "3" and not self.api_agreed(s):
                    kind = ""
            if kind == "3":
                by, choices["mode"] = f"{s.model} (API)", "api"
            else:
                by = self.ask(
                    "Which one is it? Its name is enough, e.g. 'Claude'; add the "
                    "model too if you know it, e.g. 'Claude Opus 5.5'. "
                ).strip()
                if not by:
                    raise Stop
                choices["mode"] = "paste" if kind == "1" else "files"
            if kind == "2":
                self.say(
                    "\nThen it does the tasks without any copying; what to tell "
                    "it is below.\nA script it writes that the tool's checks flag "
                    "runs only when you agree, in a terminal: run miragold "
                    "audit yourself to read it and agree."
                )
            choices["by"] = by
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(choices, indent=1) + "\n", encoding="utf-8")
        return choices["by"]

    def ask_programs(self, s: settings.Settings) -> settings.Settings:
        """Ask once whether derivation scripts may start the programs the
        authors' code is written for; the answer goes in the manifest."""
        if s.code is None or s.derive_programs is not None:
            return s
        root = self.workspace / "materials" / s.code.path
        needed = {
            program: name
            for program, (name, ending) in settings.PROGRAMS.items()
            if any(root.rglob(f"*{ending}"))
        }
        if not needed:
            return s
        allowed = []
        for program, name in needed.items():
            found = matlab.find() if program == "matlab" else None
            self.say(
                f"\nThe authors' code includes {name} files. To recompute the "
                f"paper's values, your assistant's scripts may need to start {name}"
                + (
                    f" (found at {found})."
                    if found
                    else ", which the tool could not find on this computer; "
                    "install it, or put its bin folder on the command path."
                )
                + " The tool still reads every script before it runs and asks "
                "about anything else it finds, such as deleting files, using "
                f"the internet, or writing outside derivations/. {name} itself is "
                "not checked: the authors' code it runs can do anything a "
                f"program can. The answer is saved in {settings.MANIFEST} "
                "(settings: derive: programs), where you can change it."
            )
            if self.yes(f"Let the scripts start {name} without asking each time?"):
                allowed.append(program)
        settings.set_programs(self.workspace, allowed)
        return settings.load(self.workspace)

    def api_agreed(self, s: settings.Settings) -> bool:
        """Warn what API mode costs, and let the user back out."""
        self.say(
            f"\nAPI mode sends every task to {s.model} with your Anthropic API "
            "key (from ANTHROPIC_API_KEY), and the API charges for each one. "
            "This costs a substantial amount of money: roughly a dollar or two "
            "per claim, so a whole paper can cost hundreds of dollars, more if "
            "answers have to be sent back. The charges are billed to your API "
            "account, not to a Claude subscription; you can set a spending limit "
            "in the Anthropic Console. The paper's text and passages of the "
            "authors' code and documentation are sent to Anthropic."
        )
        return self.yes("Turn on API mode, and pay for it?")

    def choice(self, key: str) -> str | None:
        path = self.workspace / CHOICES
        return (
            json.loads(path.read_text(encoding="utf-8")).get(key)
            if path.is_file()
            else None
        )

    def choose(self, key: str, value: str) -> None:
        path = self.workspace / CHOICES
        choices = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
        choices[key] = value
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(choices, indent=1) + "\n", encoding="utf-8")

    def check_breaks(self) -> None:
        """Offer the optional breaks step; skipping it is remembered."""
        (planned,) = breaks.plan_handoffs(self.workspace)
        if not self.yes(
            f"The tool is unsure about {plural(len(planned.spots), 'paragraph break')} "
            "in the text cut from the PDF. Have your assistant check them? (Answer "
            "no to skip; you can still fix paragraphs.json by hand.)"
        ):
            self.choose("breaks", "skip")
            return
        self.work_through(
            "breaks",
            lambda: breaks.write_handoffs(self.workspace),
            lambda: breaks.pending_handoffs(self.workspace),
            lambda text, name: breaks.import_answer(
                self.workspace, text, self.by, name
            ),
        )

    def work_through(
        self,
        step: str,
        write: Callable[[], Sequence[Path]],
        pending: Callable[[], Sequence],
        import_answer: Callable[[str, str], tuple[Path | None, list]],
        then: Callable[[Path], None] | None = None,
    ) -> None:
        """Hand off every task of a step and import each reply, until done."""
        write()
        if self.choice("mode") == "files":
            (self.workspace / "work" / step / INBOX).mkdir(parents=True, exist_ok=True)
            self.read_inbox(step, pending, import_answer, then)
            write()  # accepted replies can open the next round of tasks
            if waiting := pending():
                raise Waiting(self.tell_assistant(step, waiting))
            self.say(f"\n{step}: done.")
            return
        by_api = self.choice("mode") == "api"
        if by_api and (waiting := pending()):
            by_api = self.yes(
                f"\n{step}: send {plural(len(waiting), 'task')} to {self.model}? "
                "(Answer no to give them to an assistant yourself.)"
            )
        while (waiting := pending()) or (write() and (waiting := pending())):
            h = waiting[0]
            path = handoffs.handoff_dir(self.workspace, step) / f"{h.name}.md"
            if by_api:
                saved = self.ask_model(step, h.name, path, import_answer)
                if saved is None:
                    by_api = False  # this task, and the rest of the step, by hand
                    continue
            else:
                saved = self.ask_user(step, h.name, path, waiting, import_answer)
                if saved is None:
                    continue
            if then is not None:
                then(saved)
        self.say(f"{step}: done.")

    def _import(
        self,
        step: str,
        name: str,
        text: str,
        import_answer: Callable[[str, str], tuple[Path | None, list]],
        quiet: bool = False,
    ) -> tuple[Path | None, list]:
        start = time.monotonic()
        saved, problems = import_answer(text, name)
        self.record(
            "import",
            step=step,
            outcome="sent back" if problems else "accepted",
            seconds=time.monotonic() - start,
            problems=problems,
            handoff=name,
        )
        if not problems and not quiet:
            self.say(f"Accepted {name}.")
        return saved, problems

    def read_inbox(self, step, pending, import_answer, then) -> None:
        """Check every reply in the step's inbox: save the good ones, write
        the problems with the rest beside them, and run the scripts waiting
        if the user agrees."""
        inbox = self.workspace / "work" / step / INBOX
        held = []
        for h in pending():
            reply = next(
                (
                    inbox / f"{h.name}{end}"
                    for end in (".txt", ".md", ".json")
                    if (inbox / f"{h.name}{end}").is_file()
                ),
                None,
            )
            if reply is None:
                continue
            before = len(self.held)
            saved, problems = self._import(
                step,
                h.name,
                reply.read_text(encoding="utf-8"),
                import_answer,
                quiet=True,
            )
            self.file_reply(reply, h.name, saved, problems, then)
            if len(self.held) > before:
                held.append((h.name, reply, self.held[-1]))
        if not held:
            return
        scripts = [script for _, _, script in held]
        listing = "".join(
            f"  {self.rel(p)} "
            f"({plural(p.read_text(encoding='utf-8').count(chr(10)), 'line')})\n"
            + "".join(f"    {c}\n" for c in concerns)
            for p, concerns in scripts
        )
        flagged = any(concerns for _, concerns in scripts)
        why = (
            "The script checks found these for a person to look at:\n" + listing
            if flagged
            else "The manifest says to ask before every script (derive: run: ask).\n"
        )
        if not self.interactive:
            self.held.clear()
            names = {name for name, _, _ in held}
            others = [h for h in pending() if h.name not in names]
            raise Waiting(
                f"\n{step}: {plural(len(scripts), 'script')} passed the checks and "
                f"{'waits' if len(scripts) == 1 else 'wait'} for the user to read "
                f"and agree to run. {why}Ask the user to run miragold audit "
                f"{self.workspace} in a terminal."
                + (self.tell_assistant(step, others) if others else "")
            )
        self.say(
            f"\n{step}: your assistant wrote {plural(len(scripts), 'script')} "
            "that passed the checks:\n"
            + listing
            + (
                "The script checks found what is listed under each.\n"
                if flagged
                else ""
            )
            + derive.RUN_WARNING
        )
        if not self.yes("Run them now?"):
            raise Stop
        self.approving = True
        try:
            for name, reply, (script, _) in held:
                self.say(f"Running {self.rel(script)} ...")
                saved, problems = self._import(
                    step,
                    name,
                    reply.read_text(encoding="utf-8"),
                    import_answer,
                    quiet=True,
                )
                self.file_reply(reply, name, saved, problems, then)
                if problems:
                    self.say(
                        f"It did not work; the problems are in "
                        f"{self.rel(reply.with_name(name + PROBLEMS))}, for your "
                        "assistant."
                    )
        finally:
            self.approving = False
            self.held.clear()

    def file_reply(self, reply, name, saved, problems, then) -> None:
        """Keep an accepted reply with the others; write a rejected one's
        problems beside it."""
        note = reply.with_name(name + PROBLEMS)
        if problems:
            note.write_text(handoffs.paste_back(problems), encoding="utf-8")
            return
        note.unlink(missing_ok=True)
        if saved is None:
            return  # its script waits for the user
        replies = self.workspace / "work" / reply.parent.parent.name / "replies"
        replies.mkdir(parents=True, exist_ok=True)
        reply.replace(replies / f"{name}.txt")
        self.say(f"Accepted {name}.")
        if then is not None:
            then(saved)

    def tell_assistant(self, step: str, waiting: Sequence) -> str:
        """What to do next: for the user, a line to give the assistant; for
        the assistant, the tasks and where its replies go."""
        n = plural(len(waiting), "task")
        work = PurePosixPath("work", step)
        notes = {
            h.name: work / INBOX / f"{h.name}{PROBLEMS}"
            for h in waiting
            if (self.workspace / work / INBOX / f"{h.name}{PROBLEMS}").is_file()
        }
        if self.interactive:
            return (
                f"\n{step}: {n} wait for your assistant"
                + (
                    f" ({len(notes)} with problems in their replies, "
                    f"listed in {work / INBOX}/<task>{PROBLEMS})"
                    if notes
                    else ""
                )
                + f". Tell it:\n  Run miragold audit {self.workspace} and do "
                "the tasks it gives you."
            )
        return (
            f"\n{step}: {n} waiting. For each, read the task file and write your "
            "whole reply, in the form the task asks for, to its inbox file "
            f"(paths in {self.workspace}):\n"
            + "\n".join(
                f"  {work / 'handoffs' / h.name}.md -> {work / INBOX / h.name}.txt"
                + (
                    f"\n    the reply there has problems: correct it as "
                    f"{notes[h.name]} says"
                    if h.name in notes
                    else ""
                )
                for h in waiting
            )
            + f"\nThen run miragold audit {self.workspace} again: it checks the "
            f"replies, and writes the problems with any to {work / INBOX}/"
            f"<task>{PROBLEMS}. Correct those replies and run it again."
        )

    def ask_user(self, step, name, path, waiting, import_answer) -> Path | None:
        """One task by hand: the file to give, then the saved reply."""
        if self.clip is not None and self.clip.copy(path.read_text(encoding="utf-8")):
            return self.ask_clipboard(step, name, path, waiting, import_answer)
        self.say(
            f"\n{step}: {plural(len(waiting), 'task')} left. Give your assistant "
            f"this file (paste its text, or attach it):\n  {self.rel(path)}\n"
            "Save the assistant's whole reply as a text file."
        )
        reply = self.ask("Path of the saved reply (press Enter to stop for now): ")
        if not reply.strip():
            raise Stop
        file = Path(reply.strip()).expanduser()
        if not file.is_absolute() and not file.is_file():
            file = self.workspace / file
        if not file.is_file():
            self.say(f"There is no file at {reply.strip()}.")
            return None
        saved, problems = self._import(
            step, name, file.read_text(encoding="utf-8"), import_answer
        )
        if problems:
            self.say(
                f"\nThe reply has {plural(len(problems), 'problem')} and was not "
                "saved. Paste the text between the lines back to the assistant, "
                "and save its new reply:\n"
            )
            self.say(handoffs.paste_back(problems))
        return saved

    def ask_clipboard(self, step, name, path, waiting, import_answer) -> Path | None:
        """One task through the clipboard, which already holds it: each reply
        the user copies is checked, and the problems with one copied back,
        until one is accepted."""
        question = "Reply copied? Press Enter (q to stop): "
        if not self.explained:
            self.say(
                "\nEach task goes on your clipboard. Paste it into a chat with "
                "your assistant (a new chat for each step works well), copy the "
                "assistant's whole reply (most chats have a copy button under "
                "it), and press Enter here."
            )
            question = (
                "Press Enter once you have copied the reply (or type q to stop): "
            )
            self.explained = True
        task = path.read_text(encoding="utf-8")
        self.say(
            f"\n{step}: {plural(len(waiting), 'task')} left; the next is on your "
            "clipboard."
        )
        replies = self.workspace / "work" / step / "replies"
        for n in itertools.count(1):
            answer = self.ask(question).strip()
            if answer.lower() == "q":
                raise Stop
            text = self.clip.paste() if self.clip is not None else None
            if text is None:
                self.say("The tool could not read the clipboard; try copying again.")
                continue
            if not text.strip() or text.strip() == task.strip():
                self.say(
                    "The clipboard still holds the task, not the reply. Copy the "
                    "assistant's reply, then press Enter."
                )
                continue
            replies.mkdir(parents=True, exist_ok=True)
            (replies / f"{name}-{n}.txt").write_text(text, encoding="utf-8")
            saved, problems = self._import(step, name, text, import_answer, quiet=True)
            if not problems:
                self.say("Accepted.")
                return saved
            note = handoffs.paste_back(problems)
            if self.clip.copy(note):
                self.say(
                    f"The reply has {plural(len(problems), 'problem')}. A note "
                    "listing them is on your clipboard: paste it into the same "
                    "chat, then copy the new reply."
                )
            else:
                self.say(
                    f"The reply has {plural(len(problems), 'problem')}. Paste the "
                    "text between the lines back to the assistant, then copy the "
                    f"new reply:\n{note}"
                )
        return None  # never reached

    def ask_model(self, step, name, path, import_answer) -> Path | None:
        """One task by the model: its reply, and each reply sent back to it,
        up to :data:`TRIES` in all; ``None`` if it was not accepted."""
        replies = self.workspace / "work" / step / "replies"
        replies.mkdir(parents=True, exist_ok=True)
        self.say(f"{step}: asking {self.model} for {name} ...")
        try:
            talk = self.talk(self.model)
            text = talk.ask(path.read_text(encoding="utf-8"))
            for n in range(1, TRIES + 1):
                kept = replies / f"{name}-{n}.txt"
                kept.write_text(text, encoding="utf-8")
                saved, problems = self._import(step, name, text, import_answer)
                if not problems:
                    return saved
                if n == TRIES:
                    break
                self.say(
                    f"The reply has {plural(len(problems), 'problem')}; sending "
                    "them back ..."
                )
                text = talk.ask(handoffs.paste_back(problems))
        except api.Unavailable as e:
            self.record("api", step=step, outcome="unavailable", handoff=name)
            self.say(f"{e} Doing the rest of this step by hand.")
            return None
        self.say(
            f"After {TRIES} tries the reply to {name} still has problems (the "
            f"replies are in {self.rel(replies)}). Doing the rest of this step by "
            "hand."
        )
        return None

    def approve_run(self, script: Path, concerns: Sequence[str]) -> bool:
        """Ask before running a script the assistant wrote; stop if not. A
        script from an inbox waits, to be agreed to with the others."""
        if self.choice("mode") == "files":
            if not self.approving:
                self.held.append((script, list(concerns)))
            return self.approving
        lines = script.read_text(encoding="utf-8").count("\n")
        if not self.yes(
            f"The reply passed its checks. Its script is saved as "
            f"{self.rel(script)} ({plural(lines, 'line')}). "
            f"{derive.concerns_text(concerns)}{derive.RUN_WARNING} Run it now?"
        ):
            raise Stop
        self.say("Running it ...")
        return True

    def run_steps(self, s: settings.Settings) -> None:
        ws = self.workspace
        self.model = s.model
        if self.choice("mode") == "api" and s.code_access == "auto":
            # a model asked through the API cannot open the repository
            s = dataclasses.replace(s, code_access="index")
        steps: list[tuple[str, Callable[[], bool], Callable[[], None]]] = []
        files = self.choice("mode") == "files"  # the assistant reads the folder
        entries = json.loads((ws / PARAGRAPHS).read_text(encoding="utf-8"))
        if any(e.get("approximate") for e in entries):
            steps.append(
                (
                    "breaks",
                    lambda: (
                        self.choice("breaks") == "skip" or not breaks.plan_handoffs(ws)
                    ),
                    self.check_breaks,
                )
            )
        if s.code is not None:
            steps.append(
                (
                    "docs",
                    lambda: not docs.plan_handoffs(ws, s),
                    lambda: self.work_through(
                        "docs",
                        lambda: docs.write_handoffs(ws, s),
                        lambda: docs.pending_handoffs(ws),
                        lambda text, name: docs.import_answer(ws, text, self.by, name),
                    ),
                )
            )
        steps += [
            (
                "segment",
                lambda: (
                    not segment.plan_handoffs(
                        read_paragraphs(ws / PARAGRAPHS),
                        segment.read_accepted(ws),
                        s.scope,
                    )
                ),
                lambda: self.work_through(
                    "segment",
                    lambda: segment.write_handoffs(ws, s.scope),
                    lambda: segment.pending_handoffs(ws),
                    lambda text, name: segment.import_answer(ws, text, self.by, name),
                ),
            ),
            (
                "decompose",
                lambda: not decompose.plan_handoffs(ws),
                lambda: self.work_through(
                    "decompose",
                    lambda: decompose.write_handoffs(ws),
                    lambda: decompose.pending_handoffs(ws),
                    lambda text, name: decompose.import_answer(ws, text, self.by, name),
                ),
            ),
        ]
        if s.code is not None:
            steps.append(
                (
                    "trace",
                    lambda: not trace.plan_handoffs(ws, s),
                    lambda: self.work_through(
                        "trace",
                        lambda: trace.write_handoffs(ws, s, shared_methods=files),
                        lambda: trace.pending_handoffs(ws),
                        lambda text, name: trace.import_answer(
                            ws, s, text, self.by, name
                        ),
                        then=lambda saved: (
                            trace.write_handoffs(ws, s, shared_methods=files)
                            if saved.parent.name == trace.ASKED.name
                            else None
                        ),
                    ),
                )
            )
        steps.append(
            (
                "derive",
                lambda: not derive.plan_handoffs(ws, s),
                lambda: self.work_through(
                    "derive",
                    lambda: derive.write_handoffs(ws, s),
                    lambda: derive.pending_handoffs(ws),
                    lambda text, name: derive.import_answer(
                        ws,
                        s,
                        text,
                        self.by,
                        name,
                        approve=self.approve_run,
                        announce=lambda p: self.say(
                            f"Running {self.rel(p)} (it passed the script checks) ..."
                        ),
                    ),
                ),
            )
        )
        if not (ws / compare.SCRIPT).is_file():
            steps.append(
                (
                    "compare",
                    lambda: not compare.plan_handoffs(ws, s),
                    lambda: self.work_through(
                        "compare",
                        lambda: compare.write_handoffs(ws, s),
                        lambda: compare.pending_handoffs(ws),
                        lambda text, name: compare.import_answer(
                            ws, text, self.by, name
                        ),
                    ),
                )
            )

        def record() -> AuditRecord | None:
            return crosscheck.record_for(ws, s)

        steps.append(
            (
                "crosscheck",
                # an audit with its own record.py has no record until it runs
                lambda: (r := record()) is None or not crosscheck.plan_handoffs(ws, r),
                lambda: self.work_through(
                    "crosscheck",
                    lambda: crosscheck.write_handoffs(ws, record()),
                    lambda: crosscheck.pending_handoffs(ws),
                    lambda text, name: crosscheck.import_answer(
                        ws, text, self.by, name
                    ),
                ),
            )
        )
        steps.append(
            (
                "header",
                lambda: not header.plan_handoffs(ws, s),
                lambda: self.work_through(
                    "header",
                    lambda: header.write_handoffs(ws, s),
                    lambda: header.pending_handoffs(ws),
                    lambda text, name: header.import_answer(ws, text, self.by, name),
                ),
            )
        )

        def finished_steps() -> list[str]:
            done = []
            for name, finished, _ in steps:  # done up to the first unfinished step
                if not finished():
                    break
                done.append(name)
            return done

        def say_standing() -> None:
            done = finished_steps()
            self.say(
                "\nWhere the audit stands:\n"
                + "\n".join(
                    f"  [{'x' if name in done else ' '}] {name}" for name, _, _ in steps
                )
            )

        self.say_old_answers([name for name, _, _ in steps])
        # The list is printed when the run stops, after any replies are
        # checked, so it agrees with the "done" lines above it.
        done = finished_steps()
        try:
            for name, _, work in steps:
                if name not in done:
                    self.by = self.by or self.who(s)
                    s = self.ask_programs(s)  # the steps' lambdas read s when run
                    work()
        except (Waiting, Stop, KeyboardInterrupt, EOFError):
            say_standing()
            raise
        say_standing()

    def say_old_answers(self, steps: Sequence[str]) -> None:
        """Warn about accepted answers written under older instructions,
        which the tool keeps using."""
        lines = []
        for step in steps:
            old = handoffs.old_answers(self.workspace, step)
            if old:
                named = ", ".join(sorted(set(old.values())))
                current = instructions.load(step).label
                lines.append(
                    f"  {step}: {plural(len(old), 'answer')} followed {named}; "
                    f"the current instructions are {current}."
                )
        if lines:
            self.say(
                "\nSome accepted answers followed older instructions, and the "
                "tool still uses them:\n"
                + "\n".join(lines)
                + "\nTo redo an answer under the current instructions, delete its "
                "file in work/<step>/answers/ and run miragold audit again."
            )

    # --- Check and report -------------------------------------------------

    def check_and_report(self, s: settings.Settings) -> str:
        """Build the record if the tool builds it, check it, and write the
        report if every check passes; the outcome."""
        if (self.workspace / compare.SCRIPT).is_file():
            if not (self.workspace / RECORD).is_file():
                self.say(
                    f"\nThis audit builds its record with its own {compare.SCRIPT}, "
                    f"and there is no {RECORD} yet. Run that script, then run "
                    "miragold audit again to check the record and write the report."
                )
                return "waiting for the record"
        else:
            path = compare.write_record(self.workspace, s)
            self.record("record", outcome="wrote")
            self.say(f"\nBuilt the record from the accepted answers: {self.rel(path)}.")
        self.say("\nChecking the record against the materials ...")
        start = time.monotonic()
        try:
            result = check.run(self.workspace)
        except (FileNotFoundError, ValueError) as e:
            self.record("check", outcome="failed", error=e)
            self.say(f"The check could not run: {e}")
            return "check failed"
        self.record(
            "check",
            outcome="passed" if result.passed else "problems",
            seconds=time.monotonic() - start,
        )
        self.say(check.describe(result))
        if not result.passed:
            return "check failed"
        page = report.write(self.workspace)
        self.record("report", outcome="wrote")
        self.say(
            f"\nWrote the report. To read it, open this file in your browser:\n"
            f"{page.resolve()}\nTo read it with review buttons on each claim and "
            "finding, run miragold review instead."
        )
        return "finished"

    # --- The whole run ----------------------------------------------------

    def run(self) -> str:
        """Take the user as far as they want to go; return how the run ended."""
        if self.make_workspace():
            return "made workspace"
        outcome = "stopped"
        try:
            s = settings.load(self.workspace)
            if not (
                self.check_materials(s)
                and self.list_materials(s)
                and self.check_extract(s)
            ):
                outcome = "waiting for materials"
            else:
                self.run_steps(s)
                outcome = self.check_and_report(s)
        except Waiting as w:
            self.say(str(w))
            outcome = "waiting"
        except (Stop, KeyboardInterrupt, EOFError):
            if self.interactive:
                self.say("\nStopped. Run miragold audit again to pick up here.")
            else:
                self.say(
                    "\nStopped at a question for the user. Ask the user to run "
                    f"miragold audit {self.workspace} in a terminal and answer it."
                )
        except Exception as e:
            self.record("audit", outcome="failed", error=e)
            self.say(_FEEDBACK_NOTE)
            raise
        self.record("audit", outcome=outcome)
        self.say(_FEEDBACK_NOTE)
        return outcome


_FEEDBACK_NOTE = (
    f"\nThe feedback report, {feedback.REPORT.as_posix()}, now includes this run. "
    "Nothing has been sent; run miragold feedback to read about it and how to "
    "send it if you wish."
)


def download(repository: str, commit: str, dest: Path) -> None:
    """Clone ``repository`` into ``dest`` and check out ``commit``."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.is_dir() and not any(dest.iterdir()):
        dest.rmdir()

    def git(*args: str, cwd: Path | None = None) -> None:
        subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)

    git("clone", "--quiet", "--no-checkout", repository, str(dest))
    try:
        git("checkout", "--quiet", "--detach", commit, cwd=dest)
    except subprocess.CalledProcessError:
        # the clone this call made, so a rerun starts clean; on Windows git's
        # files are read-only, so make each writable to remove it
        shutil.rmtree(dest, onexc=lambda rm, path, _: (os.chmod(path, 0o700), rm(path)))
        raise
