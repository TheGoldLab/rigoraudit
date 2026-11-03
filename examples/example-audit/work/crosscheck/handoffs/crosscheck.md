# Find the values printed for one thing in more than one claim

You are helping audit a scientific paper. Each claim has been checked
against its own sources, but never against the other claims. A paper can
give one quantity two different values in two places (a count in the
Results and in a figure legend), and only setting the claims side by side
shows it.

Below is every value the paper prints in the claims audited, claim by
claim, each labelled `V1`, `V2`, …, with its name, subject, unit, and the
words it is printed in. Say which values, from different claims, are about
the same thing. The tool then compares the values in each group; do not
compare them yourself, and do not judge which is right.

Values are about the same thing only if all three are the same:

- **the quantity**: what is counted or measured (number of sessions,
  mean reaction time, the slope of one fit);
- **the population**: who or what it is about (the same subjects, the
  same group, the same units or cells, the same set of simulated agents);
- **the condition**: the task, session, block, stimulus, analysis, or
  case it is computed for.

Read the claim's sentence and the value's words for each of these. Two
values with the same name are often not the same thing:

- one word for the quantity, in two tasks or two groups ("accuracy" in the
  easy task and in the hard task; "N" for the trained and the naive
  group);
- one analysis run on two populations (a fit to the human data and to the
  model's);
- two cases of one formula (with the learning term and without it);
- numbers that are not values at all: list numbers ("1)", "2)"), figure
  panel numbers, the number of an equation.

And values with different names can be the same thing ("48 of 60
sessions" in one claim, "60 recordings" in another, when both say they are
the sessions analysed in Figure 2). Look for these too: counts of subjects,
trials, sessions, and exclusions are the most common.

## Candidate groups

Three rules have proposed candidate groups, `C1`, `C2`, …: one claim
restates another (*restates*); their findings cite the same code lines,
data, or Methods paragraph (*same place*); the values have the same name,
subject, and unit (*same label*). The rules know nothing of population or
condition, so treat each candidate as a guess. For each one, either:

- **confirm** it: give a group with its values, all of them or only those
  that are one thing (a candidate can be split into several groups); or
- **set it aside** with the reason, if none of its values belong together.

Every candidate must be in a group (any of its values) or set aside.

## Groups

Each group has:

- `values`: two or more labels, from at least two claims. Values marked
  "the same words as" another value are one printed text quoted by two
  claims; a group needs at least two different texts. A value is in one
  group at most.
- `reason`: one sentence naming the quantity, the population, and the
  condition the values share, from the paper's words ("Sessions analysed,
  for the mice of the trained group, in the tone task: both count the same
  sessions shown in Figure 2.").

Leave out values that are about one thing in one claim only. An empty
list of groups is a correct answer when no value is printed twice.

## Your answer

Reply with a single JSON block and nothing else, in this form:

```json
{
  "instructions": "crosscheck v1",
  "groups": [
    {"values": ["V3", "V17"],
     "reason": "Number of mice in the trained group, over the whole study: the Results and the Figure 2 legend count the same animals."},
    {"values": ["V8", "V21", "V40"],
     "reason": "Mean reaction time, for all mice, in the hard condition, from the same analysis."}
  ],
  "set_aside": [
    {"candidate": "C2",
     "reason": "The same loop computes accuracy for the easy and the hard task; V5 is the easy task, V9 the hard."}
  ]
}
```

If the tool finds problems with your answer, it will list them; correct
them and send the whole answer again.

---

# Your task: crosscheck

Follow the instructions above (crosscheck v1) for the 6 values from 2 claims and the 0 candidate groups below.

## Candidate groups, from the rules

(none)

## The values, claim by claim

### R1.2.a (Results › Learning)

> Twelve mice completed 3,600 trials over 10 sessions

- V1 · population · mice: 12 — “Twelve mice completed 3,600 trials over 10 sessions”
- V2 · population · trials: 3600 — “Twelve mice completed 3,600 trials over 10 sessions”
- V3 · population · sessions: 10 — “Twelve mice completed 3,600 trials over 10 sessions”

### R1.2.b (Results › Learning)

> Accuracy rose from 60% in session 1 to 87% in session 10

- V4 · analysis · response-time cutoff; unit s: 2 s — “Trials with response times longer than 2 s were excluded from analysis.”
- V5 · quantity · accuracy; subject session 1; unit %: 60% — “Accuracy rose from 60% in session 1 to 87% in session 10”
- V6 · quantity · accuracy; subject session 10; unit %: 87% — “Accuracy rose from 60% in session 1 to 87% in session 10”
