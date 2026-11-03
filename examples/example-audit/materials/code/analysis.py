"""Accuracy by session for the tone discrimination task."""

import json

with open("data/trials.json") as f:
    trials = json.load(f)

# Exclude slow responses
trials = [t for t in trials if t["rt"] <= 2.5]

for session in range(1, 11):
    s = [t for t in trials if t["session"] == session]
    print(session, round(100 * sum(t["correct"] for t in s) / len(s), 1))
