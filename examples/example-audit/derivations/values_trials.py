"""Recompute the trial counts and accuracies the Results state (step 6).

Reads the raw trials and writes every value the record cites, with the
checksums of this script and its input, to output/values/trials.json.
miragold.verify reads the values back by key and reports them as stale if
this script or the data change.

Accuracy is recomputed as the Methods describe it: trials with response
times longer than 2 s are excluded. The authors' code uses 2.5 s, so
accuracy is also computed with that cutoff, to show whether the difference
changes the values reported. The count of trials is of all trials in the
data, with none excluded.

    uv run python examples/example-audit/derivations/values_trials.py
"""

import json
from pathlib import Path

from miragold.values import write_values

HERE = Path(__file__).parent
WORKSPACE = HERE.parent
DATA = WORKSPACE / "materials" / "data" / "trials.json"
METHODS_CUTOFF_S, CODE_CUTOFF_S = 2.0, 2.5

trials = json.loads(DATA.read_text())


def accuracy(session: int, cutoff: float) -> float:
    s = [t for t in trials if t["session"] == session and t["rt"] <= cutoff]
    return 100 * sum(t["correct"] for t in s) / len(s)


values = {
    "trials": {
        "all": len(trials),
        "excluded_methods_cutoff": sum(t["rt"] > METHODS_CUTOFF_S for t in trials),
    },
    "mice": len({t["mouse"] for t in trials}),
    "sessions": len({t["session"] for t in trials}),
    "accuracy_pct": {f"session_{s}": accuracy(s, METHODS_CUTOFF_S) for s in (1, 10)},
    "accuracy_pct_code_cutoff": {
        f"session_{s}": accuracy(s, CODE_CUTOFF_S) for s in (1, 10)
    },
}
write_values(
    HERE / "output" / "values" / "trials.json",
    values,
    script=Path(__file__),
    inputs=[DATA],
    workspace=WORKSPACE,
)
print(json.dumps(values, indent=1))
