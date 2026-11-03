# 0013 — Read the authors' documentation before running their code

**Status:** accepted (2026-10-30)

## Problem

The authors' code often comes with documentation that says how to run it:
which script to start with and in what order, which software and versions
it needs, where the data must go, which settings to use, how long it takes,
and what it should produce. Data repositories have their own: a README, a
codebook, column descriptions.

Nothing in the tool makes sure these are read. In the audits so far they
were, because of how those audits were done, but a run that skips them can
report as a failure something the documentation explains, use a version
the authors warn against, or miss a step they describe. Where the
documentation and the code disagree, that is worth knowing too.

## Decision

1. **Before any of the authors' code is run, the tool lists their
   documentation:** every file in `materials/` that documents the code or
   data: READMEs and other text, Markdown, and PDF documents; files that
   name dependencies (`requirements.txt`, `environment.yml`,
   `pyproject.toml`, `setup.py`, `DESCRIPTION`, `renv.lock`,
   `Project.toml`, `Makefile`, `Dockerfile`, MATLAB `Contents.m` and project
   files); and the opening comment of every script the run will start.

2. **Each file is read, and what it says is written down** in the
   workspace, under the same headings for every file:
   - what to run, and in what order;
   - software and versions (language, toolboxes, packages);
   - data: what is needed and where it must go;
   - settings, random seeds, and hardware;
   - what the run should produce, and how long it takes;
   - known problems.

   Each entry quotes the file word for word, and the quote is checked, as
   for every other step (0011 item 5). "Says nothing about this" is a valid
   entry. This is a step like the others, with written, versioned
   instructions, so any assistant can do it (0011 item 3).

3. **The run follows the documentation.** Where it cannot, such as a
   version that is no longer available or a step that does not work as
   described, the departure and its reason go in `audit.yaml`, as missing
   helpers and stand-ins already do.

4. **The guided command does not start a run until every listed file has
   been read.** A documentation file that appears later, for example after
   downloading a newer copy, has to be read before the next run.

5. **Where the documentation disagrees with the code or the paper,** for
   example a README that says a script makes one figure when it makes
   another, or names a version the code cannot run on, the disagreement is
   noted for the trace and compare steps. Whether it becomes a finding
   follows the usual rules (0006).

## Why

The authors' documentation is the closest thing to their own instructions
for reproducing the work. Reading it first is what a careful person would
do, and makes a failure to reproduce mean something: the code was run as
its authors said to run it, or the record says where and why it was not.
Writing down what each file says, under fixed headings with checked quotes,
makes the reading visible and checkable rather than assumed.

## Not yet decided

- The file format for what each document says, and where in the workspace
  it lives (`derivations/` or `work/`).
- How documentation in PDFs and web pages (a lab wiki, a data repository's
  page) is brought into `materials/`.
- Whether to also read the authors' code comments beyond the opening one of
  each script started.
