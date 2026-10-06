import csv
import json

import pytest
import yaml

from fakes import FakeLLM, trailer

from dialogic import run as runner
from evals import datasets
from evals.datasets import Problem

PROBLEMS = [Problem(f"toy-{i}", f"What is {i} + {i}?", str(2 * i)) for i in range(4)]

DIALOGUE_CFG = {
    "name": "toy_dialogue",
    "method": "dialogue",
    "model": "fake",
    "seed": 0,
    "dataset": {"name": "toy", "split": "test", "limit": 3},
    "agents": {"A": {"objective": "accuracy"}, "B": {"objective": "simplicity"}},
    "controller": {"type": "heuristic", "max_turns": 4, "soft_limit": 100, "scratch_budget": 20},
    "synthesis": {"type": "single_writer", "writer": "A"},
}
BASELINE_CFG = {
    "name": "toy_baselines",
    "method": "baselines",
    "model": "fake",
    "dataset": {"name": "toy", "split": "test", "limit": 3},
    "baselines": {"methods": ["direct", "cot", "self_consistency"]},
}


def answer_for(ctx):
    i = int(ctx.problem_id.split("-")[1])
    return str(2 * i)


def script(ctx, msgs, mt):
    if ctx.space == "scratchpad":
        return "checking"
    if ctx.space == "core":
        return "work\n" + trailer(answer_for(ctx), "agree", "yes")
    if ctx.space == "synthesis":
        return f"SOLUTION:\n1. add\nANSWER: {answer_for(ctx)}"
    return "some reasoning words here\nANSWER: " + answer_for(ctx)


@pytest.fixture(autouse=True)
def toy_dataset(monkeypatch):
    monkeypatch.setattr(datasets, "load_split", lambda name, split: list(PROBLEMS))


async def test_dialogue_then_matched_baselines(tmp_path):
    d_dir = await runner.run(dict(DIALOGUE_CFG), yaml.safe_dump(DIALOGUE_CFG), runs_dir=tmp_path, llm=FakeLLM(script))

    for f in ("config.yaml", "meta.json", "summary.json", "results.csv", "turns.jsonl", "decisions.jsonl", "problems.jsonl"):
        assert (d_dir / f).exists(), f
    meta = json.loads((d_dir / "meta.json").read_text())
    assert meta["model"] == "fake" and meta["n_problems"] == 3 and "git_hash" in meta
    summary = json.loads((d_dir / "summary.json").read_text())
    assert summary["methods"]["dialogue"]["accuracy"] == 1.0 and summary["errors"] == 0
    rows = list(csv.DictReader(open(d_dir / "results.csv")))
    assert len(rows) == 3 and "tokens_generated" in rows[0] and "final_text" not in rows[0]

    b_dir = await runner.run(dict(BASELINE_CFG), yaml.safe_dump(BASELINE_CFG), match=str(d_dir), runs_dir=tmp_path, llm=FakeLLM(script))
    bmeta = json.loads((b_dir / "meta.json").read_text())
    dlg_mean = summary["methods"]["dialogue"]["tokens_mean"]["generated"]
    assert bmeta["baselines"]["budget"] == round(dlg_mean)
    assert bmeta["matched_run"] == str(d_dir) and bmeta["matched_problems"] == 3
    bsum = json.loads((b_dir / "summary.json").read_text())
    assert set(bsum["methods"]) == {"direct", "cot", "self_consistency"}
    assert len(list(csv.DictReader(open(b_dir / "results.csv")))) == 9


async def test_baselines_need_a_budget(tmp_path):
    with pytest.raises(SystemExit):
        await runner.run(dict(BASELINE_CFG), "", runs_dir=tmp_path, llm=FakeLLM(script))


async def test_refuses_full_split_without_final_run(tmp_path):
    cfg = {**DIALOGUE_CFG, "dataset": {"name": "toy", "split": "test"}}
    with pytest.raises(SystemExit):
        await runner.run(cfg, "", runs_dir=tmp_path, llm=FakeLLM(script))


def test_config_env_expansion(tmp_path, monkeypatch):
    path = tmp_path / "c.yaml"
    path.write_text(yaml.safe_dump({**DIALOGUE_CFG, "model": "${MODEL}"}))
    monkeypatch.setenv("MODEL", "some-model")
    cfg, _ = runner.load_config(path)
    assert cfg["model"] == "some-model"
    monkeypatch.delenv("MODEL")
    with pytest.raises(SystemExit):
        runner.load_config(path)


def test_shipped_configs_parse_and_load(monkeypatch):
    monkeypatch.undo()  # use the real dataset loaders, not the toy fixture
    monkeypatch.setenv("MODEL", "m")
    paths = sorted((runner.ROOT / "configs").glob("*.yaml"))
    assert len(paths) >= 4
    for path in paths:
        cfg, _ = runner.load_config(path)
        if cfg["dataset"]["name"] == "jsonl":
            probs = datasets.load(cfg["dataset"])
            assert len(probs) == cfg["dataset"]["limit"] and all(p.gold.isdigit() for p in probs)


def test_dev_subset_file_is_fixed():
    sub = json.loads((runner.ROOT / "evals/subsets/gsm8k_dev200.json").read_text())
    assert sub["n"] == 200 and len(sub["ids"]) == 200 and len(set(sub["ids"])) == 200
    assert sub["ids"][:3] == ["gsm8k-test-788", "gsm8k-test-861", "gsm8k-test-82"]
