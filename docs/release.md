# Release checklist

How the tool is published, and what has to be true before it is. The public
repository starts fresh: its first commit is a checked copy of this tree, and
this repository stays private. (Its history once contained audit content; on
2026-10-30 it was replaced by a single commit of the tree as it then stood.)

## Settled

- **License:** BSD-2-Clause. Anyone may use, modify, and redistribute the
  tool, including in closed or commercial work, provided they keep the
  copyright notice, the license, and the warranty disclaimer. It grants no
  patent rights. Penn Center for Innovation (PCI) recommends BSD or MIT
  first and discourages GPLv3-family licenses, including AGPL-3.0, for
  their patent grant (*Faculty Guide to Open-Source Software Licenses*,
  2026).
- **Copyright holder:** Joshua I. Gold. Under Penn's faculty copyright policy,
  faculty own software from their research unless a sponsored program
  agreement gives the sponsor rights to copyrightable works, the work is
  made for hire, or it makes substantial use of University resources beyond
  the norm; none applies. Penn keeps a royalty-free license for academic
  use.
- **No audit content in the repository.** Audits, including the examples the
  tool is developed against, live in workspaces outside it (0001). Examples
  in the docs and tests are synthetic.
- **Model access is each user's own** (0009): an API key from the
  environment, never shipped, and never a personal subscription.
- **Gold records are for evaluation, not training** (0009).

## Before the first public commit

1. **Ownership and obligations**
   - [x] Check that no grant that funded the work requires a particular
     license.
2. **Audit content**
   - [ ] Hooks installed (`scripts/install-hooks`) and
     `uv run python scripts/check_no_audit_content.py` passes, with every
     example workspace visible to it.
   - [ ] Each workspace's `release_terms.txt` (or the shared one at the
     workspaces root) lists its authors, subjects, titles, distinctive file
     names, and distinctive values.
   - [ ] Read the docs, docstrings, and tests once by eye. The check finds
     listed terms and copied runs of 8 words or more; it cannot find a
     paraphrase or a value no list names.
   - [ ] `git ls-files` lists only the tool: `src/`, `tests/`, `docs/`,
     `scripts/`, `examples/` (the made-up example audit), `.github/` (tests
     on Linux, macOS, and Windows at each push), and top-level project
     files.
3. **Licensing files**
   - [x] `LICENSE`: the BSD-2-Clause text, with the line
     `Copyright (c) 2026, Joshua I. Gold`.
   - [x] A copyright line in `README.md` and a short header in each source
     file: `Copyright (c) 2026, Joshua I. Gold` and `SPDX-License-Identifier:
     BSD-2-Clause`.
   - [x] Bundled code keeps its own license: KaTeX (MIT) in
     `src/miragold/katex/`, with its `LICENSE`, named in `README.md`.
   - [x] `pyproject.toml`: `license = "BSD-2-Clause AND MIT"` (MIT for
     KaTeX) and `license-files` listing both licenses; author name and a contact address meant
     to be public.
   - [x] `CITATION.cff` with the author, title, version, and (after the
     first release) the DOI.
4. **Docs**
   - [ ] `README.md` states what is built and what is not, how to install
     and run it, that the steps needing judgment work with any assistant
     the user has (API mode only with their own key), and that use of a
     provider's API is governed by its terms and usage policy.
   - [ ] Every link in the docs resolves inside the public repository.
5. **Create the public repository**
   - [ ] Copy the tracked files (`git archive HEAD`) into a new directory,
     `git init`, commit, run the check and the tests there, then push to the
     new remote. Do not push this repository's history.
   - [ ] Install the hooks in the new clone.
   - [ ] Development continues in the public repository; this one is
     archived.
6. **First release**
   - [ ] Tag `v0.1.0`, and archive it on Zenodo for a DOI. Add the DOI to
     `CITATION.cff` and the README.

## How audit content gets in

The tool writes only into workspaces, so audit content arrives only by
someone writing it here. The moments to watch:

- **A fix or rule prompted by an audit.** The real case is the obvious test
  fixture or decision-record example.
- **Model prompts and evaluation.** Few-shot examples drawn from gold
  records, or gold records copied in as test data.
- **Moving code from a workspace into the tool,** such as the report
  renderer, which may carry strings or layout specific to one paper.
- **Commit messages** describing what an audit found, and **status notes**
  ("audit X has N findings") in the README or design docs.

The rule in each case: the real case goes in the audit's workspace; the
repository gets a synthetic case with the same structure but invented text
and values; code that needs real records reads them from the workspace at
run time.

## For every later commit

The hooks check each commit, its message, and the tree at each push. A
contributor without the workspaces gets only the file-type checks, so
changes from others are read for audit content before they are merged.
