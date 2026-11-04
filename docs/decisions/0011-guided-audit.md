# 0011 — One guided command, and steps that work with any assistant

**Status:** accepted (2026-10-30)

## Problem

Running an audit today takes a coding assistant that can work on the
user's computer: open any file, search the authors' code, run their
programs for hours, and save results in the workspace. Many users will
have only an assistant they reach through a website, which sees only what
they paste or upload, cannot run programs on their computer, and forgets
everything when the chat ends. Others will have an API key, or a coding
assistant like the one used so far.

The audit is also many separate steps, each started by hand, with the
order and the next step known only to whoever has done one before.

## Decision

1. **One guided command takes the user through the whole audit.** A
   single command (name to be chosen; `miragold audit <workspace>` for
   now) creates the workspace if it does not exist, works out from the
   files present which steps are done, and does the next one:
   - steps the tool does itself (extracting the text, checking, building
     the report) it simply runs;
   - steps that need judgment it hands to the assistant the user chose
     (item 3), then checks the answer (item 5);
   - before anything slow, such as running the authors' code, it says what
     it will do and how long it may take, and asks first.

   It can be stopped at any point and picks up where it left off. It says
   in plain words what it is doing, what is left, and what the user needs
   to do next.

2. **Every step is also its own command, fully documented.** The guided
   command calls the same commands a user can run one at a time, with the
   same options. Nothing can be done only through the guide. Settings live
   in one file in the workspace, with defaults that suit most audits, so
   the guided command needs no configuration to start.

3. **Steps that need judgment can be done three ways, chosen once per
   audit:**
   - *A website assistant,* through handoff files that the user pastes into
     the chat (item 4), saving the reply for the tool to read;
   - *The tool calls a model itself,* with the user's own API key
     ([0009](0009-language-models.md), item 6);
   - *A coding assistant on the user's computer,* as the example audits
     were done.

   All three use the same written instructions and the same answer format,
   so their answers are checked the same way and can be compared.

4. **A handoff file holds everything the assistant needs for one task:**
   the instructions, the material to work on with a label on every
   paragraph or code line, and the exact format the answer must take. It
   is small enough to paste into a chat; a long section is split across
   several files.

5. **Every answer is checked before it enters the record,** whichever way
   it was produced: that it is in the required format, that every quote
   appears word for word in the manuscript, and that every cited code line
   exists at the stated place. Problems are described in plain words that
   can be pasted back to the assistant so it can correct them. This
   applies [0009](0009-language-models.md) item 2. The record notes which
   assistant drafted each item ([0010](0010-provenance-and-review.md)).

6. **Running code stays on the user's computer.** An assistant may write
   a script that recomputes a value; the tool runs it locally and reads the
   result back. Because a website assistant cannot search the authors'
   code, handoff files for tracing include an index of it: the files, the
   functions each defines, and where each variable is first set.

7. **The instructions for each step are written into the tool,** with a
   version number, rather than living in conversations with an assistant.
   They are the instructions all three ways in item 3 use, and the version
   is recorded with each answer.

## Why

The tool should be usable by a scientist who rarely uses a terminal,
with whatever assistant they have. A single
guided command means they need to learn one thing to start, while the
separate commands keep every step open to inspection, scripting, and
reruns. Handoff files are the one method that works with any assistant,
including those with no access to the user's computer. Because every
answer passes the same checks, the user does not have to trust the
assistant, only the checks, which are the tool's and are the same for
everyone.

## Not yet decided

- The command's name.
- A later option in which a website assistant connects to the tool
  directly, so nothing is copied by hand and it can search the code
  itself.
- How the code index is built for each programming language.
- How large a handoff file can be, which depends on the assistant.
- When to build it. `miragold new` and `miragold verify`, deferred
  until the steps are better tested (design.md, Deferred), become parts of
  this command; the deferral itself stands.

## Notes

- 2026-10-31: Both deferred commands exist now. `miragold new` is the
  first run of `miragold audit`, which makes the workspace and its
  manifest. The verify step is `miragold check`, a command of its own
  that runs the anchor and coverage checks from the workspace's fixed
  layout; the guide does not run it yet.
- 2026-10-31: The guide now runs `miragold check` once there is a record,
  and writes the report when every check passes.
- 2026-10-31: Item 6 is built as the derive step: an assistant writes a
  script for each claim's numbers, and the tool runs it only after the
  user, told the script can do anything they can, has agreed.
- 2026-10-31: The record is now built by the tool too (the compare step
  and `miragold record`): an assistant names the observations and
  comparisons for each facet, and the schema computes each status. An
  audit's own `record/record.py` still takes precedence.
- 2026-10-31: The second way in item 3 is built: the guide can send each
  task to a model with the user's API key, and send a reply's problems back
  to it, up to three times, before the user takes over. The user chooses
  it once per audit, and is told what is sent before choosing.
- 2026-11-01: Item 6 changed: asking before every script meant users ran
  them unread. The tool now reads each script first, without running it,
  and runs it without asking unless that check flags something (a module
  that can start programs or change files, writing outside
  `derivations/`, deleting a file, a path outside the workspace). A flagged
  script waits for the user, with what was found. The manifest's
  `settings: derive: run: ask` asks before every script, as before.
- 2026-11-01: With a coding assistant, every script that started MATLAB
  was flagged, so the run stopped for the user at each one. When the
  authors' code includes MATLAB files, the guide now asks once, at the
  start, whether scripts may start MATLAB, and saves the answer in the
  manifest (`settings: derive: programs`). If yes, a script that starts it
  through `miragold.matlab` runs without asking; anything else the check
  finds still waits for the user.
