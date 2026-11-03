# Copyright (c) 2026, Joshua I. Gold
# SPDX-License-Identifier: BSD-2-Clause
"""The review log: every reviewer action on a record (decision 0010).

The record's statuses are computed and its structure is drafted; neither is
edited by hand. A reviewer acts through a fixed set of operations, each kept
as an entry in ``review/log.json``: the operation, its target, who, when,
why, and a fingerprint of the target as the reviewer saw it. Nothing is
deleted from the log. If a rebuild changes the target, its entries are
stale: they are shown for re-review and not applied.

On claims: Confirm, Edit, Remove, Split, Merge, Add. On findings: Confirm,
Edit trace, Add, Remove, Override. On cross-claim findings (decision 0016),
which the tool works out from the record: Confirm and Override. An Override
(decision 0007, rule 5) gives the status the reviewer would give; the latest
one for a finding is in force.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, ValidationError, model_validator

from rigoraudit.schema import (
    AuditRecord,
    Claim,
    ClaimId,
    ClaimType,
    CrossFinding,
    Finding,
    FindingId,
    ManuscriptAnchor,
    NonEmptyStr,
    Status,
    Trace,
)

LOG = Path("review") / "log.json"
"""The log's place in a workspace."""


class Operation(StrEnum):
    """What a reviewer did (decision 0010, rule 3)."""

    CONFIRM = "confirm"
    EDIT = "edit"
    """A claim's quote extent or type."""
    REMOVE = "remove"
    SPLIT = "split"
    MERGE = "merge"
    ADD = "add"
    EDIT_TRACE = "edit_trace"
    """A finding's anchors or observations."""
    OVERRIDE = "override"


class Target(StrEnum):
    CLAIM = "claim"
    FINDING = "finding"
    CROSS = "cross"
    """A cross-claim finding."""


OPERATIONS_ON = {
    Target.CLAIM: {
        Operation.CONFIRM,
        Operation.EDIT,
        Operation.REMOVE,
        Operation.SPLIT,
        Operation.MERGE,
        Operation.ADD,
    },
    Target.FINDING: {
        Operation.CONFIRM,
        Operation.EDIT_TRACE,
        Operation.ADD,
        Operation.REMOVE,
        Operation.OVERRIDE,
    },
    Target.CROSS: {Operation.CONFIRM, Operation.OVERRIDE},
}


class Entry(BaseModel):
    """One reviewer action on one claim or finding."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    operation: Operation
    target_kind: Target
    target: FindingId
    """The claim, finding, or cross-claim finding acted on; for an Add, the
    new item's ID."""
    reason: NonEmptyStr
    reviewer: NonEmptyStr
    date: datetime.date
    fingerprint: str | None = None
    """:func:`fingerprint` of the target as the reviewer saw it; none for an Add."""
    status: Status | None = None
    """Override: the status the reviewer gives the finding."""
    type: ClaimType | None = None
    """Edit: the claim's new type."""
    anchor: ManuscriptAnchor | None = None
    """Edit: the claim's new quote."""
    claims: tuple[Claim, ...] = ()
    """Split: the parts, each with an ID that starts with the target's. Add: the new claim."""
    absorbs: tuple[ClaimId, ...] = ()
    """Merge: the claims folded into the target, whose IDs are retired."""
    finding: Finding | None = None
    """Add or Edit trace on a finding: the finding as it should be."""

    @model_validator(mode="after")
    def _payload_fits_operation(self) -> Self:
        op = self.operation
        if op not in OPERATIONS_ON[self.target_kind]:
            raise ValueError(f"{op} is not an operation on a {self.target_kind}")
        if (self.fingerprint is None) != (op is Operation.ADD):
            raise ValueError("every entry but an Add records the target's fingerprint")
        given = {
            name
            for name in ("status", "type", "anchor", "finding")
            if getattr(self, name) is not None
        } | {name for name in ("claims", "absorbs") if getattr(self, name)}
        expected = self._payload_for(op)
        if not given <= expected[0] or not expected[1] <= given:
            needs = ", ".join(sorted(expected[1] or expected[0])) or "nothing else"
            raise ValueError(f"a {self.target_kind} {op} entry takes {needs}")
        if op is Operation.EDIT and not given:
            raise ValueError("an Edit gives the claim's new type, quote, or both")
        if op is Operation.SPLIT:
            if len(self.claims) < 2:
                raise ValueError("a Split gives at least two claims")
            if any(
                c.id == self.target or not c.id.startswith(self.target)
                for c in self.claims
            ):
                raise ValueError(
                    f"split parts get new IDs that start with {self.target}"
                )
        if op is Operation.MERGE and self.target in self.absorbs:
            raise ValueError("a claim cannot absorb itself")
        if (
            op is Operation.ADD
            and self.target_kind is Target.CLAIM
            and (len(self.claims) != 1 or self.claims[0].id != self.target)
        ):
            raise ValueError("an Add gives one claim, with the target's ID")
        if self.finding is not None and self.finding.id != self.target:
            raise ValueError("the finding's ID must be the target")
        return self

    def _payload_for(self, op: Operation) -> tuple[set[str], set[str]]:
        """(allowed, required) payload fields for an operation on this target."""
        on_claim = self.target_kind is Target.CLAIM
        if op is Operation.OVERRIDE:
            return {"status"}, {"status"}
        if op is Operation.EDIT:
            return {"type", "anchor"}, set()
        if op is Operation.SPLIT or (op is Operation.ADD and on_claim):
            return {"claims"}, {"claims"}
        if op is Operation.MERGE:
            return {"absorbs"}, {"absorbs"}
        if op in (Operation.ADD, Operation.EDIT_TRACE):
            return {"finding"}, {"finding"}
        return set(), set()


class ReviewLog(BaseModel):
    """Contents of ``review/log.json``."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    log_version: Literal[1] = 1
    entries: tuple[Entry, ...] = ()


def fingerprint(item: Claim | Finding | CrossFinding) -> str:
    """Digest of what a reviewer judges in a claim or finding.

    For a claim: its type, quote and place, and what it cites or rests on.
    For a finding: its status, comparisons, and evidence; for a cross-claim
    finding, its status and values. A finding's summary is excluded, so
    rephrasing it does not make its entries stale; any change to a value,
    quote, or rule does.
    """
    if isinstance(item, CrossFinding):
        content = {
            "status": item.status,
            "values": [
                {"claim": x.claim_id, "quote": x.anchor.quote}
                | {"value": x.value.model_dump(mode="json")}
                for x in item.values
            ],
        }
    elif isinstance(item, Claim):
        content = item.model_dump(mode="json", include={
            "type", "anchor", "depends_on", "citations", "restates",
        })  # fmt: skip
    else:
        content = {
            "status": item.status,
            "basis": item.basis,
            "comparisons": [c.model_dump(mode="json") for c in item.comparisons],
            "tolerance": item.tolerance,
            "evidence": [
                {
                    "source": o.source,
                    "quote": o.anchor.quote,
                    "values": [v.model_dump(mode="json") for v in o.values],
                }
                for o in item.observations
            ],
            "not_described_in": item.not_described_in,
            "reason": item.reason,
        }
    text = json.dumps(content, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def load(path: Path) -> tuple[Entry, ...]:
    """Read the log; a missing file means no entries."""
    if not path.is_file():
        return ()
    return ReviewLog.model_validate_json(path.read_text(encoding="utf-8")).entries


def _write(path: Path, entries: tuple[Entry, ...]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".log-", suffix=".json")
    with os.fdopen(fd, "w") as f:
        f.write(ReviewLog(entries=entries).model_dump_json(indent=1) + "\n")
    os.replace(tmp, path)


def add(path: Path, entry: Entry) -> None:
    """Append an entry to the log, writing the file atomically."""
    _write(path, (*load(path), entry))


@dataclass(frozen=True)
class Review:
    """The override in force for one finding; for a cross-claim finding, the
    latest Confirm or Override."""

    override: Entry
    stale: bool
    """The finding has changed since the entry was made."""

    @property
    def applies(self) -> bool:
        return not self.stale


def current(
    record: AuditRecord, entries: tuple[Entry, ...]
) -> tuple[dict[str, Review], tuple[Entry, ...]]:
    """The latest override per finding, and overrides of findings not in the record.

    An override whose finding no longer exists is returned separately so it
    can be reported, not silently dropped. Entries other than overrides are
    not applied here.
    """
    findings = {f.id: f for f in record.findings}
    latest: dict[str, Entry] = {}
    orphans = []
    for e in entries:
        if e.operation is not Operation.OVERRIDE or e.target_kind is Target.CROSS:
            continue
        if e.target in findings:
            latest[e.target] = e
        else:
            orphans.append(e)
    reviews = {
        fid: Review(e, stale=e.fingerprint != fingerprint(findings[fid]))
        for fid, e in latest.items()
    }
    return reviews, tuple(orphans)


def current_cross(
    found: tuple[CrossFinding, ...], entries: tuple[Entry, ...]
) -> tuple[dict[str, Review], tuple[Entry, ...]]:
    """The latest Confirm or Override per cross-claim finding, and those of
    cross-claim findings no longer found, as :func:`current` does."""
    by_id = {x.id: x for x in found}
    latest: dict[str, Entry] = {}
    orphans = []
    for e in entries:
        if e.target_kind is not Target.CROSS:
            continue
        if e.target in by_id:
            latest[e.target] = e
        else:
            orphans.append(e)
    reviews = {
        xid: Review(e, stale=e.fingerprint != fingerprint(by_id[xid]))
        for xid, e in latest.items()
    }
    return reviews, tuple(orphans)


@dataclass(frozen=True)
class Applied:
    """The reviewed record: the draft with the log applied (decision 0010, rule 5)."""

    record: AuditRecord
    applied: tuple[Entry, ...]
    stale: tuple[Entry, ...]
    """Entries whose target has changed or gone since the reviewer saw it."""
    refused: tuple[tuple[Entry, str], ...]
    """Entries that would leave the record invalid, with the reason."""
    retired: frozenset[str]
    """Claim IDs removed, split, or merged away; never used again."""


def reviewed(draft: AuditRecord, workspace: Path) -> AuditRecord:
    """The reviewed record: ``draft`` with the workspace's review log applied.

    The record the mechanical checks are run on and the report shows
    (decision 0010, rules 5 and 6).
    """
    return apply(draft, load(workspace / LOG)).record


def _reset(claim: Claim) -> Claim:
    """A claim whose structure changed: back to pending, its findings dropped."""
    return claim.model_copy(update={"trace": Trace.PENDING})


def _repoint(claims: list[Claim], old: str, new: tuple[str, ...]) -> list[Claim]:
    """Point other claims' dependencies on ``old`` at ``new``."""
    out = []
    for c in claims:
        if old in c.depends_on:
            deps = [d for d in c.depends_on if d != old]
            deps += [n for n in new if n not in deps and n != c.id]
            c = c.model_copy(update={"depends_on": tuple(deps)})
        out.append(c)
    return out


def apply(record: AuditRecord, entries: tuple[Entry, ...]) -> Applied:
    """Apply the log's structural entries to the draft, in order.

    Each entry is checked against its target as it stands after the entries
    before it. Edit, Split, and Merge reset the claims they touch to pending
    and drop their findings (rule 7); the old findings remain only in the
    log. Claims that depended on a split or merged claim are pointed at what
    replaced it. Confirm and Override change nothing here (overrides apply
    through :func:`current`). Entries on cross-claim findings, which are
    not in the record, are left to :func:`current_cross`.
    """
    applied, stale, refused = [], [], []
    retired: set[str] = set()
    for e in entries:
        if e.target_kind is Target.CROSS:
            continue
        claims, findings = list(record.claims), list(record.findings)
        by_id = {c.id: c for c in claims} | {f.id: f for f in findings}
        if e.operation is not Operation.ADD:
            target = by_id.get(e.target)
            if target is None or fingerprint(target) != e.fingerprint:
                stale.append(e)
                continue
        try:
            claims, findings = _apply_one(e, claims, findings, retired, by_id)
            kept = {c.id for c in claims}
            record = AuditRecord(
                drafted_by=record.drafted_by,
                claims=tuple(claims),
                findings=tuple(findings),
                context=tuple(x for x in record.context if x.claim_id in kept),
            )
        except ValidationError as err:
            refused.append((e, err.errors()[0]["msg"].removeprefix("Value error, ")))
            continue
        except ValueError as err:
            refused.append((e, str(err)))
            continue
        if e.operation in (Operation.REMOVE, Operation.SPLIT) and (
            e.target_kind is Target.CLAIM
        ):
            retired.add(e.target)
        retired.update(e.absorbs)
        applied.append(e)
    return Applied(
        record, tuple(applied), tuple(stale), tuple(refused), frozenset(retired)
    )


def _apply_one(
    e: Entry,
    claims: list[Claim],
    findings: list[Finding],
    retired: set[str],
    by_id: dict,
) -> tuple[list[Claim], list[Finding]]:
    op, on_claim = e.operation, e.target_kind is Target.CLAIM
    new_ids = [c.id for c in e.claims]
    if reused := [i for i in new_ids if i in retired or i in by_id]:
        raise ValueError(f"IDs are never reused: {', '.join(reused)}")
    if op in (Operation.CONFIRM, Operation.OVERRIDE):
        return claims, findings
    if not on_claim:
        assert e.finding is not None or op is Operation.REMOVE
        if op is Operation.REMOVE:
            findings = [f for f in findings if f.id != e.target]
        elif op is Operation.EDIT_TRACE:
            findings = [e.finding if f.id == e.target else f for f in findings]
        else:
            findings.append(e.finding)
        # A claim is traced exactly when it has findings
        with_findings = {f.claim_id for f in findings}
        claims = [
            c.model_copy(update={"trace": Trace.TRACED})
            if c.id in with_findings
            else (_reset(c) if c.trace is Trace.TRACED else c)
            for c in claims
        ]
        return claims, findings
    if op is Operation.ADD:
        return claims + [_reset(e.claims[0])], findings
    findings = [f for f in findings if f.claim_id != e.target]
    if op is Operation.EDIT:
        update = {k: v for k, v in (("type", e.type), ("anchor", e.anchor)) if v}
        claims = [
            _reset(c.model_copy(update=update)) if c.id == e.target else c
            for c in claims
        ]
    elif op is Operation.REMOVE:
        claims = [c for c in claims if c.id != e.target]
    elif op is Operation.SPLIT:
        i = next(k for k, c in enumerate(claims) if c.id == e.target)
        claims = claims[:i] + [_reset(c) for c in e.claims] + claims[i + 1 :]
        claims = _repoint(claims, e.target, tuple(new_ids))
    elif op is Operation.MERGE:
        if missing := [a for a in e.absorbs if a not in by_id]:
            raise ValueError(
                f"cannot merge claims not in the record: {', '.join(missing)}"
            )
        findings = [f for f in findings if f.claim_id not in e.absorbs]
        claims = [
            _reset(c) if c.id == e.target else c
            for c in claims
            if c.id not in e.absorbs
        ]
        for a in e.absorbs:
            claims = _repoint(claims, a, (e.target,))
    return claims, findings
