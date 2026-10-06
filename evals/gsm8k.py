"""GSM8K loader. Fetches the official jsonl once into data/gsm8k/ and verifies its checksum."""

from __future__ import annotations

import hashlib
import json
import urllib.request
from pathlib import Path

from dialogic.protocol import normalize_answer
from evals.datasets import Problem

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "gsm8k"
_URL = "https://raw.githubusercontent.com/openai/grade-school-math/master/grade_school_math/data/{split}.jsonl"
SHA256 = {
    "test": "3730d312f6e3440559ace48831e51066acaca737f6eabec99bccb9e4b3c39d14",
}


def parse_gold(solution: str) -> str:
    """GSM8K solutions end with '#### <answer>'."""
    if "####" not in solution:
        raise ValueError("GSM8K solution has no '####' marker")
    gold = normalize_answer(solution.rsplit("####", 1)[1])
    if gold is None:
        raise ValueError(f"unparseable GSM8K gold: {solution.rsplit('####', 1)[1]!r}")
    return gold


def _fetch(split: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with urllib.request.urlopen(_URL.format(split=split), timeout=60) as r:
        tmp.write_bytes(r.read())
    tmp.rename(path)


def _verify(split: str, path: Path) -> None:
    expected = SHA256.get(split)
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    if expected and actual != expected:
        raise ValueError(f"{path} checksum mismatch: {actual} != {expected}")


def load_gsm8k(split: str = "test", data_dir: str | Path = DATA_DIR) -> list[Problem]:
    path = Path(data_dir) / f"{split}.jsonl"
    if not path.exists():
        _fetch(split, path)
    _verify(split, path)
    problems = []
    with open(path, encoding="utf-8") as f:
        for i, line in enumerate(f):
            row = json.loads(line)
            problems.append(Problem(f"gsm8k-{split}-{i}", row["question"], parse_gold(row["answer"]), {"solution": row["answer"]}))
    return problems
