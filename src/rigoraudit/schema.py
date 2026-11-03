# Copyright (c) 2026, Joshua I. Gold
# SPDX-License-Identifier: BSD-2-Clause
"""Core data model for an audit: the evidence graph described in docs/design.md.

- Anchors locate exact text or values in the audit materials.
- Claims are statements in the manuscript.
- Observations record what one source (Methods, Results, code, output, data)
  says about a claim, with an anchor, a verbatim quote, and any values it
  states or yields.
- Findings compare observations for one facet of one claim.
- Cross-claim findings compare values the manuscript prints in different
  claims (decision 0016).

Every item records who drafted it (decision 0010): the record states its
drafter once, and an item names its own only when it differs.

Validation enforces decision 0003: a finding cannot exist without anchored,
quoted evidence from every source it involves. It also enforces decision
0007: numeric comparisons are stored as values and tolerances, and their
status is computed, never set by hand.
"""

from __future__ import annotations

import datetime
import math
import operator
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import Annotated, Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SCHEMA_VERSION = 4
RECORD = Path("record/record.json")
"""Where a workspace keeps its record."""

NonEmptyStr = Annotated[str, Field(pattern=r"\S")]
"""A string containing at least one non-whitespace character."""

ClaimId = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")]
"""Stable claim identifier shown in the report margin, e.g. ``R2.3.b``."""

FindingId = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._/-]*$")]
"""Stable finding identifier: the claim ID, then ``/``-separated parts, e.g.
``R1.1.b/condition/mean-B``. Overrides in ``review/`` refer to it."""


class Frozen(BaseModel):
    """A model that cannot be changed once made, and refuses unknown fields."""

    model_config = ConfigDict(frozen=True, extra="forbid")


def _check_relative_path(path: str, root: str) -> str:
    """Require a path relative to ``root`` that stays inside it."""
    p = PurePosixPath(path)
    if not path or p.is_absolute() or ".." in p.parts:
        raise ValueError(
            f"path must be relative to {root} and stay inside it: {path!r}"
        )
    return path


def _check_materials_path(path: str) -> str:
    """Require a path relative to the workspace's ``materials/`` directory."""
    return _check_relative_path(path, "materials/")


def _check_workspace_path(path: str) -> str:
    """Require a path relative to the workspace root."""
    return _check_relative_path(path, "the workspace")


# --- Vocabularies -----------------------------------------------------------


class ClaimType(StrEnum):
    """Kinds of claim; each is traced differently (decision 0002)."""

    NEW_RESULT = "new_result"
    REFERENCED_RESULT = "referenced_result"
    COMPARISON = "comparison"
    INTERPRETATION = "interpretation"
    PROCEDURE = "procedure"
    NO_STATED_SUPPORT = "no_stated_support"


class Facet(StrEnum):
    """Components of a new-result claim that are traced separately."""

    QUANTITY = "quantity"
    POPULATION = "population"
    ANALYSIS = "analysis"
    CONDITION = "condition"
    DISPLAY = "display"


class Source(StrEnum):
    """Where an observation comes from."""

    METHODS = "methods"
    RESULTS = "results"
    CODE = "code"
    OUTPUT = "output"
    """Values produced by running the code."""
    DATA = "data"


class Status(StrEnum):
    """Neutral outcome of a comparison (decision 0004)."""

    CONSISTENT = "consistent"
    DIFFERS = "differs"
    NOT_DESCRIBED = "not_described"
    NOT_VERIFIABLE = "not_verifiable"


class Basis(StrEnum):
    """How two sources were compared (decision 0006)."""

    EXACT = "exact"
    """Counts, identities, codings, code settings, named tests: any mismatch differs."""
    REPORTED_PRECISION = "reported_precision"
    """A reported statistic vs its recomputation, at the reported precision."""
    DESIGN_VS_REALIZATION = "design_vs_realization"
    """A stated design vs the recorded trials, within a practical tolerance."""
    DIRECTION = "direction"
    """A qualitative statement (higher, shallower, increases) vs the data's direction."""


class Effect(StrEnum):
    """Potential effect of a finding on the reported result; used for ordering."""

    DIRECT = "direct"
    """Bears on the reported value or statistic itself."""
    INDIRECT = "indirect"
    """Bears on the sample, condition, or analysis behind the reported value."""
    PRESENTATION = "presentation"
    """Rounding, labeling, or wording only."""
    NONE_OBSERVED = "none_observed"
    """Checked; does not change anything reported in these data."""
    UNKNOWN = "unknown"


class Trace(StrEnum):
    """How far a claim has been traced; stated explicitly, never inferred."""

    PENDING = "pending"
    """Not yet traced."""
    TRACED = "traced"
    """Traced to its sources; the claim has findings."""
    VIA_DEPENDENCIES = "via_dependencies"
    """Supported by the claims it depends on, not traced directly."""
    DEFERRED = "deferred"
    """Rests on citations; citation tracing is deferred (decision 0005)."""


class Obtained(StrEnum):
    """How the audit obtained an observation (decision 0007)."""

    QUOTED = "quoted"
    """Manuscript text, quoted."""
    READ = "read"
    """Code inspected, not run."""
    EXECUTED = "executed"
    """The authors' code, run by the audit."""
    RECOMPUTED = "recomputed"
    """The audit's own computation."""
    COMPUTED = "computed"
    """Worked out by the tool from values printed in the manuscript, such as
    p from a printed t and its degrees of freedom (decision 0015)."""


_OBTAINED_FOR_SOURCE = {
    Source.METHODS: {Obtained.QUOTED, Obtained.COMPUTED},
    Source.RESULTS: {Obtained.QUOTED, Obtained.COMPUTED},
    Source.CODE: {Obtained.READ, Obtained.EXECUTED},
    Source.OUTPUT: {Obtained.EXECUTED},
    Source.DATA: {Obtained.EXECUTED, Obtained.RECOMPUTED},
}


class Relation(StrEnum):
    """How a value is stated, e.g. ``p < 0.001`` or ``~140 ms``."""

    EQ = "="
    LT = "<"
    LE = "≤"
    GT = ">"
    GE = "≥"
    APPROX = "~"


_INEQUALITIES = {
    Relation.LT: operator.lt,
    Relation.LE: operator.le,
    Relation.GT: operator.gt,
    Relation.GE: operator.ge,
}


class Kind(StrEnum):
    """Comparison kinds and their tolerances (decision 0006, rule 4)."""

    EXACT = "exact"
    """Observed equals the reference."""
    PRECISION = "precision"
    """Observed rounds to the stated value at the decimals shown."""
    INEQUALITY = "inequality"
    """Observed satisfies the stated inequality, e.g. ``p < 0.001``."""
    RELATIVE = "relative"
    """Observed within ``amount`` (a fraction) of the reference."""
    ABSOLUTE = "absolute"
    """Observed within ``amount`` (in the values' unit) of the reference."""
    RANGE = "range"
    """Every observed value within the stated low and high values."""
    SIGN = "sign"
    """Observed has the stated sign (stated value +1 or -1)."""


_KINDS_FOR_BASIS = {
    Basis.EXACT: {Kind.EXACT},
    Basis.REPORTED_PRECISION: {Kind.PRECISION, Kind.INEQUALITY, Kind.RELATIVE},
    Basis.DESIGN_VS_REALIZATION: {Kind.RELATIVE, Kind.ABSOLUTE, Kind.RANGE},
    Basis.DIRECTION: {Kind.SIGN, Kind.INEQUALITY},
}
"""Direction findings use inequalities for wording with a numeric threshold:
"majority" (share > 0.5), and significance wording read at the reported alpha."""

_COMPARISON_REQUIRED = {
    Basis.REPORTED_PRECISION,
    Basis.DESIGN_VS_REALIZATION,
    Basis.DIRECTION,
}
"""Bases whose findings are always numeric; exact may compare identities."""


# --- Provenance -------------------------------------------------------------


class DrafterKind(StrEnum):
    """Who drafted an item (decision 0010, rule 1)."""

    PERSON = "person"
    MODEL = "model"
    TOOL = "tool"
    """The tool itself, for findings it works out with no judgment (decision 0015)."""


class Drafter(Frozen):
    """A person, or a named model and version, and when they drafted an item."""

    kind: DrafterKind
    name: NonEmptyStr
    """The person's name, the model's, e.g. ``Claude Opus 5.5``, or the tool's."""
    model_id: str | None = None
    """The provider's exact model identifier; required for a model."""
    stage: str | None = None
    """The pipeline stage, or how the model was used, e.g. ``segment`` or
    ``Claude Code session``; required for a model or the tool."""
    prompt_version: str | None = None
    """The stage's prompt version, when the model ran from a tool prompt."""
    date: datetime.date

    @model_validator(mode="after")
    def _fields_fit_kind(self) -> Self:
        if self.kind is DrafterKind.MODEL:
            if not (self.model_id and self.stage):
                raise ValueError("a model drafter names its model_id and stage")
        elif self.model_id or self.prompt_version:
            raise ValueError(
                "model_id and prompt_version describe a model drafter only"
            )
        elif (self.kind is DrafterKind.TOOL) != bool(self.stage):
            raise ValueError("the tool names its stage; a person has none")
        return self


# --- Anchors ----------------------------------------------------------------


class ManuscriptAnchor(Frozen):
    """A span of manuscript text. Offsets are relative to the paragraph."""

    kind: Literal["manuscript"] = "manuscript"
    file: str
    section: NonEmptyStr
    paragraph: int = Field(ge=1)
    char_start: int = Field(ge=0)
    char_end: int
    page: int | None = Field(default=None, ge=1)
    """Page on which the quote starts, for paginated manuscripts."""
    line: int | None = Field(default=None, ge=1)
    """Manuscript line number, when the manuscript has them."""
    quote: NonEmptyStr

    _check_file = field_validator("file")(_check_materials_path)

    @model_validator(mode="after")
    def _span_nonempty(self) -> Self:
        if self.char_end <= self.char_start:
            raise ValueError("char_end must be greater than char_start")
        return self


class CodeAnchor(Frozen):
    """A line range in a source file."""

    kind: Literal["code"] = "code"
    file: str
    line_start: int = Field(ge=1)
    line_end: int
    commit: str | None = None
    quote: NonEmptyStr

    _check_file = field_validator("file")(_check_materials_path)

    @model_validator(mode="after")
    def _range_ordered(self) -> Self:
        if self.line_end < self.line_start:
            raise ValueError("line_end must be at least line_start")
        return self


class Derivation(Frozen):
    """The audit script that produced a value, and its machine-readable output."""

    script: str
    """Path relative to the workspace, e.g. ``derivations/durations.py``."""
    output: str
    """JSON or CSV written by the script, relative to the workspace."""
    drafted_by: Drafter | None = None
    """Who wrote the script, when not the record's drafter."""

    _check_paths = field_validator("script", "output")(_check_workspace_path)


class DataAnchor(Frozen):
    """A value or summary taken from a data file or a generated output."""

    kind: Literal["data"] = "data"
    file: str
    """The file, or the folder of files, relative to ``materials/``."""
    field: str | None = None
    """Column, variable, or key the value comes from."""
    selection: str | None = None
    """Which rows/trials/subjects, e.g. ``subject == 3``."""
    derivation: str | None = None
    """How the audit obtained the value, e.g. ``count of unique subject IDs``."""
    produced_by: Derivation | None = None
    """The script and output holding the values; required when the audit
    ran or computed them (decision 0007)."""
    quote: NonEmptyStr
    """The value(s) as shown to the reader."""

    _check_file = field_validator("file")(_check_materials_path)


Anchor = Annotated[
    ManuscriptAnchor | CodeAnchor | DataAnchor, Field(discriminator="kind")
]

_ANCHOR_KIND_FOR_SOURCE = {
    Source.METHODS: "manuscript",
    Source.RESULTS: "manuscript",
    Source.CODE: "code",
    Source.OUTPUT: "data",
    Source.DATA: "data",
}


# --- Values and comparisons -------------------------------------------------


def same_value(a: object, b: object) -> bool:
    """Equal, with true and false kept apart from 1 and 0."""
    return isinstance(a, bool) == isinstance(b, bool) and a == b


class Value(Frozen):
    """One value stated by, or obtained from, a source."""

    name: NonEmptyStr
    """What the value is, e.g. ``mean``, ``SEM``, ``p``, ``sessions``."""
    value: bool | int | float | str
    """Strings and true/false only for exact comparisons, e.g. of identities
    and codings."""
    unit: str | None = None
    """e.g. ``ms``; ``%`` for proportions shown as percentages."""
    subject: str | None = None
    """The subject or selection the value applies to, e.g. ``subject B``."""
    relation: Relation = Relation.EQ
    """How the value is stated; ``=`` for obtained values."""
    decimals: int | None = Field(default=None, ge=0)
    """Decimal places shown, for stated values compared at reported precision."""
    key: str | None = None
    """Where the value sits in its derivation's output (``Derivation.output``)."""

    @model_validator(mode="after")
    def _finite(self) -> Self:
        if isinstance(self.value, float) and not math.isfinite(self.value):
            raise ValueError("a value must be finite")
        return self

    def printed(self) -> str:
        """The value as the text gives it: relation, number at the decimals
        shown (0.10, not 0.1), and unit."""
        x = self.value
        if isinstance(x, float) and self.decimals is not None:
            x = _fmt(x, self.decimals)
        rel = "" if self.relation is Relation.EQ else f"{self.relation} "
        unit = (
            "" if not self.unit else self.unit if self.unit == "%" else f" {self.unit}"
        )
        return f"{rel}{x}{unit}"


def _decimals_of(x: float) -> int:
    text = repr(float(x))
    return 0 if "e" in text else len(text.split(".")[1].rstrip("0"))


def _fmt(x: float, places: int) -> str:
    return f"{x:.{places}f}"


class Comparison(Frozen):
    """One stated value compared with what the audit observed (decision 0007).

    The reference is ``predicted`` when given (decision 0006, rule 1: what the
    stated value predicts for the observed quantity), otherwise ``stated``.
    """

    kind: Kind
    stated: tuple[Value, ...] = Field(min_length=1, max_length=2)
    """One value; two (low, high) for ``range``."""
    observed: tuple[Value, ...] = Field(min_length=1)
    """Every observed value must agree for the comparison to agree."""
    predicted: Value | None = None
    amount: float | None = Field(default=None, gt=0)
    """Tolerance for ``relative`` (a fraction, 0.05 for ±5%) or ``absolute``
    (in the values' unit)."""
    hedge: str | None = None
    """Wording that set the tolerance, e.g. ``~140``; for an inequality, the
    wording it reads, e.g. ``no reliable difference`` read as p ≥ 0.05; for a
    sign, the words that state the direction, e.g. ``higher``."""
    span: tuple[Value, Value] | None = None
    """For a value worked out from rounded printed values: the lowest and
    highest it can be, given that rounding. It agrees if any value in the
    span agrees (decision 0015, note of 2026-11-02)."""

    @model_validator(mode="after")
    def _well_formed(self) -> Self:
        k, stated = self.kind, self.stated
        if (len(stated) == 2) != (k is Kind.RANGE):
            raise ValueError("range compares against two stated values; others one")
        if (self.amount is not None) != (k in (Kind.RELATIVE, Kind.ABSOLUTE)):
            raise ValueError("amount is required for relative and absolute only")
        if self.predicted is not None and k not in (
            Kind.EXACT,
            Kind.RELATIVE,
            Kind.ABSOLUTE,
        ):
            raise ValueError(
                f"a {k} comparison uses the stated value, not a prediction"
            )
        values = [
            *stated,
            *self.observed,
            *([self.predicted] if self.predicted else []),
        ]
        if k is not Kind.EXACT and any(isinstance(v.value, bool | str) for v in values):
            raise ValueError(f"a {k} comparison needs numeric values")
        relations = {v.relation for v in stated}
        if k is Kind.INEQUALITY:
            if not relations <= set(_INEQUALITIES):
                raise ValueError(
                    "an inequality comparison needs a stated <, ≤, >, or ≥"
                )
        elif k is Kind.RELATIVE:
            if not relations <= {Relation.EQ, Relation.APPROX}:
                raise ValueError("a relative comparison needs a stated = or ~ value")
        elif relations != {Relation.EQ}:
            raise ValueError(f"a {k} comparison needs a stated = value")
        if k is Kind.PRECISION and stated[0].decimals is None:
            raise ValueError("a precision comparison needs the stated decimals")
        if k is Kind.RANGE and stated[0].value > stated[1].value:
            raise ValueError("range values must be ordered low, high")
        if k is Kind.SIGN and stated[0].value not in (1, -1):
            raise ValueError("a sign comparison states +1 or -1")
        if any(v.relation is not Relation.EQ for v in self.observed):
            raise ValueError("observed values are stated with =")
        if self.span is not None:
            if k not in (Kind.PRECISION, Kind.INEQUALITY) or len(self.observed) != 1:
                raise ValueError(
                    "a span is for one observed value, compared by precision or "
                    "inequality"
                )
            low, high = (v.value for v in self.span)
            x = self.observed[0].value
            if any(isinstance(v, bool | str) for v in (low, high)) or not (
                low <= x <= high
            ):
                raise ValueError(
                    "a span is two numbers, low and high, around the observed value"
                )
        return self

    @property
    def reference(self) -> Value:
        """The value observed values are compared against."""
        return self.predicted or self.stated[0]

    def agrees(self) -> bool:
        """Whether every observed value agrees with the stated value."""
        ref = self.reference.value
        k = self.kind
        if k is Kind.EXACT:
            return all(same_value(o.value, ref) for o in self.observed)
        assert not isinstance(ref, bool | str)  # enforced by _well_formed
        obs = [float(o.value) for o in self.observed]
        slack = 1e-9 * max(1.0, abs(ref))
        if self.span is not None:
            low, high = (float(v.value) for v in self.span)
            if k is Kind.PRECISION:
                half = 0.5 * 10.0 ** -(self.stated[0].decimals or 0)
                return low - slack <= ref + half and high + slack >= ref - half
            compare = _INEQUALITIES[Relation(self.stated[0].relation)]
            # the end of the span nearest the bound decides
            return compare(low if compare(0, 1) else high, ref)
        match k:
            case Kind.PRECISION:
                half = 0.5 * 10.0 ** -(self.stated[0].decimals or 0)
                return all(abs(x - ref) <= half + slack for x in obs)
            case Kind.INEQUALITY:
                compare = _INEQUALITIES[Relation(self.stated[0].relation)]
                return all(compare(x, ref) for x in obs)
            case Kind.RELATIVE:
                bound = (self.amount or 0) * abs(ref)
                return all(abs(x - ref) <= bound + slack for x in obs)
            case Kind.ABSOLUTE:
                return all(abs(x - ref) <= (self.amount or 0) + slack for x in obs)
            case Kind.RANGE:
                low, high = (float(v.value) for v in self.stated)
                return all(low - slack <= x <= high + slack for x in obs)
            case Kind.SIGN:
                return all(math.copysign(1, x) == ref and x != 0 for x in obs)
        raise AssertionError(k)

    def values_text(self) -> str:
        """The stated value beside what was found, short enough for the report:
        ``SD (for block A) 0.20 vs 0.236``."""
        s = self.stated[0]
        name = s.name + (f" (for {s.subject})" if s.subject else "")
        stated = " to ".join(v.printed() for v in self.stated)
        found = ", ".join(
            f"{v.value:.4g}" if isinstance(v.value, float) else v.printed()
            for v in self.observed
        )
        return f"{name} {stated} vs {found}"

    def describe(self) -> str:
        """The tolerance as printed in the report (decision 0006, rule 4)."""
        ref = self.reference
        unit = f" {ref.unit}" if ref.unit and ref.unit != "%" else (ref.unit or "")
        k = self.kind
        if k is Kind.EXACT:
            text = "exact"
        elif k is Kind.PRECISION:
            d = self.stated[0].decimals
            text = f"to the {d} decimal{'s' if d != 1 else ''} shown"
        elif k is Kind.INEQUALITY:
            s = self.stated[0]
            if self.hedge:  # wording with a threshold, e.g. "no reliable difference"
                return f"“{self.hedge}” read as {s.name} {s.relation} {s.value}"
            text = f"as the stated inequality ({s.name} {s.relation} {s.value})"
        elif k is Kind.RANGE:
            low, high = self.stated
            text = (
                f"all values within the stated range ({low.value}–{high.value}{unit})"
            )
        elif k is Kind.SIGN:
            sign = "positive" if self.stated[0].value > 0 else "negative"
            if self.hedge:  # the words that state the direction, e.g. "higher"
                return f"“{self.hedge}” read as direction ({sign})"
            text = f"direction ({sign})"
        else:
            r = float(ref.value)
            amount = self.amount or 0
            band = amount * abs(r) if k is Kind.RELATIVE else amount
            # As precise as the stated value; one place more for a prediction
            places = _decimals_of(float(self.stated[0].value)) + bool(self.predicted)
            if k is Kind.RELATIVE:
                size = f"±{amount * 100:g}%"
            elif ref.unit == "%":
                size = f"±{amount:g} percentage points"
            else:
                size = f"±{amount:g}{unit}"
            of = ""
            if self.predicted:
                of = (
                    f"the {ref.name} "
                    if "predicted" in ref.name
                    else f"the predicted {ref.name} "
                )
            text = (
                f"{size} of {of}{_fmt(r, places)}{unit} "
                f"({_fmt(r - band, places)}–{_fmt(r + band, places)}{unit})"
            )
        if self.hedge:
            text = f"hedged “{self.hedge}”: {text}"
        if self.span is not None:
            low, high = (v.value for v in self.span)
            text += f", allowing for rounding in the printed values ({low:.3g} to {high:.3g})"
        return text


# --- Graph ------------------------------------------------------------------


class Claim(Frozen):
    """A single claim in the manuscript (decision 0002)."""

    id: ClaimId
    type: ClaimType
    anchor: ManuscriptAnchor
    trace: Trace = Trace.PENDING
    depends_on: tuple[ClaimId, ...] = ()
    """Claims an interpretation or comparison rests on."""
    citations: tuple[NonEmptyStr, ...] = ()
    """Reference labels as printed, e.g. ``[12]``."""
    restates: ClaimId | None = None
    """For a claim outside the Results (legend, Abstract, Discussion): the Results claim it repeats."""
    drafted_by: Drafter | None = None
    """Who drafted the claim, when not the record's drafter."""

    @model_validator(mode="after")
    def _consistent_with_type(self) -> Self:
        cited = {ClaimType.REFERENCED_RESULT, ClaimType.COMPARISON}
        if self.type in cited and not self.citations:
            raise ValueError(f"a {self.type} claim must list its citations")
        if self.type is ClaimType.NO_STATED_SUPPORT and (
            self.citations or self.depends_on
        ):
            raise ValueError(
                "a no_stated_support claim cannot have citations or depends_on"
            )
        if self.id in self.depends_on or self.restates == self.id:
            raise ValueError("a claim cannot refer to itself")
        if self.trace is Trace.VIA_DEPENDENCIES and not self.depends_on:
            raise ValueError("a via_dependencies claim must list depends_on")
        if self.trace is Trace.DEFERRED and not self.citations:
            raise ValueError("a deferred claim must list its citations")
        return self


class Observation(Frozen):
    """What one source states or does, with quoted, anchored evidence."""

    source: Source
    statement: NonEmptyStr
    """Neutral plain-language paraphrase, e.g. ``n = 22 after excluding ...``."""
    anchor: Anchor
    obtained: Obtained
    values: tuple[Value, ...] = ()
    """Values the source states or yields; comparisons draw on these."""
    drafted_by: Drafter | None = None
    """Who drafted the observation, when not the finding's drafter."""

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        expected = _ANCHOR_KIND_FOR_SOURCE[self.source]
        if self.anchor.kind != expected:
            raise ValueError(
                f"{self.source} observations need a {expected} anchor, "
                f"got {self.anchor.kind}"
            )
        if self.obtained not in _OBTAINED_FOR_SOURCE[self.source]:
            allowed = ", ".join(sorted(_OBTAINED_FOR_SOURCE[self.source]))
            raise ValueError(
                f"{self.source} observations are obtained as {allowed}, "
                f"not {self.obtained}"
            )
        if isinstance(self.anchor, DataAnchor):
            # Data and output values are always run or computed by the audit.
            if self.anchor.produced_by is None:
                raise ValueError(
                    "data and output observations name the derivation that "
                    "produced them (anchor.produced_by)"
                )
            if not self.values or any(v.key is None for v in self.values):
                raise ValueError(
                    "values from a derivation must each name their key in its output"
                )
            if any(v.relation is not Relation.EQ for v in self.values):
                raise ValueError("obtained values are stated with =")
        elif any(v.key is not None for v in self.values):
            raise ValueError("only values from a derivation have a key")
        return self


def is_stated(o: Observation) -> bool:
    """Whether an observation's values are stated by the manuscript, rather
    than obtained by the audit (from the code, the data, or the text itself)."""
    return (
        o.source in (Source.METHODS, Source.RESULTS)
        and o.obtained is not Obtained.COMPUTED
    )


class Finding(Frozen):
    """Comparison of sources for one facet of one claim.

    With ``comparisons``, the status is computed from them (decision 0007).
    A record may repeat the computed status, as ``record.json`` does, but a
    status that disagrees with the comparisons is rejected.
    """

    id: FindingId
    claim_id: ClaimId
    facet: Facet | None = None
    """None when the finding concerns the claim as a whole."""
    scope: str | None = None
    """The part of the facet covered, when a source covers only part of it,
    e.g. ``bins 2 and 4``. One finding per part keeps each status exact."""
    status: Status
    basis: Basis | None = None
    """How the sources were compared; required for consistent and differs."""
    comparisons: tuple[Comparison, ...] = ()
    """Structured comparisons; required for numeric bases."""
    tolerance: str | None = None
    """The agreement criterion, for comparisons not stated as ``comparisons``
    (e.g. codings). Generated from ``comparisons`` otherwise."""
    summary: NonEmptyStr
    """One neutral sentence: "Methods states X. The code does Y." """
    observations: tuple[Observation, ...]
    not_described_in: tuple[Source, ...] = ()
    """Sources that are silent on what the observed sources state or do."""
    reason: str | None = None
    """Why the comparison could not be made; required for not_verifiable."""
    effect: Effect = Effect.UNKNOWN
    drafted_by: Drafter | None = None
    """Who drafted the finding, when not the record's drafter."""

    @model_validator(mode="before")
    @classmethod
    def _compute_status(cls, data: Any) -> Any:
        if not isinstance(data, dict) or not data.get("comparisons"):
            return data
        comparisons = [
            c if isinstance(c, Comparison) else Comparison.model_validate(c)
            for c in data["comparisons"]
        ]
        computed = (
            Status.CONSISTENT
            if all(c.agrees() for c in comparisons)
            else Status.DIFFERS
        )
        given = data.get("status")
        if given is not None and Status(given) is not computed:
            raise ValueError(
                f"finding {data.get('id')}: status {Status(given)} contradicts the "
                f"comparisons, which give {computed}; record an override in "
                "review/ instead"
            )
        return {**data, "status": computed, "comparisons": tuple(comparisons)}

    @property
    def tolerance_text(self) -> str | None:
        """The tolerance as printed in the report."""
        if not self.comparisons:
            return self.tolerance
        # Exact comparisons have no tolerance to state; repeated rules print once
        texts = [c.describe() for c in self.comparisons if c.kind is not Kind.EXACT]
        return "; ".join(dict.fromkeys(texts)) or None

    @model_validator(mode="after")
    def _evidence_matches_status(self) -> Self:
        if not self.id.startswith(f"{self.claim_id}/"):
            raise ValueError(f"finding id {self.id!r} must start with {self.claim_id}/")
        sources = {o.source for o in self.observations}
        # a value the tool worked out from the text is checked against that text
        sides = {(o.source, o.obtained is Obtained.COMPUTED) for o in self.observations}
        compared = self.status in (Status.CONSISTENT, Status.DIFFERS)
        if compared and len(sides) < 2:
            raise ValueError(
                f"a {self.status} finding needs observations from at least two "
                "sources, or a value computed from the text beside the text"
            )
        if compared != (self.basis is not None):
            raise ValueError(
                "consistent and differs findings state their comparison basis; "
                "other statuses have none"
            )
        if self.status is Status.NOT_DESCRIBED:
            if not self.observations or not self.not_described_in:
                raise ValueError(
                    "a not_described finding needs an observation and the "
                    "sources that are silent"
                )
            if sources & set(self.not_described_in):
                raise ValueError(
                    "a source cannot be both observed and not_described_in"
                )
        elif self.not_described_in:
            raise ValueError("not_described_in is only used for not_described")
        if self.status is Status.NOT_VERIFIABLE and not (
            self.reason and self.reason.strip()
        ):
            raise ValueError("a not_verifiable finding must state the reason")
        self._check_comparisons()
        return self

    def _check_comparisons(self) -> None:
        if self.basis in _COMPARISON_REQUIRED and not self.comparisons:
            raise ValueError(f"a {self.basis} finding states its values as comparisons")
        if not self.comparisons:
            return
        if self.tolerance is not None:
            raise ValueError(
                "the tolerance is generated from the comparisons; do not set it"
            )
        assert self.basis is not None  # comparisons imply a computed status
        stated = [v for o in self.observations if is_stated(o) for v in o.values]
        obtained = [v for o in self.observations if not is_stated(o) for v in o.values]
        for c in self.comparisons:
            if c.kind not in _KINDS_FOR_BASIS[self.basis]:
                raise ValueError(
                    f"a {c.kind} comparison does not fit basis {self.basis}"
                )
            if any(v not in stated for v in c.stated):
                raise ValueError(
                    "stated values must appear in a methods or results observation"
                )
            if any(v not in obtained for v in (*c.observed, *(c.span or ()))):
                raise ValueError(
                    "observed values must appear in a code, output, data, or "
                    "computed observation"
                )
            if c.predicted is not None and c.predicted not in stated + obtained:
                raise ValueError("a predicted value must appear in an observation")


class Context(Frozen):
    """Lines a claim card shows beside a reported test, with no status
    (decision 0015, items 9 and 11): the test as the text prints it, what it
    assumes, and plain facts about the values behind it."""

    claim_id: ClaimId
    scope: str | None = None
    """The test, when the claim reports several, e.g. ``test 2``."""
    test: NonEmptyStr
    """The test as the text prints it, e.g. ``paired t test, t(22) = 2.10, p = 0.047``."""
    assumes: str | None = None
    """E.g. ``Assumes independent observations, roughly normal group means.``"""
    data: str | None = None
    """E.g. ``Data: A, N = 12, skew 0.4; B, N = 12, skew 1.8; ...``"""


class Rule(StrEnum):
    """Why values from different claims were set side by side (decision 0016)."""

    RESTATES = "restates"
    """One claim restates the other."""
    SAME_PLACE = "same_place"
    """Their findings cite the same code lines, data, or Methods paragraph."""
    SAME_LABEL = "same_label"
    """The values have the same name, subject, and unit."""
    SAME_MEANING = "same_meaning"
    """No rule proposed them; an assistant found them the same quantity, for
    the same population and condition."""


class CrossValue(Frozen):
    """One value the manuscript prints, in one claim."""

    claim_id: ClaimId
    facet: Facet | None = None
    value: Value
    anchor: ManuscriptAnchor


class CrossFinding(Frozen):
    """Values for one thing that the manuscript prints in two or more claims,
    compared with each other (decision 0016). Made by the tool, never by hand."""

    id: FindingId
    claim_ids: tuple[ClaimId, ...] = Field(min_length=2)
    rules: tuple[Rule, ...] = Field(min_length=1)
    status: Literal[Status.CONSISTENT, Status.DIFFERS]
    values: tuple[CrossValue, ...] = Field(min_length=2)
    summary: NonEmptyStr
    """One neutral sentence, e.g. "R3.1.b and F4.2.a give sessions as 60 and 61." """
    reason: NonEmptyStr
    """Why the values are about one thing, naming the population and the
    condition, from the assistant that confirmed the group."""

    @model_validator(mode="after")
    def _claims_match_values(self) -> Self:
        if self.claim_ids != tuple(dict.fromkeys(v.claim_id for v in self.values)):
            raise ValueError("claim_ids lists the values' claims, in their order")
        return self


class AuditRecord(Frozen):
    """All claims and findings for one audit; canonical file in ``work/``."""

    schema_version: Literal[4] = SCHEMA_VERSION
    drafted_by: Drafter
    """Who drafted the record; items name their own drafter only when it differs."""
    claims: tuple[Claim, ...] = ()
    findings: tuple[Finding, ...] = ()
    context: tuple[Context, ...] = ()
    """Set by the tool; no status."""

    @model_validator(mode="after")
    def _references_resolve(self) -> Self:
        check_claims(self.claims)
        known = {c.id for c in self.claims}
        finding_ids = [f.id for f in self.findings]
        duplicates = {i for i in finding_ids if finding_ids.count(i) > 1}
        if duplicates:
            raise ValueError(f"duplicate finding ids: {sorted(duplicates)}")
        for f in self.findings:
            if f.claim_id not in known:
                raise ValueError(f"finding refers to unknown claim {f.claim_id}")
        for x in self.context:
            if x.claim_id not in known:
                raise ValueError(f"context refers to unknown claim {x.claim_id}")
        with_findings = {f.claim_id for f in self.findings}
        for c in self.claims:
            if (c.trace is Trace.TRACED) != (c.id in with_findings):
                raise ValueError(
                    f"claim {c.id}: trace is {c.trace} but it has "
                    f"{'findings' if c.id in with_findings else 'no findings'}; "
                    "a claim has findings exactly when it is traced"
                )
        return self

    def drafter_of(self, item: Claim | Finding) -> Drafter:
        """Who drafted a claim or finding: its own drafter, else the record's."""
        return item.drafted_by or self.drafted_by

    def findings_for(self, claim_id: str) -> tuple[Finding, ...]:
        """Return the findings for one claim, in record order."""
        return tuple(f for f in self.findings if f.claim_id == claim_id)


def check_claims(claims: tuple[Claim, ...]) -> None:
    """Reject duplicate claim IDs and references to claims not in ``claims``."""
    ids = [c.id for c in claims]
    duplicates = {i for i in ids if ids.count(i) > 1}
    if duplicates:
        raise ValueError(f"duplicate claim ids: {sorted(duplicates)}")
    known = set(ids)
    for c in claims:
        missing = set(c.depends_on) - known
        if c.restates is not None and c.restates not in known:
            missing.add(c.restates)
        if missing:
            raise ValueError(f"claim {c.id} refers to unknown {sorted(missing)}")
