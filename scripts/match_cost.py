"""Match each baseline's mean cost per problem to the dialogue's (docs/PLAN_v2.md WS2/WS3).

    uv run python scripts/match_cost.py --target runs/<syn_dev200_dialogue> --runs runs/<calib_*> ... [--tolerance 0.02]

Cost = every API call priced from its run's config (prompt-cache reads/writes included), local-cache
replays priced as if called, averaged over the problems the run covers.

Per family, the measured settings are:
  self_consistency  first n draws of one run, for every n it drew (cost of draws 0..n-1)
  k_plus_judge      one run per k (the judge's cost depends on k)
  reasoning         one run per effort level
  any other method  one run per config (e.g. self-refine variants), keyed by run name
For each family, the two settings that bracket the target are mixed per problem
(evals/mixture.Mixture) with p_high solved so the expected cost equals the target.
Writes analysis/results/cost_matching.md and prints it.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from statistics import mean

import yaml

from evals.mixture import solve_p_high

ROOT = Path(__file__).resolve().parent.parent


def call_cost(c: dict, pricing: dict) -> float:
    rin = pricing["input_per_mtok"]
    read, write = c.get("prompt_cache_read_tokens", 0), c.get("prompt_cache_write_tokens", 0)
    return ((c["prompt_tokens"] - read - write) * rin + read * pricing.get("cache_read_per_mtok", rin)
            + write * pricing.get("cache_write_per_mtok", rin) + c["completion_tokens"] * pricing["output_per_mtok"]) / 1e6


def load_run(run: Path) -> tuple[dict, list[dict]]:
    cfg = yaml.safe_load((run / "config.yaml").read_text())
    calls = [json.loads(l) for l in (run / "calls.jsonl").read_text().splitlines()]
    return cfg, calls


def per_problem(calls: list[dict], pricing: dict, keep=lambda c: True) -> tuple[float, float, float]:
    """(mean cost, mean generated tokens, mean reasoning tokens) per problem over the calls kept."""
    cost, gen, rsn = defaultdict(float), defaultdict(int), defaultdict(int)
    for c in calls:
        if keep(c):
            cost[c["problem_id"]] += call_cost(c, pricing)
            gen[c["problem_id"]] += c["completion_tokens"]
            rsn[c["problem_id"]] += c.get("reasoning_tokens", 0)
    ids = list(cost)
    return mean(cost[i] for i in ids), mean(gen[i] for i in ids), mean(rsn[i] for i in ids)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", required=True)
    ap.add_argument("--runs", nargs="+", required=True)
    ap.add_argument("--tolerance", type=float, default=0.02)
    args = ap.parse_args()

    tcfg, tcalls = load_run(Path(args.target))
    target, tgen, _ = per_problem(tcalls, tcfg["pricing"])
    families: dict[str, list[tuple[str, float, float, float]]] = defaultdict(list)  # family -> (setting, cost, gen, reasoning)

    for run in map(Path, args.runs):
        cfg, calls = load_run(run)
        pricing = cfg["pricing"]
        bcfg = cfg.get("baselines", {})
        methods = sorted({c["method"] for c in calls})
        for m in methods:
            mine = [c for c in calls if c["method"] == m]
            if m == "self_consistency":
                n_max = 1 + max(c["sample_idx"] for c in mine)
                for n in range(1, n_max + 1):
                    families[m].append((f"n={n}", *per_problem(mine, pricing, lambda c, n=n: c["sample_idx"] < n)))
            elif m == "k_plus_judge":
                families[m].append((f"k={bcfg.get('judge_k')}", *per_problem(mine, pricing)))
            elif m == "reasoning":
                n_max = 1 + max(c["sample_idx"] for c in mine)
                for n in range(1, n_max + 1):  # a vote over the first n reasoning calls
                    label = f"effort={bcfg.get('reasoning_effort')}" + (f" n={n}" if n_max > 1 else "")
                    families[m].append((label, *per_problem(mine, pricing, lambda c, n=n: c["sample_idx"] < n)))
            else:
                families[m].append((cfg["name"], *per_problem(mine, pricing)))

    L = ["# Cost matching on the dev set (WS3)", "",
         f"Target: `{Path(args.target).name}` — **${target:.5f} per problem**, {tgen:.0f} generated tokens. "
         f"Tolerance ±{args.tolerance:.0%}.", ""]
    for fam, settings in families.items():
        settings = sorted(set(settings), key=lambda s: s[1])
        L += [f"## {fam}", "", "| setting | $/problem | ratio to dialogue | generated tokens | of which hidden reasoning |", "|---|---|---|---|---|"]
        L += [f"| {s} | {c:.5f} | {c / target:.3f} | {g:.0f} | {r:.0f} |" for s, c, g, r in settings]
        below = [s for s in settings if s[1] <= target]
        above = [s for s in settings if s[1] > target]
        if below and above:
            lo, hi = below[-1], above[0]
            p = solve_p_high(lo[1], hi[1], target)
            exp_cost = lo[1] + p * (hi[1] - lo[1])
            exp_gen = lo[2] + p * (hi[2] - lo[2])
            L += ["", f"**Match:** mixture low = `{lo[0]}`, high = `{hi[0]}`, p_high = **{p:.3f}** → expected "
                      f"${exp_cost:.5f} (ratio {exp_cost / target:.3f}), {exp_gen:.0f} generated tokens.", ""]
        else:
            nearest = min(settings, key=lambda s: abs(s[1] - target))
            ok = abs(nearest[1] / target - 1) <= args.tolerance
            side = "every setting is cheaper" if not above else "every setting is dearer"
            L += ["", f"**{'Within tolerance' if ok else 'No bracket'}:** {side} than the dialogue; nearest `{nearest[0]}` "
                      f"at ratio {nearest[1] / target:.3f}." + ("" if ok else " Measure another setting on the other side, "
                      "or report the gap."), ""]
    out = ROOT / "analysis" / "results" / "cost_matching.md"
    out.write_text("\n".join(L) + "\n")
    print(out.read_text())


if __name__ == "__main__":
    main()
