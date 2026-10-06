import pytest

from fakes import FakeLLM

from evals.baselines import Baselines, majority_vote, run_baselines, sc_num_samples
from evals.datasets import Problem

P = Problem("p1", "Janet has 16 eggs, eats 7, sells the rest at $2. How much does she make?", "18")


def test_majority_vote():
    assert majority_vote(["18", "17", "18"]) == "18"
    assert majority_vote(["17", "18"]) == "17"  # tie -> earliest
    assert majority_vote([None, "18", None]) == "18"
    assert majority_vote([None, None]) is None


def test_sc_num_samples():
    assert sc_num_samples(1000, 250) == 4
    assert sc_num_samples(300, 250) == 3  # floor at min_samples
    assert sc_num_samples(1000, 0) == 1000  # guarded division


async def test_direct_and_cot():
    llm = FakeLLM(lambda ctx, msgs, mt: "ANSWER: 18" if ctx.method == "direct" else "9 eggs * 2 = 18\nANSWER: 18")
    b = Baselines(llm)
    d = await b.direct(P, max_tokens=16)
    c = await b.cot(P, budget=700)
    assert d.correct and c.correct and d.method == "direct" and c.method == "cot"
    assert [call.max_tokens for call in llm.calls] == [16, 700]
    assert "about 700 tokens" in llm.calls[1].messages[0]["content"]
    assert c.tokens["generated"] == len("9 eggs * 2 = 18\nANSWER: 18".split())


async def test_self_consistency_votes_over_distinct_samples():
    replies = {0: "ANSWER: 17", 1: "ANSWER: 18", 2: "ANSWER: 18", 3: ("cut", "length")}
    llm = FakeLLM(lambda ctx, msgs, mt: replies[ctx.sample_idx])
    r = await Baselines(llm).self_consistency(P, n=4, sample_budget=300, temperature=0.7)
    assert r.final_answer == "18" and r.correct
    assert r.sample_answers == ["17", "18", "18", None] and r.truncated == 1
    assert sorted(c.ctx.sample_idx for c in llm.calls) == [0, 1, 2, 3]
    assert all(c.temperature == 0.7 and c.max_tokens == 300 for c in llm.calls)
    assert r.tokens["generated"] == 2 + 2 + 2 + 1


async def test_run_baselines_sizes_sc_from_measured_cot():
    cot_text = " ".join(["w"] * 99) + "\nANSWER: 18"  # 101 whitespace tokens
    llm = FakeLLM(lambda ctx, msgs, mt: "ANSWER: 18" if ctx.method == "direct" else cot_text)
    probs = [P, Problem("p2", "q", "18")]
    results, info = await run_baselines({"baselines": {}}, probs, budget=505, llm=llm)
    assert set(results) == {"direct", "cot", "self_consistency"}
    assert info["self_consistency"]["n"] == 5 and info["self_consistency"]["cot_tokens_ref"] == 101
    assert all(r.n_samples == 5 for r in results["self_consistency"])


async def test_sc_without_cot_needs_reference():
    llm = FakeLLM(lambda *_: "ANSWER: 1")
    with pytest.raises(ValueError):
        await run_baselines({"baselines": {"methods": ["self_consistency"]}}, [P], budget=500, llm=llm)


async def test_failed_problem_is_skipped_not_fatal():
    def script(ctx, msgs, mt):
        if ctx.problem_id == "bad":
            raise RuntimeError("api down")
        return "ANSWER: 18"

    rs = await Baselines(FakeLLM(script)).run("direct", [P, Problem("bad", "q", "1")], max_tokens=8)
    assert [r.problem_id for r in rs] == ["p1"]
