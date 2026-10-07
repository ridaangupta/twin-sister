"""Experiment runner: one YAML config -> one run directory.

    uv run python -m dialogic.run configs/gsm8k_dev50_dialogue.yaml
    uv run python -m dialogic.run configs/gsm8k_dev50_baselines.yaml --match runs/<dialogue_run_id>

Run dir: config.yaml, meta.json, calls/prompts/turns/decisions/problems/errors.jsonl,
results.csv, summary.json.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import os
import platform
import re
import subprocess
import sys
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path
from statistics import mean
from typing import Any, Mapping

import yaml
from dotenv import load_dotenv

from dialogic.llm import LLM
from dialogic.orchestrator import DialogueRunner
from dialogic.trace import Tracer, utc_now
from evals import datasets
from evals.baselines import run_baselines
from evals.metrics import cost_usd, summarize

ROOT = Path(__file__).resolve().parent.parent
RUNS = ROOT / "runs"
_VAR = re.compile(r"\$\{(\w+)\}")


# ------------------------------------------------------------------ config


def _expand(obj: Any) -> Any:
    """Substitute ${VAR} from the environment; unset variables are an error."""
    if isinstance(obj, str):
        def sub(m: re.Match) -> str:
            if m.group(1) not in os.environ or not os.environ[m.group(1)]:
                raise SystemExit(f"config needs environment variable {m.group(1)} (set it in .env)")
            return os.environ[m.group(1)]
        return _VAR.sub(sub, obj)
    if isinstance(obj, dict):
        return {k: _expand(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_expand(v) for v in obj]
    return obj


def load_config(path: str | Path) -> tuple[dict[str, Any], str]:
    raw = Path(path).read_text()
    cfg = _expand(yaml.safe_load(raw))
    for key in ("name", "method", "model", "dataset"):
        if not cfg.get(key):
            raise SystemExit(f"config is missing {key!r}")
    if cfg["method"] not in ("dialogue", "baselines"):
        raise SystemExit("method must be 'dialogue' or 'baselines'")
    return cfg, raw


def git_info() -> dict[str, Any]:
    def git(*args: str) -> str:
        return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True).stdout.strip()

    return {"git_hash": git("rev-parse", "HEAD") or None, "git_dirty": bool(git("status", "--porcelain", "--untracked-files=no"))}


# ------------------------------------------------------------------ matching


def matched_budget(match_dir: str | Path, problem_ids: list[str]) -> tuple[int, dict[str, Any]]:
    """Mean generated tokens per problem in a dialogue run, over the problems both runs share."""
    rows = [json.loads(l) for l in (Path(match_dir) / "problems.jsonl").read_text().splitlines()]
    rows = [r for r in rows if r.get("method") == "dialogue"]
    wanted = set(problem_ids)
    shared = [r for r in rows if r["problem_id"] in wanted]
    if not shared:
        raise SystemExit(f"{match_dir} has no dialogue rows for these problems")
    b = round(mean(r["tokens"]["generated"] for r in shared))
    return b, {"matched_run": str(match_dir), "matched_problems": len(shared), "missing_in_match": len(wanted) - len(shared)}


# ------------------------------------------------------------------ outputs

_SKIP = {"final_text", "answer_trajectory", "agreement_trajectory", "sample_answers", "extra"}


def flat(row: Mapping[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in row.items():
        if k in _SKIP:
            continue
        if isinstance(v, Mapping):
            out.update({f"{k}_{kk}": vv for kk, vv in v.items()})
        elif isinstance(v, (list, tuple)):
            continue
        else:
            out[k] = v
    return out


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    rows = [flat(r) for r in rows]
    cols: list[str] = []
    for r in rows:
        cols += [c for c in r if c not in cols]
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)


# ------------------------------------------------------------------ main


async def run(cfg: dict[str, Any], raw_cfg: str, match: str | None = None, *, runs_dir: Path = RUNS, llm: Any = None) -> Path:
    problems = datasets.load(cfg["dataset"])
    if datasets.is_full_split(cfg["dataset"]) and not cfg.get("final_run"):
        raise SystemExit("refusing to run the full split without final_run: true (use the dev subset)")

    run_id = f"{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}_{cfg['name']}"
    run_dir = Path(runs_dir) / run_id
    run_dir.mkdir(parents=True)
    (run_dir / "config.yaml").write_text(raw_cfg)
    meta: dict[str, Any] = {
        "run_id": run_id,
        "name": cfg["name"],
        "method": cfg["method"],
        "model": cfg["model"],
        "seed": cfg.get("seed"),
        "n_problems": len(problems),
        "started_at": utc_now(),
        **git_info(),
        "python": platform.python_version(),
        "openai": version("openai"),
        "resolved_config": cfg,
    }

    with Tracer(run_dir, run_id) as tracer:
        if llm is None:
            llm = LLM.from_config(cfg, tracer, cache_path=Path(runs_dir) / ".cache.sqlite")
        if cfg["method"] == "dialogue":
            results = {"dialogue": [r.row() for r in await DialogueRunner.from_config(cfg, llm, tracer).run_all(problems)]}
        else:
            if match:
                budget, match_info = matched_budget(match, [p.id for p in problems])
            elif cfg.get("baselines", {}).get("budget"):
                budget, match_info = int(cfg["baselines"]["budget"]), {"matched_run": None}
            else:
                raise SystemExit("baselines need --match <dialogue run dir> or baselines.budget in the config")
            meta.update(match_info)
            raw, info = await run_baselines(cfg, problems, budget, llm, tracer)
            meta["baselines"] = info
            results = {m: [r.row() for r in rs] for m, rs in raw.items()}

    pricing = cfg.get("pricing")
    total = llm.usage.total()
    summary = {
        "run_id": run_id,
        "model": cfg["model"],
        "methods": {m: summarize(rows) for m, rows in results.items()},
        "errors": len(problems) * len(results) - sum(len(rs) for rs in results.values()),
        "usage": llm.usage.snapshot(),
        # billed: excludes local-cache hits, prices API prompt-cache reads/writes at their rates
        "cost_usd_billed": cost_usd(total.billed_prompt_tokens, total.billed_completion_tokens, pricing,
                                    cache_read_tokens=total.billed_prompt_cache_read_tokens,
                                    cache_write_tokens=total.billed_prompt_cache_write_tokens),
        # what the whole run would cost from scratch with no prompt caching at all
        "cost_usd_no_prompt_cache": cost_usd(total.prompt_tokens, total.completion_tokens, pricing),
    }
    meta["finished_at"] = utc_now()
    (run_dir / "meta.json").write_text(json.dumps(meta, indent=2, default=str))
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2, default=str))
    write_csv(run_dir / "results.csv", [r for rs in results.values() for r in rs])

    print(f"run: {run_dir}")
    for m, s in summary["methods"].items():
        lo, hi = s["accuracy_ci95"]
        print(f"  {m:17s} acc={s['accuracy']:.3f} [{lo:.3f}, {hi:.3f}]  n={s['n']}  generated/problem={s['tokens_mean'].get('generated')}")
    if summary["errors"]:
        print(f"  {summary['errors']} problem(s) failed; see errors.jsonl")
    return run_dir


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="python -m dialogic.run")
    ap.add_argument("config")
    ap.add_argument("--match", help="dialogue run dir whose mean generated tokens set the baseline budget")
    ap.add_argument("--limit", type=int, help="override dataset.limit")
    args = ap.parse_args(argv)

    load_dotenv(ROOT / ".env")
    cfg, raw = load_config(args.config)
    if args.limit:
        cfg["dataset"]["limit"] = args.limit
    asyncio.run(run(cfg, raw, args.match))


if __name__ == "__main__":
    sys.exit(main())
