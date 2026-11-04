---
step: breaks
version: 2
---

# Find where paragraphs begin

You are helping audit a scientific paper. Its text was read from a PDF,
and the tool guessed where each paragraph begins from the page layout. At
the places below it is not sure. Each place shows the text on either side
of a point, marked `‖`. For each one, decide: **does a new paragraph start
at `‖`?**

- Answer `true` when the text after `‖` starts a new paragraph: it turns
  to a new topic, a new experiment or analysis, or a new step of the
  argument.
- Answer `false` when it carries on the same paragraph: the sentence
  before `‖` is unfinished, the text after it starts in the middle of a
  sentence, or it goes on with the same point.
- A sentence cut by an equation or a figure carries on the same
  paragraph, even when what follows `‖` is a separate line in the PDF
  (for example, a sentence that goes on with "where ..." after an
  equation).
- After an equation set on its own line, a new sentence starts a new
  paragraph: answer `true` when the text before `‖` ends with the
  equation and the text after it starts a sentence of its own.
- When it is a close call, answer `false`. Two paragraphs wrongly joined
  do less harm than one wrongly split.

Do not rewrite or correct the text; the answer holds only your decisions.

## Your answer

Reply with a single JSON block and nothing else, deciding every place
once, in this form:

```json
{
  "instructions": "breaks v2",
  "decisions": [
    {"spot": "B1", "new_paragraph": true},
    {"spot": "B2", "new_paragraph": false}
  ]
}
```

If the tool finds problems with your answer, it will list them; correct
them and send the whole answer again.

## Example

### B1 (Results ¶3)

> …so licking rose with reward size in every session. ‖ We next asked
> whether the same mice also learned which tone came first…

### B2 (Results ¶5)

> …the lick rate on each trial was fitted with r = a·t + b ‖ where t is
> the time from tone onset and a is the slope…

### B3 (Methods ¶2)

> …the reward on each trial was drawn from R = 2 + ε ‖ The tones were
> played through a speaker above the spout…

Answer:

```json
{
  "instructions": "breaks v2",
  "decisions": [
    {"spot": "B1", "new_paragraph": true},
    {"spot": "B2", "new_paragraph": false},
    {"spot": "B3", "new_paragraph": true}
  ]
}
```

B1 moves on to a new question; B2 is one sentence cut by an equation;
in B3 a new sentence follows the equation.
