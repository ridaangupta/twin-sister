"""Sample sizes for paired accuracy comparisons (exact-McNemar designs), from discordance rates.

    uv run python scripts/power.py --discordance 0.16 --gaps 0.07 0.05 0.04 0.03 --family 4
    uv run python scripts/power.py --tost --discordance 0.085 --margin 0.03
    uv run python scripts/power.py --from-runs runs/<dialogue> runs/<baselines>   # observed rates

Superiority: normal approximation to McNemar (Connor 1987), two-sided, alpha split Bonferroni-style
across `--family` comparisons (the conservative bound for Holm's first step).
Equivalence (TOST): paired difference with true difference 0, margin +-m, variance ~ discordance.
"""

from __future__ import annotations

import argparse
import json
from math import ceil, sqrt
from pathlib import Path
from statistics import NormalDist

Z = NormalDist().inv_cdf


def n_superiority(p10: float, p01: float, alpha: float = 0.05, power: float = 0.8) -> int:
    pd, d = p10 + p01, p10 - p01
    if d <= 0:
        raise ValueError("the gap must be positive")
    return ceil((Z(1 - alpha / 2) * sqrt(pd) + Z(power) * sqrt(pd - d * d)) ** 2 / d**2)


def n_tost(discordance: float, margin: float, alpha: float = 0.05, power: float = 0.9) -> int:
    return ceil((Z(1 - alpha) + Z(1 - (1 - power) / 2)) ** 2 * discordance / margin**2)


def observed(dialogue_run: str, other_run: str) -> list[tuple[str, float, float, int]]:
    def rows(run: str) -> dict:
        out: dict = {}
        for r in map(json.loads, (Path(run) / "problems.jsonl").read_text().splitlines()):
            out.setdefault(r["method"], {})[r["problem_id"]] = r["correct"]
        return out

    d = rows(dialogue_run)["dialogue"]
    res = []
    for method, o in rows(other_run).items():
        ids = sorted(set(d) & set(o))
        p10 = sum(d[i] and not o[i] for i in ids) / len(ids)
        p01 = sum(o[i] and not d[i] for i in ids) / len(ids)
        res.append((method, p10, p01, len(ids)))
    return res


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--discordance", type=float, nargs="+", default=[0.16, 0.12, 0.09])
    ap.add_argument("--gaps", type=float, nargs="+", default=[0.07, 0.05, 0.04, 0.03])
    ap.add_argument("--family", type=int, default=1, help="number of comparisons sharing alpha")
    ap.add_argument("--alpha", type=float, default=0.05)
    ap.add_argument("--power", type=float, nargs="+", default=[0.8, 0.9])
    ap.add_argument("--tost", action="store_true")
    ap.add_argument("--margin", type=float, default=0.03)
    ap.add_argument("--from-runs", nargs=2, metavar=("DIALOGUE_RUN", "BASELINE_RUN"))
    args = ap.parse_args()

    if args.from_runs:
        print("observed discordance (dialogue-only rate p10, other-only rate p01):")
        for m, p10, p01, n in observed(*args.from_runs):
            print(f"  {m:20s} n={n:4d}  p10={p10:.3f}  p01={p01:.3f}  total={p10 + p01:.3f}  gap={p10 - p01:+.3f}")
        return
    a = args.alpha / args.family
    if args.tost:
        for pd in args.discordance:
            print(f"TOST margin ±{args.margin:.0%}, discordance {pd:.3f}: "
                  + ", ".join(f"{pw:.0%} power n={n_tost(pd, args.margin, args.alpha, pw)}" for pw in args.power))
        return
    print(f"superiority, two-sided, alpha {args.alpha} over a family of {args.family} (per-test {a:.4f})")
    for pd in args.discordance:
        for g in args.gaps:
            if g >= pd:
                continue
            ns = ", ".join(f"{pw:.0%}: n={n_superiority((pd + g) / 2, (pd - g) / 2, a, pw)}" for pw in args.power)
            print(f"  discordance {pd:.2f}, gap {g * 100:.0f} pts -> {ns}")


if __name__ == "__main__":
    main()
