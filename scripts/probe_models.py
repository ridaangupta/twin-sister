"""Compare candidate (model, reasoning_effort) configs on single-agent CoT over the same dev problems.

    uv run python scripts/probe_models.py --n 40 gpt-5.6-luna:none gpt-5.6-luna:low gpt-4.1-mini

`model` alone means the API default effort (or a non-reasoning model). Results print per difficulty
level with visible vs hidden-reasoning token use; traces go to runs/<ts>_probe_models/.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, median

from dotenv import load_dotenv

from dialogic.llm import LLM, ResponseCache
from dialogic.trace import Tracer
from evals.baselines import Baselines
from evals.datasets import load_jsonl
from evals.metrics import bootstrap_ci

ROOT = Path(__file__).resolve().parent.parent


async def probe(spec: str, problems, budget: int, run_dir: Path, concurrency: int) -> dict:
    model, _, effort = spec.partition(":")
    sub = run_dir / spec.replace(":", "_")
    with Tracer(sub, f"{run_dir.name}/{spec}") as tracer:
        llm = LLM(model, tracer=tracer, cache=ResponseCache(ROOT / "runs" / ".cache.sqlite"), concurrency=concurrency,
                  seed=0, reasoning_effort=effort or None, timeout_s=600)
        results = await Baselines(llm, tracer=tracer, temperature=None).run("cot", problems, budget=budget)
    calls = {c["problem_id"]: c for c in map(json.loads, (sub / "calls.jsonl").read_text().splitlines())}

    by_level = defaultdict(list)
    for r in results:
        by_level[next(p.meta["n_ops"] for p in problems if p.id == r.problem_id)].append(r)
    out = {"spec": spec, "errors": len(problems) - len(results), "levels": {}}
    for lvl, rs in sorted(by_level.items()):
        acc = [float(r.correct) for r in rs]
        cs = [calls[r.problem_id] for r in rs]
        out["levels"][lvl] = {
            "n": len(rs),
            "accuracy": mean(acc),
            "ci95": bootstrap_ci(acc),
            "visible_tokens_median": median(c["completion_tokens"] - c["reasoning_tokens"] for c in cs),
            "reasoning_tokens_median": median(c["reasoning_tokens"] for c in cs),
            "latency_median_s": median(c["latency_s"] for c in cs),
            "truncated": sum(r.truncated for r in rs),
            "no_answer": sum(r.final_answer is None for r in rs),
        }
    out["usage"] = llm.usage.total().__dict__
    return out


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("specs", nargs="+")
    ap.add_argument("--n", type=int, default=40)
    ap.add_argument("--budget", type=int, default=16000)
    ap.add_argument("--set", default="evals/subsets/synthetic_dev200.jsonl")
    ap.add_argument("--concurrency", type=int, default=16)
    args = ap.parse_args()

    load_dotenv(ROOT / ".env")
    problems = load_jsonl(args.set)[: args.n]
    run_dir = ROOT / "runs" / f"{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}_probe_models"
    outs = await asyncio.gather(*(probe(s, problems, args.budget, run_dir, args.concurrency) for s in args.specs))

    print(f"{len(problems)} problems from {args.set}, CoT budget {args.budget}\n")
    print(f"{'config':24} {'ops':>3} {'n':>3} {'acc':>5} {'95% CI':>13} {'visible':>8} {'hidden':>7} {'lat s':>6} {'trunc':>5} {'noans':>5}")
    for o in outs:
        for lvl, r in o["levels"].items():
            lo, hi = r["ci95"]
            print(f"{o['spec']:24} {lvl:>3} {r['n']:>3} {r['accuracy']:>5.2f} [{lo:.2f}, {hi:.2f}] {r['visible_tokens_median']:>8.0f} "
                  f"{r['reasoning_tokens_median']:>7.0f} {r['latency_median_s']:>6.1f} {r['truncated']:>5} {r['no_answer']:>5}")
        if o["errors"]:
            print(f"{o['spec']:24} {o['errors']} failed calls (see errors.jsonl)")
    (run_dir / "probe.json").write_text(json.dumps(outs, indent=2, default=str))
    print(f"\n{run_dir}/probe.json")


if __name__ == "__main__":
    asyncio.run(main())
