"""Calibrate synthetic difficulty: single-agent CoT accuracy vs n_ops.

    uv run python scripts/calibrate_synthetic.py [--n 30] [--levels 4 8 12 16 24 32] [--budget 8000]

Recipe per level (one knob): n_distractors = n_ops // 2, n_reverse = 1 if n_ops >= 8,
p_total = 0.2, shuffled. The CoT budget is deliberately generous so the curve measures
capability, not truncation. Output: runs/<ts>_calibrate_synthetic/ with traces and calibration.json.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, median

from dotenv import load_dotenv

from dialogic.llm import LLM, ResponseCache
from dialogic.trace import Tracer
from evals.baselines import Baselines
from evals.metrics import bootstrap_ci
from evals.synthetic import generate_set, standard_knobs as recipe

ROOT = Path(__file__).resolve().parent.parent


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=30)
    ap.add_argument("--levels", type=int, nargs="+", default=[4, 8, 12, 16, 24, 32])
    ap.add_argument("--budget", type=int, default=8000)
    ap.add_argument("--seed", type=int, default=1000)  # disjoint from the seeds used for frozen dev sets
    ap.add_argument("--concurrency", type=int, default=16)
    ap.add_argument("--model", default=None, help="defaults to $MODEL")
    ap.add_argument("--effort", default=None, help="reasoning_effort; omitted = API default")
    args = ap.parse_args()

    load_dotenv(ROOT / ".env")
    model = args.model or os.environ["MODEL"]
    run_id = f"{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}_calibrate_synthetic"
    run_dir = ROOT / "runs" / run_id

    problems = {lvl: generate_set(args.n, args.seed, **recipe(lvl)) for lvl in args.levels}
    with Tracer(run_dir, run_id) as tracer:
        llm = LLM(model, tracer=tracer, cache=ResponseCache(ROOT / "runs" / ".cache.sqlite"), concurrency=args.concurrency, seed=0, timeout_s=600,
                  reasoning_effort=args.effort)
        b = Baselines(llm, tracer=tracer, temperature=None)
        results = await b.run("cot", [p for ps in problems.values() for p in ps], budget=args.budget)

    reasoning = defaultdict(int)
    for line in (run_dir / "calls.jsonl").read_text().splitlines():
        c = json.loads(line)
        reasoning[c["problem_id"]] = c["reasoning_tokens"]

    by_id = {r.problem_id: r for r in results}
    table = []
    print(f"model={model}  effort={args.effort}  n={args.n}/level  budget={args.budget}\n")
    print(f"{'n_ops':>5} {'acc':>6} {'95% CI':>15} {'gen tok (med)':>14} {'reasoning (med)':>16} {'trunc':>5} {'no ans':>6} {'err':>4}")
    for lvl, ps in problems.items():
        rs = [by_id[p.id] for p in ps if p.id in by_id]
        acc = [float(r.correct) for r in rs]
        lo, hi = bootstrap_ci(acc)
        row = {
            "n_ops": lvl,
            "knobs": recipe(lvl),
            "n": len(rs),
            "errors": len(ps) - len(rs),
            "accuracy": mean(acc) if acc else None,
            "ci95": [lo, hi],
            "generated_tokens_median": median(r.tokens["generated"] for r in rs) if rs else None,
            "generated_tokens_mean": mean(r.tokens["generated"] for r in rs) if rs else None,
            "reasoning_tokens_median": median(reasoning[r.problem_id] for r in rs) if rs else None,
            "truncated": sum(r.truncated for r in rs),
            "no_answer": sum(r.final_answer is None for r in rs),
        }
        table.append(row)
        print(f"{lvl:>5} {row['accuracy']:>6.2f} [{lo:.2f}, {hi:.2f}]{'':>2} {row['generated_tokens_median']:>14.0f} "
              f"{row['reasoning_tokens_median']:>16.0f} {row['truncated']:>5} {row['no_answer']:>6} {row['errors']:>4}")

    out = {"run_id": run_id, "model": model, "reasoning_effort": args.effort, "n_per_level": args.n, "budget": args.budget, "seed": args.seed, "levels": table,
           "usage": llm.usage.snapshot()}
    (run_dir / "calibration.json").write_text(json.dumps(out, indent=2))
    print(f"\n{run_dir}/calibration.json")


if __name__ == "__main__":
    asyncio.run(main())
