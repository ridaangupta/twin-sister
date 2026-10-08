"""GSM-Symbolic loader (apple-aiml-research/ml-gsm-symbolic, generated data).

The data is licensed CC BY-NC-ND 4.0: it is downloaded at load time into data/gsm_symbolic/
(gitignored), verified against a pinned sha256, and never committed or modified. Only the
template-level dev/test split (evals/subsets/gsm_symbolic_p2_split.json) lives in the repo.

Instances of one template are correlated, so splits are by template and analyses must cluster by
template (`Problem.meta["template"]`).
"""

from __future__ import annotations

import hashlib
import json
import random
import urllib.request
from pathlib import Path

from dialogic.protocol import normalize_answer
from evals.datasets import ROOT, Problem

DATA_DIR = ROOT / "data" / "gsm_symbolic"
_URL = "https://raw.githubusercontent.com/apple-aiml-research/ml-gsm-symbolic/main/generated_data/{name}.jsonl"
FILES = {"p2": "GSM_p2", "p1": "GSM_p1", "symbolic": "GSM_symbolic"}
SHA256 = {"p2": "f7d6701619f824f4fedd0a914b1cfbc0fd31f61617887aa7fe318d018dda3f29"}
SPLIT_FILE = "evals/subsets/gsm_symbolic_{variant}_split.json"


def _path(variant: str) -> Path:
    return DATA_DIR / f"{FILES[variant]}.jsonl"


def _fetch(variant: str) -> None:
    path = _path(variant)
    path.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(_URL.format(name=FILES[variant]), timeout=60) as r:
        data = r.read()
    path.with_suffix(".tmp").write_bytes(data)
    path.with_suffix(".tmp").rename(path)


def load_all(variant: str = "p2") -> list[Problem]:
    path = _path(variant)
    if not path.exists():
        _fetch(variant)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if variant in SHA256 and digest != SHA256[variant]:
        raise ValueError(f"{path} checksum mismatch: {digest}")
    problems = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        gold = normalize_answer(r["answer"].rsplit("####", 1)[1])
        if gold is None:
            raise ValueError(f"unparseable gold for template {r['id']} instance {r['instance']}")
        problems.append(Problem(f"gsmsym-{variant}-t{r['id']}-i{r['instance']}", r["question"], gold,
                                {"template": int(r["id"]), "instance": int(r["instance"]), "original_id": r["original_id"]}))
    return problems


def make_split(variant: str = "p2", seed: int = 0) -> dict:
    """Half the templates for dev, half for test, by a seeded shuffle of template ids."""
    templates = sorted({p.meta["template"] for p in load_all(variant)})
    rng = random.Random(seed)
    shuffled = templates[:]
    rng.shuffle(shuffled)
    half = len(shuffled) // 2
    return {"variant": variant, "seed": seed, "dev_templates": sorted(shuffled[:half]), "test_templates": sorted(shuffled[half:]),
            "sha256": SHA256.get(variant), "note": "Template-level split; instances of a template never cross sets."}


def load_split(variant: str, split: str) -> list[Problem]:
    spec = json.loads((ROOT / SPLIT_FILE.format(variant=variant)).read_text())
    keep = set(spec[f"{split}_templates"])
    return [p for p in load_all(variant) if p.meta["template"] in keep]
