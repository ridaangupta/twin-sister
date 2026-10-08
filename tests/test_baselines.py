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


async def test_two_plus_judge_accepts_agreement_without_judge():
    llm = FakeLLM(lambda ctx, msgs, mt: "ANSWER: 18")
    r = await Baselines(llm).two_plus_judge(P, sample_budget=300, judge_budget=500)
    assert r.correct and r.judged is False and len(llm.calls) == 2
    assert sorted(c.ctx.sample_idx for c in llm.calls) == [0, 1] and all(c.temperature == 0.7 for c in llm.calls)


async def test_two_plus_judge_calls_judge_on_disagreement():
    def script(ctx, msgs, mt):
        if ctx.sample_idx < 2:
            return f"work {ctx.sample_idx}\nANSWER: {17 + ctx.sample_idx}"
        return "WORKING:\nrecheck = 18\nANSWER: 18"

    llm = FakeLLM(script)
    r = await Baselines(llm, temperature=None).two_plus_judge(P, sample_budget=300, judge_budget=500)
    judge = llm.calls[-1]
    assert r.judged and r.final_answer == "18" and r.sample_answers == ["17", "18"]
    assert judge.max_tokens == 500 and judge.temperature is None
    assert "work 0" in judge.prompt_text and "work 1" in judge.prompt_text
    assert r.tokens["generated"] == sum(len(script(c.ctx, None, 0).split()) for c in llm.calls)


async def test_run_baselines_fixed_sc_samples_and_judge():
    llm = FakeLLM(lambda ctx, msgs, mt: "ANSWER: 18")
    results, info = await run_baselines({"baselines": {"methods": ["self_consistency", "two_plus_judge"], "sc_samples": 7}}, [P], budget=900, llm=llm)
    assert results["self_consistency"][0].n_samples == 7 and info["self_consistency"]["n"] == 7
    assert results["two_plus_judge"][0].judged is False


async def test_sc_mixture_picks_per_problem_and_reuses_draws():
    from evals.mixture import Mixture
    probs = [Problem(f"p{i}", "q", "18") for i in range(200)]
    llm = FakeLLM(lambda ctx, msgs, mt: "ANSWER: 18")
    rs = await Baselines(llm).run("self_consistency", probs, n=Mixture(7, 8, 0.25, "sc_samples"), sample_budget=300)
    ns = [r.n_samples for r in rs]
    assert set(ns) == {7, 8} and 0.15 < ns.count(8) / len(ns) < 0.35
    assert all(r.setting == f"n={r.n_samples}" for r in rs)


async def test_reasoning_baseline_effort_and_tokens():
    from evals.mixture import Mixture
    seen = []

    class Spy(FakeLLM):
        async def complete(self, ctx, messages, *, max_tokens, temperature=0.0, reasoning_effort=None):
            seen.append((reasoning_effort, temperature, max_tokens))
            return await super().complete(ctx, messages, max_tokens=max_tokens, temperature=temperature)

    llm = Spy(lambda ctx, msgs, mt: "step by step\nANSWER: 18")
    probs = [Problem(f"p{i}", "q", "18") for i in range(100)]
    rs = await Baselines(llm).run("reasoning", probs, effort=Mixture("low", "medium", 0.5, "reasoning_effort"), max_tokens=32000)
    assert {e for e, _, _ in seen} == {"low", "medium"} and all(t is None and m == 32000 for _, t, m in seen)
    assert all(r.correct and r.setting in ("low", "medium") and "reasoning" in r.tokens for r in rs)
    assert "Solve the problem step by step" in llm.calls[0].prompt_text and "WORKING" not in llm.calls[0].prompt_text


async def test_k_plus_judge_sees_all_attempts_and_skips_when_unanimous():
    def script(ctx, msgs, mt):
        if ctx.sample_idx == 1000:
            return "WORKING:\nx = 18\nANSWER: 18"
        return f"attempt {ctx.sample_idx}\nANSWER: {18 if ctx.problem_id == 'agree' or ctx.sample_idx else 17}"

    llm = FakeLLM(script)
    b = Baselines(llm, temperature=None)
    r = await b.k_plus_judge(Problem("split", "q", "18"), k=4, sample_budget=300, judge_budget=900)
    judge = llm.calls[-1]
    assert r.judged and r.correct and r.sample_answers == ["17", "18", "18", "18"]
    assert all(f"ATTEMPT {i}:" in judge.prompt_text for i in (1, 2, 3, 4)) and "4 independent attempts" in judge.prompt_text
    assert judge.max_tokens == 900
    n_before = len(llm.calls)
    r2 = await b.k_plus_judge(Problem("agree", "q", "18"), k=3, sample_budget=300, judge_budget=900)
    assert r2.judged is False and len(llm.calls) == n_before + 3
