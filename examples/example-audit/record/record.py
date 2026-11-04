"""Build the example audit's record (steps 3-7) and write record.json.

Each claim and finding is constructed with miragold.schema, so a malformed
record fails here: an unknown type, a traced claim without findings, a
status that contradicts its comparisons. Quotes are taken from the extracted
paragraphs by text, never typed by hand, and values from the derivation's
output by key.

    uv run python examples/example-audit/record/record.py
"""

import datetime
import json
from pathlib import Path

from miragold.schema import (
    AuditRecord,
    Basis,
    Claim,
    ClaimType,
    CodeAnchor,
    Comparison,
    DataAnchor,
    Derivation,
    Drafter,
    DrafterKind,
    Effect,
    Facet,
    Finding,
    Kind,
    ManuscriptAnchor,
    Observation,
    Obtained,
    Source,
    Trace,
    Value,
)
from miragold.values import read_values

HERE = Path(__file__).parent
WORKSPACE = HERE.parent
MANUSCRIPT = "manuscript.txt"

paragraphs = json.loads(
    (WORKSPACE / "work" / "extract" / "paragraphs.json").read_text()
)
by_key = {(p["section"], p["paragraph"]): p for p in paragraphs}

DERIVATION = Derivation(
    script="derivations/values_trials.py",
    output="derivations/output/values/trials.json",
)
derived = read_values(WORKSPACE / DERIVATION.output)["values"]


def quote(section: str, paragraph: int, text: str) -> ManuscriptAnchor:
    """An anchor for ``text``, which must occur once in the paragraph."""
    p = by_key[(section, paragraph)]
    start = p["text"].index(text)
    if p["text"].count(text) != 1:
        raise ValueError(f"{text!r} is not unique in {section} ¶{paragraph}")
    return ManuscriptAnchor(
        file=MANUSCRIPT, section=section, paragraph=paragraph,
        char_start=start, char_end=start + len(text), page=p["page"], quote=text,
    )  # fmt: skip


def got(
    name: str, key: str, unit: str | None = None, subject: str | None = None
) -> Value:
    """A value from the derivation's output."""
    return Value(name=name, value=derived[key], unit=unit, subject=subject, key=key)


LEARNING = "Results › Learning"
TASK = "Methods › Subjects and task"

# --- Claims (steps 3-4) ----------------------------------------------------------

claims = [
    Claim(
        id="R1.2.a",
        type=ClaimType.NEW_RESULT,
        anchor=quote(
            LEARNING, 2, "Twelve mice completed 3,600 trials over 10 sessions"
        ),
        trace=Trace.TRACED,
    ),
    Claim(
        id="R1.2.b",
        type=ClaimType.NEW_RESULT,
        anchor=quote(
            LEARNING, 2, "Accuracy rose from 60% in session 1 to 87% in session 10"
        ),
        trace=Trace.TRACED,
    ),
]

# --- Findings (steps 5-7) --------------------------------------------------------

# R1.2.a: the sample. The number of mice and sessions agree with the data; the
# number of trials does not, so they are separate findings, each with one status.
said_mice = Value(name="mice", value=12)
said_sessions = Value(name="sessions", value=10)
said_trials = Value(name="trials", value=3600)
data_mice, data_sessions = got("mice", "mice"), got("sessions", "sessions")
data_trials = got("trials", "trials/all")


def data_obs(
    statement: str, values: list[Value], quote_text: str, derivation: str
) -> Observation:
    return Observation(
        source=Source.DATA,
        statement=statement,
        obtained=Obtained.RECOMPUTED,
        values=tuple(values),
        anchor=DataAnchor(
            file="data/trials.json",
            derivation=derivation,
            produced_by=DERIVATION,
            quote=quote_text,
        ),
    )


results_a = Observation(
    source=Source.RESULTS,
    statement="Twelve mice completed 3,600 trials over 10 sessions.",
    obtained=Obtained.QUOTED,
    anchor=claims[0].anchor,
    values=(said_mice, said_trials, said_sessions),
)

findings = [
    Finding(
        id="R1.2.a/population",
        claim_id="R1.2.a",
        facet=Facet.POPULATION,
        basis=Basis.EXACT,
        comparisons=(
            Comparison(kind=Kind.EXACT, stated=(said_mice,), observed=(data_mice,)),
            Comparison(
                kind=Kind.EXACT, stated=(said_sessions,), observed=(data_sessions,)
            ),
        ),
        summary="The Results state 12 mice and 10 sessions; the data contain 12 mice and 10 sessions.",
        observations=(
            results_a,
            data_obs(
                "The data contain 12 mice and 10 sessions.",
                [data_mice, data_sessions],
                "12 mice; 10 sessions",
                "count of distinct mouse and session IDs",
            ),
        ),
        effect=Effect.NONE_OBSERVED,
        status="consistent",
    ),
    Finding(
        id="R1.2.a/quantity",
        claim_id="R1.2.a",
        facet=Facet.QUANTITY,
        basis=Basis.EXACT,
        comparisons=(
            Comparison(kind=Kind.EXACT, stated=(said_trials,), observed=(data_trials,)),
        ),
        summary=(
            "The Results state 3,600 trials; the data contain 3,540, which is "
            "60 fewer than 12 mice × 10 sessions × 30 trials."
        ),
        observations=(
            results_a,
            data_obs(
                "The data contain 3,540 trials.",
                [data_trials],
                "3,540 trials",
                "count of all trials, none excluded",
            ),
        ),
        effect=Effect.INDIRECT,
        status="differs",
    ),
]

# R1.2.b: the accuracies, recomputed with the Methods' exclusion rule.
said_s1 = Value(name="accuracy", value=60, unit="%", subject="session 1", decimals=0)
said_s10 = Value(name="accuracy", value=87, unit="%", subject="session 10", decimals=0)
data_s1 = got("accuracy", "accuracy_pct/session_1", "%", "session 1")
data_s10 = got("accuracy", "accuracy_pct/session_10", "%", "session 10")

findings.append(
    Finding(
        id="R1.2.b/quantity",
        claim_id="R1.2.b",
        facet=Facet.QUANTITY,
        basis=Basis.REPORTED_PRECISION,
        comparisons=(
            Comparison(kind=Kind.PRECISION, stated=(said_s1,), observed=(data_s1,)),
            Comparison(kind=Kind.PRECISION, stated=(said_s10,), observed=(data_s10,)),
        ),
        summary=(
            "The Results state 60% and 87% correct in sessions 1 and 10; "
            "recomputed from the data as the Methods describe, they are 60.1% and 87.3%."
        ),
        observations=(
            Observation(
                source=Source.RESULTS,
                statement="Accuracy was 60% in session 1 and 87% in session 10.",
                obtained=Obtained.QUOTED,
                anchor=claims[1].anchor,
                values=(said_s1, said_s10),
            ),
            data_obs(
                "Recomputed accuracy is 60.1% in session 1 and 87.3% in session 10.",
                [data_s1, data_s10],
                "session 1: 60.1%; session 10: 87.3%",
                "percentage correct per session, excluding response times > 2 s",
            ),
        ),
        effect=Effect.NONE_OBSERVED,
        status="consistent",
    )
)

# R1.2.b: the exclusion rule behind the accuracies. Methods and code differ; the
# derivation shows the stated values are the same with either cutoff.
said_cutoff = Value(name="response-time cutoff", value=2, unit="s")
code_cutoff = Value(name="response-time cutoff", value=2.5, unit="s")
findings.append(
    Finding(
        id="R1.2.b/analysis",
        claim_id="R1.2.b",
        facet=Facet.ANALYSIS,
        basis=Basis.EXACT,
        comparisons=(
            Comparison(kind=Kind.EXACT, stated=(said_cutoff,), observed=(code_cutoff,)),
        ),
        summary=(
            "The Methods exclude trials with response times longer than 2 s; the "
            "code excludes those longer than 2.5 s. With the code's cutoff, accuracy "
            f"is {derived['accuracy_pct_code_cutoff/session_1']:.1f}% and "
            f"{derived['accuracy_pct_code_cutoff/session_10']:.1f}%, which also round "
            "to the stated 60% and 87%."
        ),
        observations=(
            Observation(
                source=Source.METHODS,
                statement="Trials with response times longer than 2 s are excluded.",
                obtained=Obtained.QUOTED,
                anchor=quote(
                    TASK,
                    2,
                    "Trials with response times longer than 2 s were excluded from analysis.",
                ),
                values=(said_cutoff,),
            ),
            Observation(
                source=Source.CODE,
                statement="The code keeps trials with response times up to 2.5 s.",
                obtained=Obtained.READ,
                anchor=CodeAnchor(
                    file="code/analysis.py",
                    line_start=8,
                    line_end=9,
                    quote='# Exclude slow responses\ntrials = [t for t in trials if t["rt"] <= 2.5]',
                ),
                values=(code_cutoff,),
            ),
        ),
        effect=Effect.NONE_OBSERVED,
        status="differs",
    )
)

drafter = Drafter(
    kind=DrafterKind.MODEL,
    name="Claude Opus 5.5",
    model_id="claude-opus-5-5",
    stage="Claude Code session",
    date=datetime.date(2026, 10, 30),
)
record = AuditRecord(drafted_by=drafter, claims=tuple(claims), findings=tuple(findings))
(HERE / "record.json").write_text(record.model_dump_json(indent=1) + "\n")
print(f"{len(claims)} claims, {len(findings)} findings -> {HERE / 'record.json'}")
