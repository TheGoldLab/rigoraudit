# rigoraudit — instructions for working in this repository

- **No audit content, ever.** This repository holds the tool only. Never
  write into it anything taken from an audit: quotes, values, claim IDs from
  a real record, author or subject names, titles, file or script names,
  journal-specific details, or counts of claims and findings. Examples in
  docs, docstrings, tests, and commit messages are synthetic. Audit-specific
  notes go in that audit's workspace (decision 0001).
- The hooks from `scripts/install-hooks` enforce this. Never bypass them
  (`--no-verify`). If the check flags something, rewrite it as a synthetic
  example; if it is a false positive, say so to the user rather than
  working around it.
- Decision records in `docs/decisions/` are not rewritten once accepted;
  add a dated note instead (see `docs/decisions/README.md`).
- Follow the principles in `docs/development.md` (Principles) on every
  change. In short:
  - Docs match the code: a change in behavior updates the README,
    `docs/guide.md`, `docs/design.md`, and docstrings in the same commit.
    Each fact has one home; link rather than repeat.
  - Plain words for scientists who are not programmers; as few words as do
    the job. Messages say what is wrong and what to do next.
  - No legacy code or backward compatibility before the first release:
    change the workspaces and the example audit along with the format, and
    remove the old path and any code nothing uses.
  - Fixed workspace paths; an audit's settings live in its manifest, not in
    command options.
  - Workspaces (the example and those in `../audit_examples/`) follow the
    layout in `docs/guide.md` (The workspace), each with a README saying
    what is there, why, and how to rebuild it, and nothing else.
