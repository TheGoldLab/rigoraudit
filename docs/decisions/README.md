# Decision records

Each file records one design decision: the problem, what was decided, and
why. They follow the convention of *architecture decision records*: numbered
in the order made, never renumbered, and not rewritten once accepted. A
later decision that changes an earlier one says so and links to it. Short
dated notes record how an accepted decision has played out.

[design.md](../design.md) describes the design as it stands; these records
explain how it got there.

| # | Decision |
|---|---|
| [0001](0001-workspaces.md) | The tool and each audit's workspace are separate; materials are kept as received |
| [0002](0002-claims.md) | What a claim is; claim types and facets |
| [0003](0003-readable-output.md) | The report is human-readable and anchored to the manuscript |
| [0004](0004-neutral-language.md) | Report language is thorough, professional, and neutral |
| [0005](0005-scope-and-deferrals.md) | Initial scope: citation tracing deferred; schema, gold set, then pipeline |
| [0006](0006-comparison-rules.md) | When sources differ: comparison bases and tolerances |
| [0007](0007-structured-values.md) | Values and comparisons are data; statuses are computed; reviewers override |
| [0008](0008-wording-thresholds.md) | How wording with a threshold, or with none, is read |
| [0009](0009-language-models.md) | Which stages may use a language model; its output passes the same checks as hand-built records |
| [0010](0010-provenance-and-review.md) | Who drafted each item, verification levels, and how reviewers confirm or correct a record's structure |
| [0011](0011-guided-audit.md) | One guided command runs the audit; steps that need judgment work with any assistant |
| [0012](0012-feedback-reports.md) | Every run writes a feedback report; only the user decides whether to send it |
| [0013](0013-authors-documentation.md) | Read the authors' documentation, and write down what it says, before running their code |
| [0014](0014-list-the-materials.md) | List every file in the materials, with what each data file holds, and what the code reads |
| [0015](0015-statistical-tests.md) | Statistical tests: each reported number is checked against the others, the Methods, and the code |
| [0016](0016-cross-claim-checks.md) | Values that disagree between claims are found by grouping, in a stage after compare |
| [0017](0017-procedures-traced-whole.md) | Procedure claims are traced and compared whole, not split into facets |

2026-11-04: The tool was renamed from rigoraudit to miragold. The name
was replaced in the records above, and nothing else in them was changed.
