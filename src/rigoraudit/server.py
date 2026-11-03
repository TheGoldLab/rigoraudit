# Copyright (c) 2026, Joshua I. Gold
# SPDX-License-Identifier: BSD-2-Clause
"""Local review server: the report with review actions on each claim and finding.

Serves the report page on 127.0.0.1 only (it contains unpublished
materials) and adds a small script with the review operations of decision
0010. The page marks up four things for it:

- ``data-finding-id`` on each finding: Confirm, Override, Edit trace,
  Remove. Edit trace lists the finding's evidence from the elements marked
  ``.ev`` inside it (with ``.stmt`` and ``.where``), in the record's order.
- ``data-claim-id`` (and optionally ``data-claim-type``) on each claim:
  Confirm, Edit, Split, Merge, Remove, Add finding.
- ``data-cross-id`` on each cross-claim finding in the list of them
  (``#cross``): Confirm, Override.
- ``data-section`` and ``data-paragraph`` on the element holding each
  manuscript paragraph's text, exactly as extracted. Selecting text there
  gives the quote for an Edit, the parts of a Split, or a new claim (Add).
  Anything added inside it that is not the paragraph's text (a claim's
  label) is marked ``data-not-text`` and left out when counting.

:mod:`rigoraudit.report` writes the page with all of these.

Each button opens a form in place; saving appends an entry to the review
log (``review/log.json``), writes the report again, and reloads the page.
Requests are checked against the reviewed record and refused, with the
reason shown, if they would not apply.
"""

from __future__ import annotations

import datetime
import json
import sys
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit

from pydantic import ValidationError

from rigoraudit import codeindex, crosscheck, review
from rigoraudit import report as report_page
from rigoraudit.paragraphs import PARAGRAPHS, Paragraph, read_paragraphs
from rigoraudit.schema import (
    RECORD,
    AuditRecord,
    Basis,
    Claim,
    ClaimType,
    CodeAnchor,
    CrossFinding,
    Drafter,
    DrafterKind,
    Effect,
    Facet,
    Finding,
    ManuscriptAnchor,
    Observation,
    Obtained,
    Source,
    Status,
)

MAX_BODY = 64 * 1024

SCRIPT = """
<style>
.rv-bar { display: flex; flex-wrap: wrap; gap: 6px; margin: 6px 0; }
.rv-btn { justify-self: start; font: 500 12px/1 var(--sans, sans-serif); padding: 5px 9px; border-radius: 5px;
  border: 1px solid var(--rule, #ccc); background: var(--panel, #fff); color: var(--ink, #111); cursor: pointer; }
.rv-btn[hidden], .rv-form[hidden], .rv-bar[hidden], .rv-add[hidden] { display: none; }
.rv-form { display: grid; gap: 8px; margin: 10px 0 4px; padding: 12px; border: 1px solid var(--rule, #ccc);
  border-radius: 6px; background: var(--soft, #f4f4f4); }
.rv-form label { display: grid; gap: 4px; font: 500 12px/1.2 var(--sans, sans-serif); color: var(--muted, #555); }
.rv-form select, .rv-form input, .rv-form textarea { font: 14px/1.4 var(--sans, sans-serif); padding: 6px 8px;
  border: 1px solid var(--rule, #ccc); border-radius: 4px; background: var(--panel, #fff); color: var(--ink, #111); }
.rv-form textarea { min-height: 64px; resize: vertical; }
.rv-quote { font-size: 13px; margin: 0; color: var(--ink, #111); }
.rv-part { display: grid; grid-template-columns: 8rem 12rem 1fr; gap: 6px; align-items: start; }
.rv-ev { display: grid; gap: 8px; border: 1px solid var(--rule, #ccc); border-radius: 6px; padding: 8px 10px; margin: 0; }
.rv-ev legend { font: 500 12px/1.2 var(--sans, sans-serif); color: var(--muted, #555); padding: 0 4px; }
.rv-lines { display: grid; grid-template-columns: minmax(0, 1fr) 6rem 6rem; gap: 6px; }
.rv-lines input { min-width: 0; width: 100%; box-sizing: border-box; }
.rv-lines[hidden], .rv-form [hidden] { display: none; }
.rv-evs { margin: 0; padding-left: 1.2rem; display: grid; gap: 4px; font-size: 13px; }
.rv-form label.rv-keep { display: flex; gap: 6px; align-items: baseline; font: 13px/1.4 var(--sans, sans-serif); color: var(--ink, #111); }
.rv-err { color: var(--dif, #a65d12); font-size: 13px; margin: 0; }
.rv-add { position: fixed; right: 16px; bottom: calc(16px + env(safe-area-inset-bottom, 0px)); z-index: 10;
  max-width: min(32rem, calc(100vw - 32px)); }
.rv-add .rv-form { margin: 0; box-shadow: 0 4px 16px rgb(0 0 0 / .15); }
</style>
<script>
(() => {
  const STATUSES = __STATUSES__;
  const TYPES = __TYPES__;
  const REVIEWER = __REVIEWER__;
  const FACETS = __FACETS__;
  const EFFECTS = __EFFECTS__;
  const esc = (t) => String(t).replace(/[&<>"]/g, (c) => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}[c]));
  const options = (pairs, chosen) => pairs.map(([v, l]) =>
    `<option value="${esc(v)}"${v === chosen ? " selected" : ""}>${esc(l)}</option>`).join("");
  const typeOptions = (chosen) => options(TYPES.map((t) => [t, t.replaceAll("_", " ")]), chosen);

  // A paragraph's text as extracted: its text nodes, less any inside [data-not-text] (claim labels).
  function textNodes(para) {
    const out = [], walk = document.createTreeWalker(para, NodeFilter.SHOW_TEXT);
    for (let n; (n = walk.nextNode());) if (!n.parentElement.closest("[data-not-text]")) out.push(n);
    return out;
  }
  // Where a point in the page falls in the paragraph's extracted text.
  function offsetIn(nodes, container, offset) {
    const point = document.createRange();
    point.setStart(container, offset);
    let total = 0;
    for (const n of nodes) {
      if (n === container) return total + offset;
      if (point.comparePoint(n, 0) > 0) break;  // n starts after the point
      total += n.length;
    }
    return total;
  }
  // The current selection as a span of one manuscript paragraph, or null.
  function selection() {
    const sel = getSelection();
    if (!sel || sel.isCollapsed || !sel.rangeCount) return null;
    const range = sel.getRangeAt(0);
    const start = range.startContainer.nodeType === 1 ? range.startContainer : range.startContainer.parentElement;
    const para = start && start.closest("[data-paragraph]");
    if (!para || !para.contains(range.endContainer)) return null;
    const nodes = textNodes(para), whole = nodes.map((n) => n.data).join("");
    const from = offsetIn(nodes, range.startContainer, range.startOffset);
    const to = offsetIn(nodes, range.endContainer, range.endOffset);
    if (to <= from) return null;
    return {section: para.dataset.section, paragraph: Number(para.dataset.paragraph),
            start: from, end: to, text: whole.slice(from, to)};
  }
  // Clicking a button can clear the selection, so keep the last one made in a paragraph.
  let lastSelection = null;
  document.addEventListener("selectionchange", () => {
    const s = selection();
    if (s) lastSelection = s;
    addPanel.hidden = !s && addForm.hidden;
  });
  const take = (what) => {
    if (!lastSelection) throw new Error(`Select the ${what} in a manuscript paragraph first.`);
    return lastSelection;
  };

  async function send(payload, err) {
    err.textContent = "Saving…";
    const res = await fetch("/api/review", {method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify(payload)});
    const out = await res.json().catch(() => ({error: res.statusText}));
    if (res.ok) { remember(); location.reload(); }
    else err.textContent = out.error || "Could not save.";
  }

  // A form with a reason and reviewer; collect(form) gives the operation's own fields.
  function makeForm(fields, reason, collect, base, onClose) {
    const form = document.createElement("form");
    form.className = "rv-form"; form.hidden = true;
    form.innerHTML = `${fields}
      <label>Reason <textarea name="reason" required>${esc(reason)}</textarea></label>
      <label>Reviewer <input name="reviewer" required></label>
      <div><button class="rv-btn" type="submit">Save</button>
        <button class="rv-btn" type="button" data-cancel>Cancel</button></div>
      <p class="rv-err" role="alert"></p>`;
    form.reviewer.value = REVIEWER;
    form.querySelector("[data-cancel]").addEventListener("click", () => { form.hidden = true; onClose(); });
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const err = form.querySelector(".rv-err");
      let extra;
      try { extra = collect(form); } catch (x) { err.textContent = x.message; return; }
      await send({...base(), reason: form.reason.value, reviewer: form.reviewer.value, ...extra}, err);
    });
    return form;
  }

  // A button in the item's bar that opens its form in place of the bar.
  function action(bar, host, label, op, kind, target, {fields = "", reason = "", collect = () => ({}), open} = {}) {
    const btn = document.createElement("button");
    btn.type = "button"; btn.className = "rv-btn"; btn.textContent = label;
    const form = makeForm(fields, reason, collect, () => ({operation: op, target_kind: kind, target}),
      () => { bar.hidden = false; btn.focus(); });
    btn.addEventListener("click", () => {
      bar.hidden = true; form.hidden = false;
      if (open) open(form);
      (form.querySelector("input:not([name=reviewer]), select, textarea") || form.reason).focus();
    });
    bar.append(btn); host.append(form);
  }
  const bar = (host) => { const b = document.createElement("div"); b.className = "rv-bar"; host.append(b); return b; };

  const quotePicker = (what) => `<div><button class="rv-btn" type="button" data-take>Use selected text</button>
    <p class="rv-quote" data-shown>No ${what} chosen.</p></div>`;
  function wirePicker(form, what) {
    form.querySelector("[data-take]").addEventListener("click", () => {
      try { form.picked = take(what); form.querySelector("[data-shown]").textContent = `“${form.picked.text}”`; }
      catch (x) { form.querySelector(".rv-err").textContent = x.message; }
    });
  }

  // New evidence for a finding: text selected in the manuscript, or lines of code.
  const EV_SOURCES = [["methods", "Methods"], ["results", "Results / legend"], ["code", "Code"]];
  const evidenceFields = `<fieldset class="rv-ev"><legend>Add evidence</legend>
      <label>Source <select name="ev-source">${options(EV_SOURCES)}</select></label>
      <div data-ev-ms>${quotePicker("passage")}</div>
      <div data-ev-code hidden class="rv-lines">
        <label>File, in the code <input name="ev-file" placeholder="analysis/fit.py"></label>
        <label>First line <input name="ev-from" type="number" min="1"></label>
        <label>Last line <input name="ev-to" type="number" min="1"></label></div>
      <label>What it states or does <textarea name="ev-statement"></textarea></label>
      <div><button class="rv-btn" type="button" data-ev-add>Add this evidence</button></div>
    </fieldset><ul class="rv-evs" data-ev-list></ul>`;
  function wireEvidence(f) {
    f.evidence = [];
    wirePicker(f, "passage");
    const src = f.querySelector("[name=ev-source]");
    const toggle = () => {
      f.querySelector("[data-ev-ms]").hidden = src.value === "code";
      f.querySelector("[data-ev-code]").hidden = src.value !== "code";
    };
    src.addEventListener("change", toggle); toggle();
    f.querySelector("[data-ev-add]").addEventListener("click", () => {
      const err = f.querySelector(".rv-err"), statement = f["ev-statement"].value.trim();
      const spec = {source: src.value, statement};
      if (!statement) { err.textContent = "Say what the evidence states or does."; return; }
      let where;
      if (src.value === "code") {
        spec.file = f["ev-file"].value.trim();
        spec.lines = [Number(f["ev-from"].value), Number(f["ev-to"].value || f["ev-from"].value)];
        if (!spec.file || !spec.lines[0]) { err.textContent = "Give the file and its lines."; return; }
        where = `${spec.file}:${spec.lines[0]}–${spec.lines[1]}`;
      } else {
        if (!f.picked) { err.textContent = "Select the passage in the manuscript first."; return; }
        spec.quote = f.picked; where = `“${f.picked.text}”`;
      }
      f.evidence.push(spec); err.textContent = "";
      const li = document.createElement("li");
      li.innerHTML = `<b>${esc(src.selectedOptions[0].text)}</b>: ${esc(statement)} <span class="rv-quote">${esc(where)}</span>
        <button class="rv-btn" type="button">Take out</button>`;
      li.querySelector("button").addEventListener("click", () => { f.evidence.splice(f.evidence.indexOf(spec), 1); li.remove(); });
      f.querySelector("[data-ev-list]").append(li);
      f["ev-statement"].value = ""; f.picked = null;
      f.querySelector("[data-shown]").textContent = "No passage chosen.";
    });
  }

  for (const el of document.querySelectorAll("[data-finding-id]")) {
    const id = el.dataset.findingId, b = bar(el);
    action(b, el, "Confirm…", "confirm", "finding", id,
      {reason: "Sources, code, and derivation are the right ones and the summary is fair."});
    action(b, el, "Override…", "override", "finding", id, {
      fields: `<label>Status you would give <select name="status">${options(STATUSES)}</select></label>`,
      collect: (f) => ({status: f.status.value})});
    // The finding's evidence as the page shows it, in the record's order
    const shown = [...el.querySelectorAll(".ev")].map((ev, i) => {
      const stmt = ev.querySelector(".stmt"), where = ev.querySelector(".where");
      return `<label class="rv-keep"><input type="checkbox" name="keep" value="${i}" checked>
        ${esc(stmt ? stmt.textContent : `Evidence ${i + 1}`)}${where ? ` <span class="rv-quote">${esc(where.textContent)}</span>` : ""}</label>`;
    }).join("");
    const summary = el.querySelector(".f-sum");
    action(b, el, "Edit trace…", "edit_trace", "finding", id, {
      fields: `<div><b>Evidence to keep</b>${shown || "<p class='rv-quote'>The page does not list this finding's evidence.</p>"}</div>
        ${evidenceFields}
        <label>Summary <textarea name="summary">${esc(summary ? summary.textContent : "")}</textarea></label>`,
      open: (f) => { if (!f.wired) { wireEvidence(f); f.wired = true; } },
      collect: (f) => ({keep: [...f.querySelectorAll("[name=keep]:checked")].map((x) => Number(x.value)),
                        add: f.evidence, summary: f.summary.value})});
    action(b, el, "Remove…", "remove", "finding", id);
  }

  for (const el of document.querySelectorAll("#cross [data-cross-id]")) {
    const id = el.dataset.crossId, b = bar(el);
    action(b, el, "Confirm…", "confirm", "cross", id,
      {reason: "The values are about the same thing, and the status is right."});
    action(b, el, "Override…", "override", "cross", id, {
      fields: `<label>Status you would give <select name="status">${options(STATUSES.filter(([v]) =>
        v === "consistent" || v === "differs"))}</select></label>`,
      collect: (f) => ({status: f.status.value})});
  }

  for (const el of document.querySelectorAll("[data-claim-id]")) {
    const id = el.dataset.claimId, type = el.dataset.claimType || TYPES[0], b = bar(el);
    action(b, el, "Confirm…", "confirm", "claim", id, {reason: "Boundaries and type are right."});
    action(b, el, "Edit…", "edit", "claim", id, {
      fields: `<label>Type <select name="type"><option value="">(unchanged)</option>${typeOptions()}</select></label>
        <label>New quote (optional)</label>${quotePicker("new quote")}`,
      open: (f) => { if (!f.wired) { wirePicker(f, "new quote"); f.wired = true; } },
      collect: (f) => {
        if (!f.type.value && !f.picked) throw new Error("Choose a new type, a new quote, or both.");
        return {type: f.type.value || null, quote: f.picked || null};
      }});
    action(b, el, "Split…", "split", "claim", id, {
      fields: `<div data-parts></div><div><button class="rv-btn" type="button" data-add-part>Add selected text as a part</button></div>`,
      open: (f) => {
        if (f.wired) return;
        f.wired = true; f.parts = [];
        f.querySelector("[data-add-part]").addEventListener("click", () => {
          try {
            const quote = take("part");
            f.parts.push(quote);
            const row = document.createElement("div");
            row.className = "rv-part";
            row.innerHTML = `<input name="part-id" value="${esc(id + f.parts.length)}" aria-label="ID">
              <select name="part-type" aria-label="Type">${typeOptions(type)}</select>
              <p class="rv-quote">“${esc(quote.text)}”</p>`;
            f.querySelector("[data-parts]").append(row);
          } catch (x) { f.querySelector(".rv-err").textContent = x.message; }
        });
      },
      collect: (f) => {
        if ((f.parts || []).length < 2) throw new Error("A split needs at least two parts.");
        const ids = [...f.querySelectorAll("[name=part-id]")], types = [...f.querySelectorAll("[name=part-type]")];
        return {parts: f.parts.map((quote, i) => ({id: ids[i].value.trim(), type: types[i].value, quote}))};
      }});
    action(b, el, "Merge…", "merge", "claim", id, {
      fields: `<label>Claims to fold into ${esc(id)} (IDs, comma-separated) <input name="absorbs" required></label>`,
      collect: (f) => ({absorbs: f.absorbs.value})});
    action(b, el, "Remove…", "remove", "claim", id);
    action(b, el, "Add finding…", "add", "finding", id, {
      fields: `<label>Facet <select name="facet"><option value="">whole claim</option>${options(FACETS.map((x) => [x, x]))}</select></label>
        <label>Part of the facet covered (optional) <input name="scope"></label>
        <label>Status <select name="status">${options(STATUSES)}</select></label>
        <p class="rv-quote" data-if="consistent differs">Compared by exact match. A comparison of numbers, or evidence from the data, goes in the record, where its derivation is named.</p>
        <div data-if="not_described"><b>Silent sources</b> ${["methods", "results", "code"].map((x) =>
          `<label class="rv-keep"><input type="checkbox" name="silent" value="${x}">${x}</label>`).join("")}</div>
        <label data-if="not_verifiable">Why it could not be checked <textarea name="why"></textarea></label>
        <label>Potential effect <select name="effect">${options(EFFECTS, "unknown")}</select></label>
        <label>Summary <textarea name="summary" required></textarea></label>
        ${evidenceFields}`,
      open: (f) => {
        if (f.wired) return;
        f.wired = true; wireEvidence(f);
        const show = () => f.querySelectorAll("[data-if]").forEach((x) => {
          x.hidden = !x.dataset.if.split(" ").includes(f.status.value); });
        f.status.addEventListener("change", show); show();
      },
      collect: (f) => {
        if (!f.evidence.length) throw new Error("Add at least one piece of evidence.");
        return {claim: id, facet: f.facet.value, scope: f.scope.value, status: f.status.value,
                silent: [...f.querySelectorAll("[name=silent]:checked")].map((x) => x.value),
                why: f.why.value, effect: f.effect.value, summary: f.summary.value, evidence: f.evidence};
      }});
  }

  // Adding a claim: select its text in a paragraph, then use the panel that appears.
  const addPanel = document.createElement("div");
  addPanel.className = "rv-add"; addPanel.hidden = true;
  const addBtn = document.createElement("button");
  addBtn.type = "button"; addBtn.className = "rv-btn"; addBtn.textContent = "Add claim from selection…";
  const addForm = makeForm(
    `<p class="rv-quote" data-shown></p><label>ID <input name="id" required></label>
     <label>Type <select name="type">${typeOptions()}</select></label>`,
    "", (f) => ({id: f.id.value.trim(), type: f.type.value, quote: f.picked}),
    () => ({operation: "add", target_kind: "claim", target: addForm.id.value.trim()}),
    () => { addBtn.hidden = false; addPanel.hidden = !selection(); });
  addBtn.addEventListener("click", () => {
    addForm.picked = lastSelection;
    addForm.querySelector("[data-shown]").textContent = `“${lastSelection.text}”`;
    addBtn.hidden = true; addForm.hidden = false; addForm.id.focus();
  });
  addPanel.append(addBtn, addForm);
  if (document.querySelector("[data-paragraph]")) document.body.append(addPanel);

  // Keep the reviewer's place across the reload: which sections and cards are open, and the scroll.
  function remember() {
    const open = {};
    for (const d of document.querySelectorAll("details[id]")) open[d.id] = d.open;
    try { sessionStorage.setItem("rv-view", JSON.stringify({open, y: scrollY})); } catch {}
  }
  let view = null;
  try { view = JSON.parse(sessionStorage.getItem("rv-view")); sessionStorage.removeItem("rv-view"); } catch {}
  if (view) {
    for (const [id, open] of Object.entries(view.open || {})) {
      const d = document.getElementById(id);
      if (d) d.open = open;
    }
    scrollTo(0, Number(view.y) || 0);
  }
})();
</script>
"""

STATUS_LABELS = {
    Status.CONSISTENT: "Consistent",
    Status.DIFFERS: "Differs",
    Status.NOT_DESCRIBED: "Not described",
    Status.NOT_VERIFIABLE: "Not verifiable",
}


class ReviewError(Exception):
    """A request that cannot be saved; the message is shown to the reviewer."""


def _text(payload: dict, key: str) -> str:
    return str(payload.get(key) or "").strip()


def _anchor(
    spec: object, file: str, paragraphs: dict[tuple[str, int], Paragraph]
) -> ManuscriptAnchor:
    """The anchor for a selection: ``{section, paragraph, start, end, text}``.

    The quote is taken from the extracted paragraph, and must equal the text
    the reviewer selected, so a page out of step with the extraction cannot
    save a wrong quote.
    """
    if not isinstance(spec, dict):
        raise ReviewError("Select the text in the manuscript first.")
    try:
        key = (str(spec["section"]), int(spec["paragraph"]))
        start, end = int(spec["start"]), int(spec["end"])
    except (KeyError, TypeError, ValueError) as e:
        raise ReviewError("Malformed selection.") from e
    p = paragraphs.get(key)
    if p is None:
        raise ReviewError(f"No extracted paragraph {key[0]} ¶{key[1]}.")
    quote = p.text[start:end]
    if not quote.strip() or quote != spec.get("text"):
        raise ReviewError(
            "The selection does not match the extracted paragraph; re-render the "
            "report and select again."
        )
    return ManuscriptAnchor(
        file=file, section=p.section, paragraph=p.number,
        char_start=start, char_end=end, page=p.page_at(start), quote=quote,
    )  # fmt: skip


@dataclass(frozen=True)
class _Sources:
    """What new evidence is read from: the manuscript and the code."""

    file: str | None
    """The manuscript, as the record's anchors name it."""
    paragraphs: dict[tuple[str, int], Paragraph]
    materials: Path | None
    commit: str | None
    """The commit the record's code anchors cite (the most common one)."""
    code_dirs: tuple[str, ...]
    """Folders in ``materials/`` that the record's code anchors start with."""

    @classmethod
    def of(
        cls,
        record: AuditRecord,
        paragraphs: dict[tuple[str, int], Paragraph],
        materials: Path | None,
    ) -> _Sources:
        code = [
            o.anchor
            for f in record.findings
            for o in f.observations
            if isinstance(o.anchor, CodeAnchor)
        ]
        commits = Counter(a.commit for a in code if a.commit)
        dirs = {PurePosixPath(a.file).parts[0] for a in code if "/" in a.file}
        return cls(
            file=next((c.anchor.file for c in record.claims), None),
            paragraphs=paragraphs,
            materials=materials,
            commit=commits.most_common(1)[0][0] if commits else None,
            code_dirs=tuple(sorted(dirs | {"code"})),
        )

    def code_anchor(self, spec: dict) -> CodeAnchor:
        """Lines of a code file, read from the local copy at the commit."""
        if self.materials is None:
            raise ReviewError("The code is not available to this page.")
        file = _text(spec, "file").lstrip("/")
        try:
            first, last = (int(n) for n in spec.get("lines") or ())
        except (TypeError, ValueError) as e:
            raise ReviewError(f"Give the first and last line of {file}.") from e
        if ".." in PurePosixPath(file).parts:
            raise ReviewError(f"{file} is outside the materials.")
        candidates = [file, *(f"{d}/{file}" for d in self.code_dirs)]
        found = next((c for c in candidates if (self.materials / c).is_file()), None)
        if found is None:
            raise ReviewError(f"No file {file} in the code.")
        path = self.materials / found
        lines = (
            codeindex.file_at_commit(path, self.commit)
            if self.commit
            else codeindex.read_lines(path)
        )
        if lines is None:
            raise ReviewError(f"{found} is not in commit {self.commit}.")
        if lines and lines[-1] == "":
            lines = lines[:-1]  # the end of the last line, not a line
        if not 1 <= first <= last <= len(lines):
            raise ReviewError(
                f"{found} has {len(lines)} lines; lines {first}–{last} are not in it."
            )
        quote = "\n".join(lines[first - 1 : last]).rstrip()
        if not quote.strip():
            raise ReviewError(f"Lines {first}–{last} of {found} are blank.")
        return CodeAnchor(
            file=found, line_start=first, line_end=last, commit=self.commit,
            quote=quote,
        )  # fmt: skip

    def observation(self, spec: object, drafter: Drafter) -> Observation:
        """New evidence: selected manuscript text, or lines of code."""
        if not isinstance(spec, dict):
            raise ReviewError("Malformed evidence.")
        statement = _text(spec, "statement")
        if not statement:
            raise ReviewError("Say what each piece of evidence states or does.")
        try:
            source = Source(spec.get("source"))
        except ValueError as e:
            raise ReviewError(
                "Evidence comes from Methods, Results, or the code."
            ) from e
        if source is Source.CODE:
            anchor, obtained = self.code_anchor(spec), Obtained.READ
        elif source in (Source.METHODS, Source.RESULTS):
            if self.file is None:
                raise ReviewError(
                    "The record has no claims to take the manuscript from."
                )
            anchor = _anchor(spec.get("quote"), self.file, self.paragraphs)
            obtained = Obtained.QUOTED
        else:
            raise ReviewError(
                "Data and output evidence names the derivation that produced it, "
                "so it is added in the record, not here."
            )
        return Observation(
            source=source, statement=statement, anchor=anchor, obtained=obtained,
            drafted_by=drafter,
        )  # fmt: skip


def _new_finding(
    payload: dict,
    current: AuditRecord,
    sources: _Sources,
    drafter: Drafter,
    retired: frozenset[str],
) -> Finding:
    """A finding a reviewer adds to a claim."""
    claim_id = _text(payload, "claim")
    if claim_id not in {c.id for c in current.claims}:
        raise ReviewError(f"No claim {claim_id!r} in the record.")
    facet = Facet(payload["facet"]) if payload.get("facet") else None
    status = Status(payload.get("status"))
    evidence = payload.get("evidence")
    if not isinstance(evidence, list) or not evidence:
        raise ReviewError("Add at least one piece of evidence.")
    taken = {f.id for f in current.findings} | retired
    stem = f"{claim_id}/{facet.value if facet else 'claim'}"
    fid = next(
        i
        for n in range(1, 1000)
        if (i := stem if n == 1 else f"{stem}-{n}") not in taken
    )
    compared = status in (Status.CONSISTENT, Status.DIFFERS)
    return Finding(
        id=fid,
        claim_id=claim_id,
        facet=facet,
        scope=_text(payload, "scope") or None,
        status=status,
        basis=Basis.EXACT if compared else None,
        summary=_text(payload, "summary"),
        observations=tuple(sources.observation(e, drafter) for e in evidence),
        not_described_in=tuple(Source(s) for s in payload.get("silent") or ())
        if status is Status.NOT_DESCRIBED
        else (),
        reason=_text(payload, "why") or None
        if status is Status.NOT_VERIFIABLE
        else None,
        effect=Effect(payload.get("effect") or Effect.UNKNOWN),
        drafted_by=drafter,
    )


def _retraced(
    payload: dict, finding: Finding, sources: _Sources, drafter: Drafter
) -> Finding:
    """A finding with the evidence the reviewer kept and added."""
    keep = payload.get("keep")
    if not isinstance(keep, list) or not all(isinstance(i, int) for i in keep):
        raise ReviewError("Malformed request.")
    if any(not 0 <= i < len(finding.observations) for i in keep):
        raise ReviewError("The page is out of step with the record; reload it.")
    added = payload.get("add") or []
    if not isinstance(added, list):
        raise ReviewError("Malformed request.")
    observations = tuple(finding.observations[i] for i in sorted(set(keep))) + tuple(
        sources.observation(e, drafter) for e in added
    )
    summary = _text(payload, "summary") or finding.summary
    if observations == finding.observations and summary == finding.summary:
        raise ReviewError("Nothing was changed: keep, remove, or add evidence.")
    data = finding.model_dump() | {"observations": observations, "summary": summary}
    return Finding.model_validate(data)


def save_entry(
    record_path: Path,
    log_path: Path,
    payload: dict,
    paragraphs: dict[tuple[str, int], Paragraph] | None = None,
    materials: Path | None = None,
    cross: Callable[[AuditRecord], tuple[CrossFinding, ...] | None] = lambda r: (),
) -> review.Entry:
    """Check a request against the reviewed record and append it to the log.

    The reviewer acts on the reviewed record (the draft with the log
    applied), so the entry's fingerprint is taken from it, and the entry is
    saved only if it applies cleanly there. ``cross`` gives a record's
    cross-claim findings.
    """
    draft = AuditRecord.model_validate_json(record_path.read_text())
    applied = review.apply(draft, review.load(log_path))
    current = applied.record
    reviewer, reason = _text(payload, "reviewer"), _text(payload, "reason")
    if not reviewer or not reason:
        raise ReviewError("A reason and a reviewer are both required.")
    try:
        op = review.Operation(payload.get("operation"))
        kind = review.Target(payload.get("target_kind"))
    except ValueError as e:
        raise ReviewError("Unknown review operation.") from e
    if op not in review.OPERATIONS_ON[kind]:
        raise ReviewError(f"{op} is not an operation on a {kind}.")
    target = _text(payload, "target")
    items = {c.id: c for c in current.claims} | {f.id: f for f in current.findings}
    fields: dict = {}
    if kind is review.Target.CROSS:
        found = {x.id: x for x in cross(current) or ()}
        if target not in found:
            raise ReviewError(f"No cross-claim finding {target!r} for this record.")
        fields["fingerprint"] = review.fingerprint(found[target])
    elif op is not review.Operation.ADD:
        item = items.get(target)
        if item is None or isinstance(item, Claim) != (kind is review.Target.CLAIM):
            raise ReviewError(f"No {kind} {target!r} in the record.")
        fields["fingerprint"] = review.fingerprint(item)
    today = datetime.date.today()
    drafter = Drafter(kind=DrafterKind.PERSON, name=reviewer, date=today)
    file = next((c.anchor.file for c in current.claims), None)
    sources = _Sources.of(current, paragraphs or {}, materials)
    try:
        if op is review.Operation.EDIT_TRACE:
            fields["finding"] = _retraced(payload, items[target], sources, drafter)
        elif op is review.Operation.ADD and kind is review.Target.FINDING:
            fields["finding"] = _new_finding(
                payload, current, sources, drafter, applied.retired
            )
            target = fields["finding"].id
        elif op is review.Operation.OVERRIDE:
            fields["status"] = Status(payload.get("status"))
        elif op is review.Operation.EDIT:
            if payload.get("type"):
                fields["type"] = ClaimType(payload["type"])
            if payload.get("quote") is not None:
                fields["anchor"] = _anchor(payload["quote"], file, paragraphs or {})
        elif op is review.Operation.MERGE:
            fields["absorbs"] = tuple(
                i.strip()
                for i in str(payload.get("absorbs") or "").split(",")
                if i.strip()
            )
        elif op in (review.Operation.SPLIT, review.Operation.ADD):
            if file is None:
                raise ReviewError(
                    "The record has no claims to take the manuscript from."
                )
            base = items[target] if op is review.Operation.SPLIT else None
            inherit = (
                base.model_dump(include={"depends_on", "citations", "restates"})
                if base else {}
            )  # fmt: skip
            parts = payload.get("parts") if base else [payload]
            if not isinstance(parts, list):
                raise ReviewError("Malformed request.")
            fields["claims"] = tuple(
                Claim(
                    id=_text(part, "id"),
                    type=ClaimType(part.get("type")),
                    anchor=_anchor(part.get("quote"), file, paragraphs or {}),
                    drafted_by=drafter,
                    **inherit,
                )
                for part in parts
                if isinstance(part, dict)
            )
            if op is review.Operation.ADD:
                target = fields["claims"][0].id if fields["claims"] else target
        entry = review.Entry(
            operation=op, target_kind=kind, target=target, reason=reason,
            reviewer=reviewer, date=today, **fields,
        )  # fmt: skip
    except ValidationError as e:
        raise ReviewError(e.errors()[0]["msg"].removeprefix("Value error, ")) from e
    except ValueError as e:
        raise ReviewError(str(e)) from e
    if refused := review.apply(current, (entry,)).refused:
        raise ReviewError(f"Not saved: {refused[0][1]}")
    review.add(log_path, entry)
    return entry


def make_handler(
    report_path: Path,
    record_path: Path,
    log_path: Path,
    rerender: Callable[[], None],
    reviewer: str,
    paragraphs_path: Path | None = None,
    materials: Path | None = None,
    cross: Callable[[AuditRecord], tuple[CrossFinding, ...] | None] = lambda r: (),
) -> type[BaseHTTPRequestHandler]:
    statuses = json.dumps([[s.value, label] for s, label in STATUS_LABELS.items()])
    types = json.dumps([t.value for t in ClaimType])
    facets = json.dumps([f.value for f in Facet])
    effects = json.dumps([[e.value, e.value.replace("_", " ")] for e in Effect])
    script = (
        SCRIPT.replace("__STATUSES__", statuses)
        .replace("__TYPES__", types)
        .replace("__FACETS__", facets)
        .replace("__EFFECTS__", effects)
        .replace("__REVIEWER__", json.dumps(reviewer))
    )

    def paragraphs() -> dict[tuple[str, int], Paragraph]:
        if paragraphs_path is None or not paragraphs_path.is_file():
            return {}
        return {(p.section, p.number): p for p in read_paragraphs(paragraphs_path)}

    class Handler(BaseHTTPRequestHandler):
        def _send(self, status: HTTPStatus, body: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, status: HTTPStatus, data: dict) -> None:
            self._send(status, json.dumps(data).encode(), "application/json")

        def do_GET(self) -> None:
            if urlsplit(self.path).path not in ("/", "/index.html"):
                self._send(HTTPStatus.NOT_FOUND, b"Not found", "text/plain")
                return
            page = report_path.read_text()
            if "</body>" in page:
                page = page.replace("</body>", script + "</body>", 1)
            else:
                page += script
            self._send(HTTPStatus.OK, page.encode(), "text/html; charset=utf-8")

        def do_POST(self) -> None:
            if self.path != "/api/review":
                self._json(HTTPStatus.NOT_FOUND, {"error": "Not found"})
                return
            length = int(self.headers.get("Content-Length") or 0)
            if not 0 < length <= MAX_BODY:
                self._json(
                    HTTPStatus.BAD_REQUEST, {"error": "Empty or oversized request."}
                )
                return
            try:
                payload = json.loads(self.rfile.read(length))
                if not isinstance(payload, dict):
                    raise ReviewError("Malformed request.")
                entry = save_entry(
                    record_path, log_path, payload, paragraphs(), materials, cross
                )
                rerender()
            except json.JSONDecodeError:
                self._json(HTTPStatus.BAD_REQUEST, {"error": "Malformed request."})
            except ReviewError as e:
                self._json(HTTPStatus.BAD_REQUEST, {"error": str(e)})
            except (OSError, ValueError) as e:
                self._json(
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                    {"error": f"Saved, but writing the report failed: {e}"},
                )
            else:
                self._json(HTTPStatus.OK, entry.model_dump(mode="json"))

        def log_message(self, format: str, *args) -> None:
            sys.stderr.write(f"review: {format % args}\n")

    return Handler


def serve(workspace: Path, reviewer: str = "", port: int = 8765) -> None:
    """Write the workspace's report and serve it for review until interrupted."""
    workspace = workspace.resolve()
    log_path = workspace / review.LOG
    page = report_page.write(workspace)
    handler = make_handler(
        page,
        workspace / RECORD,
        log_path,
        lambda: report_page.write(workspace),
        reviewer,
        workspace / PARAGRAPHS,
        workspace / "materials",
        lambda record: crosscheck.current(workspace, record),
    )
    server = ThreadingHTTPServer(("127.0.0.1", port), handler)
    print(
        f"Open http://127.0.0.1:{port}/ in a browser to review {workspace.name}. "
        "Press Ctrl-C here to stop."
    )
    print(f"Each review action is saved to {review.LOG}.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
