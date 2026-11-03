# Copyright (c) 2026, Joshua I. Gold
# SPDX-License-Identifier: BSD-2-Clause
"""Make the made-up trial data for the example audit.

The example workspace treats ``materials/data/trials.json`` as data received
from authors. It was made by this script, which is kept outside the
workspace so the workspace holds only what an audit would receive. Rerunning
it with the same seed rewrites the same file.

    uv run python examples/make_example_data.py
"""

import json
import random
from pathlib import Path

OUT = Path(__file__).parent / "example-audit" / "materials" / "data" / "trials.json"
MICE, SESSIONS, TRIALS_PER_SESSION = 12, 10, 30
MISSING = 60
"""Trials dropped at random, so the data hold fewer trials than the paper states."""


def make(seed: int = 7) -> list[dict]:
    """Trials with accuracy rising from about 60% to 85% over sessions."""
    rng = random.Random(seed)
    trials = []
    for mouse in range(1, MICE + 1):
        for session in range(1, SESSIONS + 1):
            p_correct = 0.60 + 0.25 * (session - 1) / (SESSIONS - 1)
            for _ in range(TRIALS_PER_SESSION):
                trials.append({
                    "mouse": mouse,
                    "session": session,
                    "tone_khz": rng.choice([4, 8]),
                    "correct": int(rng.random() < p_correct),
                    "rt": round(rng.lognormvariate(-0.2, 0.45), 3),
                })  # fmt: skip
    for i in sorted(rng.sample(range(len(trials)), MISSING), reverse=True):
        del trials[i]
    return trials


if __name__ == "__main__":
    OUT.parent.mkdir(parents=True, exist_ok=True)
    rows = make()
    OUT.write_text("[\n" + ",\n".join(json.dumps(t) for t in rows) + "\n]\n")
    print(f"{len(rows)} trials -> {OUT}")
