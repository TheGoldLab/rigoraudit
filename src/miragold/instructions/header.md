---
step: header
version: 1
---

# Write the report's header

You are helping audit a scientific paper. The audit's report opens with a
short header that tells a reader which paper was audited, what the audit
covers, and where each material came from. Write its parts from the
audit's manifest and the paper's first page, given below. Use only what
they say: do not judge the paper or the audit, and do not add anything
you cannot find there.

- **heading**: the first author's family name and the year, as in
  "Lee et al. (2026)", or "Lee and Park (2026)" for two authors.
- **title**: the paper's title, copied word for word from the first page.
- **published**: where it was published, as the first page prints it
  (journal, volume, pages or article number, DOI). Leave it empty if the
  page does not say.
- **covers**: one or two sentences on what the audit covers: the audited
  sections, and that each claim has a card setting what the Results,
  Methods, code, and data say side by side.
- **materials**: one line for each material the task names, and for the
  data if the manifest lists any. Say what it is and where it came from,
  from the manifest: the file, the repository and the commit (its first
  seven characters are enough), or the project it was downloaded from.

Plain text only; no markup.

## Your answer

Reply with a single JSON block and nothing else, in this form:

```json
{
  "instructions": "header v1",
  "heading": "Lee et al. (2026)",
  "title": "Tone learning in mice",
  "published": "Journal of Examples 12:345. doi:10.0000/example.12345",
  "covers": "This audit covers the Results and the figure legends. Each claim has a card that sets what the Results, Methods, code, and data say side by side.",
  "materials": [
    {"name": "Manuscript", "text": "The published PDF, materials/manuscript/paper.pdf, from the journal's page."},
    {"name": "Code", "text": "github.com/example/tone-learning at commit 0123abc, the version the paper used."},
    {"name": "Data", "text": "materials/data/trials.json, from the authors' data deposit."}
  ]
}
```

If the tool finds problems with your answer, it will list them; correct
them and send the whole answer again.
