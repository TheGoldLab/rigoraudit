# 0003 — Output must be human-readable and anchored to the manuscript

**Status:** accepted (2026-10-27)

## Decision

- The manuscript is the navigational backbone of the report: claims are
  marked in place with stable IDs and open to a claim card.
- Claim cards follow a fixed template (quoted claim, type, facet × source
  table, differences with quoted evidence and locations).
- Output is layered (summary → cards → raw evidence); consistent claims are
  collapsed but present.
- A finding cannot be created without a manuscript anchor and quoted evidence
  from every source it involves. This is enforced in the schema.
- Machine-facing JSON in `work/` is canonical; reports are rendered from it.

## Why

Large volumes of opaque output are useless. Readers must be able to go from
any sentence of the manuscript to exactly what was checked and why, and verify
each finding themselves in seconds.
