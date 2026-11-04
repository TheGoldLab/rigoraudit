#!/bin/sh
# Rebuild the example audit from its materials, in order, and check it.
# Run from anywhere; the miragold repository's environment provides the tool.
set -e
cd "$(dirname "$0")/../.."
W=examples/example-audit
uv run miragold materials $W                  # step 1: every file, and what the code reads
uv run python $W/work/extract/extract.py        # step 2: pages and paragraphs
uv run python $W/derivations/values_trials.py   # step 4: recomputed values
uv run python $W/record/record.py               # step 5: the record
uv run miragold check $W                      # step 6: anchors and coverage
uv run miragold report $W                     # step 7: the report
