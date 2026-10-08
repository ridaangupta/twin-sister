"""Common dataset interface. Loaders (GSM8K, later FinQA) return lists of `Problem`.

Fixed subsets are committed id lists under evals/subsets/, not RNG calls, so they
stay identical across library versions.
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Problem:
    id: str
    question: str
    gold: str  # normalized gold answer
    meta: dict[str, Any] = field(default_factory=dict)


def load_split(name: str, split: str) -> list[Problem]:
    if name == "gsm8k":
        from evals.gsm8k import load_gsm8k

        return load_gsm8k(split)
    if name.startswith("gsm_symbolic_"):  # gsm_symbolic_p2 with split dev | test (template-level)
        from evals.gsm_symbolic import load_split as load_sym

        return load_sym(name.removeprefix("gsm_symbolic_"), split)
    raise ValueError(f"unknown dataset {name!r}")


def make_subset(problems: list[Problem], n: int, seed: int = 0) -> list[str]:
    """Random sample of ids in sampled order, so any prefix is itself a random subset."""
    return [p.id for p in random.Random(seed).sample(problems, n)]


def load_jsonl(path: str | Path) -> list[Problem]:
    rows = (json.loads(l) for l in (ROOT / path).read_text().splitlines() if l.strip())
    return [Problem(r["id"], r["question"], r["gold"], r.get("meta", {})) for r in rows]


def save_jsonl(problems: list[Problem], path: str | Path) -> None:
    lines = [json.dumps({"id": p.id, "question": p.question, "gold": p.gold, "meta": p.meta}) for p in problems]
    (ROOT / path).write_text("\n".join(lines) + "\n")


def load(cfg: Mapping[str, Any]) -> list[Problem]:
    """cfg: {name, split, subset?: path to id list, limit?: first n of the subset/split}.

    name: jsonl     -> {path}: a committed, frozen problem file
    name: synthetic -> {n, seed, knobs}: generated on the fly (use jsonl for experiments)
    """
    if cfg["name"] == "jsonl":
        problems = load_jsonl(cfg["path"])
    elif cfg["name"] == "synthetic":
        from evals.synthetic import generate_set

        problems = generate_set(cfg["n"], cfg.get("seed", 0), **cfg.get("knobs", {}))
    else:
        problems = load_split(cfg["name"], cfg.get("split", "test"))
    if subset := cfg.get("subset"):
        ids = json.loads((ROOT / subset).read_text())["ids"]
        by_id = {p.id: p for p in problems}
        missing = [i for i in ids if i not in by_id]
        if missing:
            raise ValueError(f"subset {subset} has ids not in the split: {missing[:5]}")
        problems = [by_id[i] for i in ids]
    if sample := cfg.get("sample"):  # seeded random subset (e.g. spread across GSM-Symbolic templates)
        problems = random.Random(cfg.get("sample_seed", 0)).sample(problems, sample)
    if limit := cfg.get("limit"):
        problems = problems[:limit]
    return problems


def is_full_split(cfg: Mapping[str, Any]) -> bool:
    """True only for a public benchmark's whole split; generated and frozen sets are always allowed."""
    return cfg["name"] not in ("jsonl", "synthetic") and not cfg.get("subset") and not cfg.get("limit")
