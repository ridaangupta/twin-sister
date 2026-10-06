"""Freeze synthetic problem sets as committed jsonl files.

Seed ranges are disjoint: calibration 1000+, dev 0-1, test 2000-2001.
Problems are shuffled across levels so any prefix is a mixed-difficulty sample.

    uv run python scripts/freeze_synthetic.py
"""

import random

from evals.datasets import save_jsonl
from evals.synthetic import generate_set, standard_knobs

SETS = {
    # Levels from the gpt-5.6-luna (reasoning_effort=none) calibration: ~87% and ~47% single-agent CoT.
    "evals/subsets/synthetic_dev200.jsonl": [(10, 100, 0), (16, 100, 1)],
    "evals/subsets/synthetic_test400.jsonl": [(10, 200, 2000), (16, 200, 2001)],
}

for path, parts in SETS.items():
    problems = [p for n_ops, n, seed in parts for p in generate_set(n, seed, **standard_knobs(n_ops))]
    random.Random(0).shuffle(problems)
    save_jsonl(problems, path)
    print(path, len(problems), "first 10 levels:", [p.meta["n_ops"] for p in problems[:10]])
