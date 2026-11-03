---
step: segment
version: 3
---

# Split the text into claims

You are helping audit a scientific paper: checking that what it says
matches what its authors' code and data actually did. This task is the
first part. You will split the paragraphs below into **claims** and say
what kind each claim is. Later tasks check each claim; this one only finds
them. Do not judge whether a claim is true.

## What a claim is

A claim is the smallest piece of text that could be true or false on its
own and that rests on a single source of evidence: the authors' own data,
a cited paper, or an argument from other claims.

- **Separate statements are separate claims,** even in one sentence and
  even when they share a subject. "Firing rates rose after stimulus onset
  and fell before the response" is two claims.
- **Several values of one statement stay one claim.** "Rates rose in both
  groups, by 12 and 15 sp/s" is one claim.
- **A different source of evidence makes a different claim.** "Rates rose
  after onset (Figure 2), as reported before (Lee et al., 2019)" is two
  claims: one about the authors' data, one about a cited paper.
- **A description of what was done counts,** when it can be checked
  against the code: "Trials shorter than 200 ms were removed" is a claim.
- **An interpretation counts,** when it says something could be wrong:
  "suggesting that the area integrates evidence" is a claim.

## A result or an interpretation?

If a number in the data could check the sentence (a difference, a
correlation, a direction, a count), it is a `new_result`, however broadly
it is worded: "responses depended on the cue" is a result. If it says what
results *mean* (a mechanism, a cause, what the brain or the animal does
with them), it is an `interpretation`: "the area integrates evidence" is
one. A sentence with both is two claims.

A figure's title follows the same rule. A title that sums up a result
("Responses depend on the cue") is a `new_result` that restates the
Results claim it sums up; a title that names a mechanism ("Two mechanisms
shape the response") is an `interpretation`.

## Kinds of claim

Give each claim one `type`:

| `type` | The claim | Also give |
|---|---|---|
| `new_result` | reports a result from the authors' own data or analyses | |
| `referenced_result` | reports a result from other work | `citations` |
| `comparison` | says the paper's result agrees or disagrees with other work | `citations`, and `depends_on` |
| `interpretation` | draws a conclusion from other claims | `depends_on` |
| `procedure` | describes what was done, in the Results | |
| `no_stated_support` | asserts something with no data, citation, or argument given | nothing |

- `citations` lists the references as printed in the paragraph, copied
  exactly: `["Lee et al., 2019"]` or `["[12]"]`.
- `depends_on` lists the IDs of the claims it rests on. Name only claims in
  your answer or in the list given with the paragraphs; if it rests on
  claims you were not given, leave `depends_on` out.

## Leaving text out

Every number, comparison word ("higher", "increased", "no difference"),
and named statistical test ("t-test", "linear fit") must be inside a
claim, or inside a piece of text you leave out on purpose, with the
reason. Leave text out only when it holds nothing that could be checked:

- a reminder of the task or design that repeats the Methods and reports
  no result ("Subjects chose between two targets (left and right)");
- a sentence that only repeats a claim made nearby in the same section.
  Give that claim's ID as `restates`.

Figure and table references ("Figure 2B") and citations ("Lee et al.,
2019") are not checkable items, so you never need to leave them out. Keep a
citation inside the claim that cites it; keep a figure reference out of a
claim's quote unless it falls in the middle of it.

## Text outside the Results

A sentence in a figure legend, the Abstract, or the Discussion that
repeats a Results claim is still a claim of its own, so a mismatch between
the two can be found. Give the Results claim's ID as `restates`. The
Results claims you can refer to are listed with the paragraphs, when there
are any.

## Quotes

Each claim and each left-out piece is identified by a **quote**: text
copied exactly from its paragraph.

- Copy it character for character: same spelling, capitals, punctuation,
  dashes, and spaces. Do not fix typos or expand abbreviations.
- Take the shortest span that contains the whole claim, including its
  numbers and comparison words. Leave out lead-ins ("Together,", "We found
  that", "and", "but", "whereas") and figure references ("(Figure 2B)")
  around it; later tasks can still quote those. Quote the whole sentence
  only when a shorter span would leave unclear what the claim says.
- The quote must appear only once in its paragraph. If it appears twice,
  make it longer.
- Claims in one paragraph do not overlap.
- If a symbol or formula in the paragraph looks garbled, keep the quote
  to the plain words around it.
- A mark such as `[Equation 3]` stands for an equation set on its own
  lines. A quote may include the mark, copied as it is; a claim that an
  equation makes can be quoted as the words that introduce it and its mark.

## Claim IDs

Each paragraph has a label, such as `R1.2`. Give its claims the label plus
a letter, in the order they appear: `R1.2.a`, `R1.2.b`, and so on (after
`z`, continue with `aa`, `ab`).

## Your answer

Reply with a single JSON block and nothing else, in this form:

```json
{
  "instructions": "segment v3",
  "claims": [
    {"id": "R1.2.a", "paragraph": "R1.2", "quote": "exact text", "type": "new_result"},
    {"id": "R1.2.b", "paragraph": "R1.2", "quote": "exact text", "type": "comparison",
     "citations": ["Lee et al., 2019"], "depends_on": ["R1.2.a"]},
    {"id": "F1.1.a", "paragraph": "F1.1", "quote": "exact text", "type": "new_result",
     "restates": "R1.2.a"}
  ],
  "left_out": [
    {"paragraph": "R1.1", "quote": "exact text", "reason": "why it holds nothing to check"},
    {"paragraph": "R1.3", "quote": "exact text", "reason": "repeats R1.2.a", "restates": "R1.2.a"}
  ]
}
```

`restates`, `citations`, and `depends_on` are optional; leave them out when
they do not apply. If the tool
finds problems with your answer, it will list them; correct them and send
the whole answer again.

## Example

Paragraph `R2.1`:

> Mice licked more often after the reward tone than after the neutral tone
> (Figure 3A). Licking began 120 ms after tone onset and peaked at 400 ms.
> Each session began with the neutral tone. This preference is consistent
> with earlier reports (Lee et al., 2019), suggesting that the mice learned
> what the reward tone meant.

Paragraph `F3.1` (legend of Figure 3):

> (A) Lick rate after each tone; mice licked more after the reward tone.

Answer:

```json
{
  "instructions": "segment v3",
  "claims": [
    {"id": "R2.1.a", "paragraph": "R2.1", "type": "new_result",
     "quote": "Mice licked more often after the reward tone than after the neutral tone"},
    {"id": "R2.1.b", "paragraph": "R2.1", "type": "new_result",
     "quote": "Licking began 120 ms after tone onset"},
    {"id": "R2.1.c", "paragraph": "R2.1", "type": "new_result",
     "quote": "peaked at 400 ms"},
    {"id": "R2.1.d", "paragraph": "R2.1", "type": "procedure",
     "quote": "Each session began with the neutral tone."},
    {"id": "R2.1.e", "paragraph": "R2.1", "type": "comparison",
     "quote": "This preference is consistent with earlier reports (Lee et al., 2019)",
     "citations": ["Lee et al., 2019"], "depends_on": ["R2.1.a"]},
    {"id": "R2.1.f", "paragraph": "R2.1", "type": "interpretation",
     "quote": "suggesting that the mice learned what the reward tone meant",
     "depends_on": ["R2.1.a"]},
    {"id": "F3.1.a", "paragraph": "F3.1", "type": "new_result",
     "quote": "mice licked more after the reward tone", "restates": "R2.1.a"}
  ],
  "left_out": []
}
```

`R2.1.d` is a claim because the order of tones can be checked against the
code or data.
