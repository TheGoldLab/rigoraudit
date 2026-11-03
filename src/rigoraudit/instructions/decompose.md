---
step: decompose
version: 3
---

# Split each claim into its parts

You are helping audit a scientific paper: checking that what it says
matches what its authors' code and data actually did. The paper's text has
already been split into claims. In this task you take each claim that
reports a new result and say what it states about each of its **facets**,
the parts that are checked separately. Do not judge whether the claim is
true.

## The facets

| `facet` | What the claim states about |
|---|---|
| `quantity` | the result itself: the numbers, or the direction ("increased", "no difference") |
| `population` | who or what was measured: subjects, cells, trials, sessions, and how many |
| `analysis` | how the result was computed or tested: the measure, statistic, test, or fit |
| `condition` | when, or under which conditions: task condition, group, block, time window |
| `display` | where it is shown: the figure or table it cites |

List only the facets the paragraph actually states for the claim. Most
claims have a `quantity`; many have only two or three facets. Give each
facet once per claim; if a claim states two conditions, put them in one
`condition`.

## For each facet

- `quote`: the words that state it, copied exactly from the claim's
  paragraph: same spelling, capitals, punctuation, dashes, and spaces. The
  words may lie outside the claim's own quote, elsewhere in the same
  paragraph (a sample size stated in the sentence before, or a figure
  reference just after). The quote must appear only once in the paragraph;
  if it appears twice, make it longer.
- `states`: one short, neutral sentence saying what the paragraph states
  about this facet, for example "Licking began 120 ms after tone onset."
  Do not add anything the paragraph does not say.
- `values` (only for numbers): each number the facet states, with a `name`
  for what it is ("latency", "mice", "p", "mean"), and `printed`, the
  number exactly as printed, with its unit or sign if it has one ("120 ms",
  "87%", "3,600", "< 0.01", "∼100 ms", "twelve", "13/16", "<10−5" for a
  power of ten). For a range, give each end as its own value, named for which end
  it is: "5–10%" is "5" (low) and "10%" (high); the tool gives "5" the
  unit printed after "10", as it does "168.25" in "168.25 ± 4.1 ms". Add `subject` when the
  value applies to one group or condition only ("block A"). Do not work out, round, or
  convert any number: the tool reads the value from what you copy.

Every number in a claim's quote must be inside the quote of one of its
facets (figure numbers such as "Figure 3A" do not count as numbers).

## Statistical tests

If the claim reports a statistical test, such as "t(22) = 2.10, p = 0.047",
also copy the test, part by part, into the claim's `tests` (one entry per
test). Copy only; work nothing out. Leave out any part the paragraph does
not print or state.

- `quote`: the words that report the test, copied exactly; they must
  appear only once in the paragraph.
- `named`: the test as the paragraph names it ("paired t test",
  "Wilcoxon signed-rank test"), copied exactly.
- `statistic`: one of `t`, `F`, `chi2` (χ²), `r`, `z`, `U`, `W`, or
  `other`.
- `value`: the statistic as printed ("2.10", "−3.4").
- `df`: the degrees of freedom as printed, one for t, χ², and r ("22"), two
  for F (`["2", "40"]`), none for z.
- `p`: p as printed, with its relation if the paper prints one ("= 0.047",
  "< 0.001"); if it prints none, the bare number ("p-value 0.03" gives
  "0.03").
- `n`: the sample size as printed ("24"). If it is stated outside the
  test's quote, also give `n_quote`, the words that state it, copied
  exactly.
- `tails`: `1` or `2`, only if the paragraph says one- or two-tailed.
- `design`: `independent`, `paired`, or `one-sample`, only if the paragraph
  says so ("paired t test", "compared with zero").
- `effect`: the effect size as printed, with its `name`: `d` (Cohen's d),
  `r`, `partial_eta_squared` (ηp², partial η²), or `other`; for example
  `{"name": "d", "printed": "0.90"}`.

Every number in a test's quote must also lie in a facet's quote, as above.

## Your answer

Reply with a single JSON block and nothing else, in this form:

```json
{
  "instructions": "decompose v3",
  "claims": [
    {"id": "R1.2.a", "facets": [
      {"facet": "quantity", "quote": "exact text", "states": "one sentence",
       "values": [{"name": "mean", "printed": "4.2 s"}]},
      {"facet": "display", "quote": "Figure 2B", "states": "Shown in Figure 2B."}
    ], "tests": [
      {"quote": "t(22) = 2.10, p = 0.047", "statistic": "t", "value": "2.10",
       "df": ["22"], "p": "= 0.047"}
    ]}
  ]
}
```

Answer every claim you are given, once. `values`, `subject`, and `tests` are
optional; leave them out when they do not apply. If the tool finds
problems with your answer, it will list them; correct them and send the
whole answer again.

## Example

Paragraph `R2.1`:

> Mice licked more often after the reward tone than after the neutral tone
> (Figure 3A). Licking began 120 ms after tone onset and peaked at 400 ms.

Claims to split: `R2.1.a` "Mice licked more often after the reward tone
than after the neutral tone", `R2.1.b` "Licking began 120 ms after tone
onset".

Answer:

```json
{
  "instructions": "decompose v3",
  "claims": [
    {"id": "R2.1.a", "facets": [
      {"facet": "quantity", "quote": "licked more often",
       "states": "Mice licked more often after one tone than after the other."},
      {"facet": "population", "quote": "Mice", "states": "The animals were mice."},
      {"facet": "condition", "quote": "after the reward tone than after the neutral tone",
       "states": "Licking after the reward tone is compared with licking after the neutral tone."},
      {"facet": "display", "quote": "(Figure 3A)", "states": "Shown in Figure 3A."}
    ]},
    {"id": "R2.1.b", "facets": [
      {"facet": "quantity", "quote": "began 120 ms",
       "states": "Licking began 120 ms after tone onset.",
       "values": [{"name": "latency", "printed": "120 ms"}]},
      {"facet": "condition", "quote": "after tone onset",
       "states": "The time is measured from tone onset."}
    ]}
  ]
}
```
