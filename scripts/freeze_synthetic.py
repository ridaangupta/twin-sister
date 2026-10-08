"""Freeze synthetic problem sets as committed jsonl files.

    uv run python scripts/freeze_synthetic.py test1200 ablation1200 sweep_dev sweep_test
    uv run python scripts/freeze_synthetic.py --list

Seed ranges are disjoint across every set, so no problem appears in two sets:
  dev 0-1 · calibration 1000+ · test400 2000-2001 · test1200 3000-3001 · ablation1200 4000-4001
  · sweep dev 5000+n_ops · sweep test 5100+n_ops · (model2 sets: 6000+ / 6100+, frozen after recalibration)
Problems are shuffled across levels (fixed seed) so any prefix is a mixed-difficulty sample.
An existing file is never overwritten unless --force is given: frozen means frozen.
"""

from __future__ import annotations

import argparse
import random
import sys
from pathlib import Path

from evals.datasets import ROOT, save_jsonl
from evals.synthetic import generate_set, standard_knobs

SWEEP_LEVELS = (8, 12, 16, 20, 24, 32)

# name -> (path, [(n_ops, count, seed), ...])
SETS: dict[str, tuple[str, list[tuple[int, int, int]]]] = {
    # Levels from the gpt-5.6-luna (reasoning_effort=none) calibration: ~87% and ~47% single-agent CoT.
    "dev200": ("evals/subsets/synthetic_dev200.jsonl", [(10, 100, 0), (16, 100, 1)]),
    "test400": ("evals/subsets/synthetic_test400.jsonl", [(10, 200, 2000), (16, 200, 2001)]),  # consumed 2026-10-07
    # PLAN_v2: WS4 confirmatory set and WS5 ablation set.
    "test1200": ("evals/subsets/synthetic_test1200.jsonl", [(10, 600, 3000), (16, 600, 3001)]),
    "ablation1200": ("evals/subsets/synthetic_ablation1200.jsonl", [(10, 600, 4000), (16, 600, 4001)]),
    # PLAN_v2: WS6a difficulty sweep.
    "sweep_dev": ("evals/subsets/synthetic_sweep_dev300.jsonl", [(n, 50, 5000 + n) for n in SWEEP_LEVELS]),
    "sweep_test": ("evals/subsets/synthetic_sweep_test1200.jsonl", [(n, 200, 5100 + n) for n in SWEEP_LEVELS]),
}


def freeze(name: str, force: bool = False) -> None:
    path, parts = SETS[name]
    if (ROOT / path).exists() and not force:
        print(f"{name}: {path} exists, left untouched (use --force to regenerate)")
        return
    problems = [p for n_ops, n, seed in parts for p in generate_set(n, seed, **standard_knobs(n_ops))]
    random.Random(0).shuffle(problems)
    save_jsonl(problems, path)
    print(f"{name}: wrote {len(problems)} problems to {path}; first 10 levels {[p.meta['n_ops'] for p in problems[:10]]}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("sets", nargs="*")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    if args.list or not args.sets:
        for k, (path, parts) in SETS.items():
            print(f"{k:13s} {path:48s} {sum(n for _, n, _ in parts):5d} problems  seeds {sorted({s for *_, s in parts})}")
        return
    unknown = set(args.sets) - set(SETS)
    if unknown:
        sys.exit(f"unknown set(s): {sorted(unknown)}")
    for name in args.sets:
        freeze(name, args.force)


if __name__ == "__main__":
    main()
