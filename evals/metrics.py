"""Answer scoring and per-run aggregation over problem rows (dialogue or baseline)."""

from __future__ import annotations

import random
from collections import Counter
from statistics import mean
from typing import Any, Iterable, Mapping, Sequence

from dialogic.protocol import extract_answer, normalize_answer

__all__ = ["extract_answer", "normalize_answer", "exact_match", "bootstrap_ci", "mind_changes", "summarize", "cost_usd"]


def exact_match(pred: str | None, gold: str | None) -> bool:
    p, g = normalize_answer(pred), normalize_answer(gold)
    return p is not None and p == g


def bootstrap_ci(values: Sequence[float], n_boot: int = 2000, alpha: float = 0.05, seed: int = 0) -> tuple[float, float]:
    if not values:
        return (float("nan"), float("nan"))
    rng = random.Random(seed)
    k = len(values)
    means = sorted(sum(rng.choices(values, k=k)) / k for _ in range(n_boot))
    return (means[int(alpha / 2 * n_boot)], means[int((1 - alpha / 2) * n_boot) - 1])


def mind_changes(trajectory: Sequence[Mapping[str, str | None]]) -> Counter:
    """Who changed whose mind: `"B<-A"` counts B switching to the answer A held just before.

    Changes to an answer neither agent held are counted as `"A<-self"` / `"B<-self"`.
    """
    out: Counter = Counter()
    prev: dict[str, str | None] = {}
    for step in trajectory:
        for agent, ans in step.items():
            before = prev.get(agent)
            if ans is None or before is None or ans == before:
                continue
            sources = [o for o, oa in prev.items() if o != agent and oa == ans]
            out[f"{agent}<-{sources[0]}" if sources else f"{agent}<-self"] += 1
        prev = {a: (v if v is not None else prev.get(a)) for a, v in step.items()}
    return out


def cost_usd(
    prompt_tokens: int,
    completion_tokens: int,
    pricing: Mapping[str, float] | None,
    *,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
) -> float | None:
    """USD from token counts. pricing: {input_per_mtok, output_per_mtok, cache_read_per_mtok?, cache_write_per_mtok?}.

    Prompt-cache reads/writes are priced at the input rate unless their own rates are configured.
    None when no pricing is configured.
    """
    if not pricing:
        return None
    rate_in = pricing["input_per_mtok"]
    uncached = prompt_tokens - cache_read_tokens - cache_write_tokens
    return (
        uncached * rate_in
        + cache_read_tokens * pricing.get("cache_read_per_mtok", rate_in)
        + cache_write_tokens * pricing.get("cache_write_per_mtok", rate_in)
        + completion_tokens * pricing["output_per_mtok"]
    ) / 1e6


def _mean(rows: Iterable[Mapping[str, Any]], *path: str) -> float | None:
    vals = []
    for r in rows:
        v: Any = r
        for p in path:
            v = v.get(p) if isinstance(v, Mapping) else None
        if isinstance(v, (int, float)):
            vals.append(v)
    return mean(vals) if vals else None


def summarize(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Aggregate metrics for one method's problem rows."""
    correct = [float(r["correct"]) for r in rows]
    lo, hi = bootstrap_ci(correct)
    out: dict[str, Any] = {
        "n": len(rows),
        "accuracy": mean(correct) if rows else None,
        "accuracy_ci95": [lo, hi],
        "no_answer_rate": mean(r["final_answer"] is None for r in rows) if rows else None,
        "tokens_mean": {k: _mean(rows, "tokens", k) for k in sorted({k for r in rows for k in r.get("tokens", {})})},
    }
    dialogue = [r for r in rows if r.get("method") == "dialogue"]
    if dialogue:
        flips: Counter = Counter()
        for r in dialogue:
            flips.update(mind_changes(r["answer_trajectory"]))
        out.update(
            turns_mean=_mean(dialogue, "turns"),
            stop_reasons=dict(Counter(r["stop_reason"] for r in dialogue)),
            consensus_rate=mean(r["stop_reason"] == "consensus" for r in dialogue),
            final_agreement_rate=mean(bool(r["agreement_trajectory"]) and r["agreement_trajectory"][-1] for r in dialogue),
            mind_changes=dict(flips),
            ledger_agreed_mean=_mean(dialogue, "ledger_agreed"),
            ledger_total_mean=_mean(dialogue, "ledger_total"),
            ledger_disputes_mean=_mean(dialogue, "ledger_disputes"),
            protocol_errors_per_problem=_mean(dialogue, "protocol_errors"),
            solution_steps_mean=_mean(dialogue, "solution_steps"),
        )
    sc = [r for r in rows if r.get("method") == "self_consistency"]
    if sc:
        out["samples_mean"] = _mean(sc, "n_samples")
    return out
