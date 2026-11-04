# Example audit (made up)

A complete, small audit workspace, to learn from and to copy when starting a
real one. The paper, code, and data are invented: a two-page "paper" on mice
learning a tone discrimination, a ten-line analysis script, and 3,540
trials. They are built so the audit finds two things that agree and two
that do not:

| Finding | Status | What it shows |
|---|---|---|
| `R1.2.a/population` | Consistent | 12 mice and 10 sessions, in the Results and in the data |
| `R1.2.a/quantity` | Differs | The Results state 3,600 trials; the data hold 3,540 |
| `R1.2.b/quantity` | Consistent | Accuracies recomputed from the data round to the stated 60% and 87% |
| `R1.2.b/analysis` | Differs | The Methods exclude responses slower than 2 s, the code slower than 2.5 s; the stated accuracies are the same with either |

<!-- miragold status: generated, do not edit -->
2 claims, 4 findings. Drafted by Claude Opus 5.5 (Claude Code session), 2026-10-30. Mechanical checks pass: 10 anchors verified. Reviewed: 0 of 2 claims, 0 of 4 findings. Independent annotation: none. Authors: not contacted. Next: review 2 claims and 4 findings, claims first.
<!-- /miragold status -->

## What is here

The layout is the one every workspace has ([user
guide](../../docs/guide.md#the-workspace)); the step numbers are the guide's.
Each script says at the top what it does.

| Path | Step | Contents |
|---|---|---|
| `audit.yaml` | 1 | Manifest: each material, its checksum, the gaps, and the audited sections (the Results) |
| `materials/` | 1 | The paper (`manuscript.txt`), code, and data, as received; never edited |
| `work/materials/files.md` | 1 | Every file in `materials/`, with what each data file holds, and what the code reads; written by `miragold materials` |
| `work/extract/` | 2 | The paper's pages, outline, and paragraphs. `extract.py` writes them; it stands in for `miragold extract`, which reads a PDF, because the paper here is a text file |
| `derivations/values_trials.py` | 4 | Recomputes the values the Results state, from the data; writes `output/values/trials.json` |
| `record/record.py` | 5 | Builds the claims and findings with `miragold.schema`; writes `record.json` |
| `record/coverage_exclusions.json` | 6 | The text the coverage check leaves out, with the reason |
| `work/checks.json` | 6 | The results of `miragold check` |
| `work/crosscheck/` | 6 | The handoff listing every printed value, the assistant's answer saying which are about one thing (none here: no value is printed twice), and `findings.json`, the values compared, written by `miragold check`. The answer is kept, not rebuilt: if the record changes, run `miragold handoff crosscheck` and import a new answer |
| `report/` | 7 | `audit.html`, written by `miragold report`, and the audit's own `header.html` |
| `rebuild.sh` | 2–7 | Runs all of the above in order |

## Try it

From the repository's folder:

```
examples/example-audit/rebuild.sh
uv run miragold review examples/example-audit
```

and open http://127.0.0.1:8765/. Each claim and finding has review buttons
(try *Split* after selecting two parts of a claim's sentence, or select text
and use *Add claim from selection*). Each action is saved to the review log,
`review/log.json`, and the report shows the reviewed record.

To see the checks catch a problem, change something and rebuild:

- Change the cutoff in `materials/code/analysis.py`: the check reports that
  the code quote no longer matches the file.
- Add a sentence such as "Response times were faster in session 10." to
  the Results paragraph: the check lists "faster" and "10" as not covered,
  until a claim or an exclusion covers them.
- Change "87%" to "85%" in the Results: `record.py` stops, because its
  quote is no longer in the paragraph. Update the quote and the stated
  value in `record.py` to match, rebuild, and the accuracy finding is
  computed as *Differs*.

## Starting a real audit from this

Run `miragold audit <folder>` for a new workspace, and copy from here what
helps:

- `record/record.py`: the helpers at the top (`quote`, `got`) and the
  pattern of each kind of claim and finding.
- `derivations/values_trials.py`: one script per group of values, saving
  them with `miragold.values.write_values`.
- `report/header.html`: the form of the header; describe the real paper,
  the audit's scope, and the materials.

The data were made by `examples/make_example_data.py` (seed 7), which is
kept outside the workspace because a real audit receives its data.
