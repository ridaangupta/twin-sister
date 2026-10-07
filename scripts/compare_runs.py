"""Compare methods across run directories on the problems they share.

    uv run python scripts/compare_runs.py runs/<dialogue> runs/<baselines> [runs/<ablation> ...] --ref dialogue

Each method is labelled by its run's config name when a run has a single method (so ablations
stay distinct), else by method name. Prints accuracy by level, paired tests against --ref
(exact McNemar + bootstrap CI of the accuracy difference), opening-agreement outcomes for
dialogue runs, tokens, and cost per problem with API prompt-cache pricing from each run's config.
"""

from __future__ import annotations

import argparse
import json
import random
from collections import Counter, defaultdict
from math import comb
from pathlib import Path
from statistics import mean

import yaml

from evals.datasets import load


def mcnemar_p(b: int, c: int) -> float:
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    return min(1.0, 2 * sum(comb(n, j) for j in range(k + 1)) / 2**n)


def paired_ci(diffs: list[float], n_boot: int = 5000, seed: int = 0) -> tuple[float, float]:
    rng = random.Random(seed)
    means = sorted(mean(rng.choices(diffs, k=len(diffs))) for _ in range(n_boot))
    return means[int(0.025 * n_boot)], means[int(0.975 * n_boot) - 1]


def call_cost(c: dict, pricing: dict | None) -> float:
    if not pricing:
        return float("nan")
    rin = pricing["input_per_mtok"]
    read, write = c.get("prompt_cache_read_tokens", 0), c.get("prompt_cache_write_tokens", 0)
    return ((c["prompt_tokens"] - read - write) * rin + read * pricing.get("cache_read_per_mtok", rin)
            + write * pricing.get("cache_write_per_mtok", rin) + c["completion_tokens"] * pricing["output_per_mtok"]) / 1e6


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("runs", nargs="+")
    ap.add_argument("--ref", default="dialogue", help="label to compare everything against")
    args = ap.parse_args()

    rows: dict[str, dict[str, dict]] = defaultdict(dict)
    costs: dict[str, float] = {}
    level: dict[str, int] = {}
    for run in map(Path, args.runs):
        cfg = yaml.safe_load((run / "config.yaml").read_text())
        meta = json.loads((run / "meta.json").read_text())
        resolved = meta["resolved_config"]
        level.update({p.id: p.meta.get("n_ops") for p in load(resolved["dataset"])})
        probs = [json.loads(l) for l in (run / "problems.jsonl").read_text().splitlines()]
        methods = {r["method"] for r in probs}
        label = (lambda m: cfg["name"]) if len(methods) == 1 and cfg["method"] == "dialogue" else (lambda m: m)
        for r in probs:
            rows[label(r["method"])][r["problem_id"]] = r
        per_method = defaultdict(float)
        for c in map(json.loads, (run / "calls.jsonl").read_text().splitlines()):
            per_method[label(c["method"])] += call_cost(c, cfg.get("pricing"))
        for m, total in per_method.items():
            costs[m] = total / max(len(rows[m]), 1)

    labels = list(rows)
    if args.ref not in rows:
        args.ref = next(l for l in labels if l.startswith("syn") or l == "dialogue")
    shared = sorted(set.intersection(*(set(rows[l]) for l in labels)))
    levels = sorted({level[i] for i in shared})
    print(f"{len(shared)} problems shared by all runs; reference = {args.ref}\n")

    head = f"{'method':28} {'all':>6}" + "".join(f" {f'{L} steps':>9}" for L in levels) + f" {'gen tok':>8} {'$/problem':>10}"
    print(head)
    for l in labels:
        acc = mean(rows[l][i]["correct"] for i in shared)
        by = "".join(f" {mean(rows[l][i]['correct'] for i in shared if level[i] == L):>9.3f}" for L in levels)
        gen = mean(rows[l][i]["tokens"]["generated"] for i in shared)
        print(f"{l:28} {acc:>6.3f}{by} {gen:>8.0f} {costs.get(l, float('nan')):>10.5f}")

    print(f"\npaired vs {args.ref}:")
    for l in labels:
        if l == args.ref:
            continue
        for scope in ["all"] + levels:
            ids = [i for i in shared if scope == "all" or level[i] == scope]
            ref_only = sum(rows[args.ref][i]["correct"] and not rows[l][i]["correct"] for i in ids)
            other_only = sum(rows[l][i]["correct"] and not rows[args.ref][i]["correct"] for i in ids)
            diffs = [float(rows[args.ref][i]["correct"]) - float(rows[l][i]["correct"]) for i in ids]
            lo, hi = paired_ci(diffs)
            print(f"  {args.ref} - {l:26} [{str(scope):>3}] diff {mean(diffs):+.3f} CI95 [{lo:+.3f}, {hi:+.3f}]  "
                  f"ref-only {ref_only:3d}  other-only {other_only:3d}  McNemar p={mcnemar_p(ref_only, other_only):.4f}")

    for l in labels:
        sample = rows[l][shared[0]]
        if sample.get("method") != "dialogue":
            continue
        cats: Counter = Counter()
        for i in shared:
            r = rows[l][i]
            traj = r["answer_trajectory"]
            opening = traj[min(1, len(traj) - 1)]
            right = sum(opening.get(a) == r["gold"] for a in ("A", "B"))
            cats[(["neither", "one", "both"][right], r["correct"])] += 1
        print(f"\n{l}: outcome by opening posts (after turn 1)")
        for k in ("both", "one", "neither"):
            n = cats[(k, True)] + cats[(k, False)]
            if n:
                print(f"  {k:8} opening(s) right: {n:3d} problems, final correct {cats[(k, True)]:3d} ({cats[(k, True)] / n:.0%})")
        stops = Counter(rows[l][i]["stop_reason"] for i in shared)
        print(f"  stop reasons {dict(stops)}; mean turns {mean(rows[l][i]['turns'] for i in shared):.2f}")


if __name__ == "__main__":
    main()
