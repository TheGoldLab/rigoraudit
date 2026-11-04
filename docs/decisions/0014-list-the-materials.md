# 0014 — List every file in the materials, and what the code reads

**Status:** accepted (2026-11-01)

## Problem

An audit recorded as missing a set of results the authors had in fact
shared. The files sat inside the code repository, next to the scripts that
read them, while the audit looked for them only in the data deposit. Claims
were then checked against a rebuilt version of those results, which
differed from the authors' own. A second audit of the same paper copied the
gap without looking again.

Nothing in the tool showed what was there. The code index counted files
other than code by folder, without naming them. The derive step's handoff
named every file but not what each held, so a data file whose name matched
another one elsewhere looked like a copy. A gap was text typed into the
manifest, and nothing tested it.

## Decision

1. **The tool lists every file in `materials/`,** wherever it is, with its
   kind (paper, code, documentation, data, other), its size, and, for a
   data file, what it holds: variable names and structure fields, a
   table's first row, an archive's arrays, a JSON file's keys. The guide
   writes the list to `work/materials/files.md` at every run, and the
   derive step's handoffs use it.

2. **The tool lists what the code reads.** Each read call whose file name
   is written in the code is matched to the materials and to the code's own
   save calls, and sorted into: in the materials; made by the code; and
   neither. Only the last is missing. Reads that build the whole name while
   the code runs are counted and pointed to, not followed. The report's
   list of gaps names the files that are neither.

3. **The check points out gaps to look at again.** When a gap's text names
   a data file, a name saved in one, a function defined inside another code
   file, or a package folder that is in the materials, `miragold check`
   says so. It does not fail, because gaps often name files that are there
   to say what is not.

4. **Before recording something as missing, look in the list,** by file
   name and by the names saved in the files. The derive instructions say
   so, and so does the user guide.

## Why

The miss came from looking where the files were expected, not at what was
there. A list made by the tool, of everything, with what each file holds,
puts what is there in front of whoever writes a gap, whether a person or
an assistant. Matching the code's reads makes "missing" the result of a
check, not of a guess, for most reads. The reads are found by line
patterns, like the code index: a map to look at, not proof. A name built
while the code runs, or a read through a function the patterns do not
know, still needs a person.

A gap entry that must say where it was looked for was considered and not
adopted. It would be filled in by the same search that missed the files,
and the list in item 1 does that search for everyone.

## Notes

- 2026-11-02: archives (`.zip`, `.tar`, `.tar.gz` and the like) are a kind
  of their own, listed with the files inside them, whose names count for
  the gap notes as names saved in a file. Before this they were listed as
  *other*, with nothing on what they held.
