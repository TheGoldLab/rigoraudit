# 0001 — Tool and audit workspaces are separate; materials kept as received

**Status:** accepted (2026-10-27)

## Decision

- The tool is an installable package in this repository. Each audit is a
  separate workspace directory at a location the user chooses.
- Manuscript materials are stored in `materials/` exactly as received and are
  never modified. Large or externally hosted data may be referenced by
  pointer plus checksum instead of copied.
- Heterogeneity is handled by a manifest (`audit.yaml`) that maps materials
  onto roles and records versions and gaps, not by reorganizing files.
- An inventory stage drafts the manifest; a human confirms it.

## Why

Materials arrive in many forms (PDF/LaTeX/Word; MATLAB/R/Python/notebooks;
local or repository-hosted data, or none). Reorganizing them is fragile and
loses information, and every finding must point back to the authors' actual
files. Keeping audits outside the tool repo prevents manuscript materials from
being committed by accident.

## Notes

- 2026-10-31: The layout inside a workspace is fixed, so the tool finds
  every file without options: the manifest (`audit.yaml`), `materials/`,
  `work/` (the tool's step outputs and the checks' results), `derivations/`,
  `record/` (the record, the script that builds it, and the coverage
  exclusions; earlier `gold/`, from when every record was built by hand),
  `review/`, `report/`, and `notes/`. The manifest also says which sections
  are audited (`settings: scope`), and the checksums it lists are the ones
  `miragold check` compares data files against.
