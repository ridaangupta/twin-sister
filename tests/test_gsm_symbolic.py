import json

import pytest

from evals import datasets
from evals.datasets import ROOT
from evals.gsm_symbolic import _path, load_split

pytestmark = pytest.mark.skipif(not _path("p2").exists(), reason="GSM-Symbolic data not downloaded (licence: not committed)")


def test_template_split_is_disjoint_and_complete():
    spec = json.loads((ROOT / "evals/subsets/gsm_symbolic_p2_split.json").read_text())
    dev, test = load_split("p2", "dev"), load_split("p2", "test")
    assert not {p.meta["template"] for p in dev} & {p.meta["template"] for p in test}
    assert len(dev) + len(test) == 2500 and len(set(spec["dev_templates"] + spec["test_templates"])) == 50
    assert all(p.gold == p.gold.strip() and p.gold for p in dev + test)


def test_sampled_config_spreads_across_templates():
    probs = datasets.load({"name": "gsm_symbolic_p2", "split": "dev", "sample": 200, "sample_seed": 0})
    assert len(probs) == 200 and len({p.meta["template"] for p in probs}) >= 20
    assert probs == datasets.load({"name": "gsm_symbolic_p2", "split": "dev", "sample": 200, "sample_seed": 0})
