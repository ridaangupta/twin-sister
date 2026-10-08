from fakes import FakeLLM, trailer

from dialogic.prompts import BREAKPOINT_KEY
from dialogic.self_refine import SelfRefineRunner
from evals.datasets import Problem

PROBLEM = Problem("p1", "A box holds 12 eggs. How many eggs are in 3 boxes?", "36")


def cfg(redraft=False, **controller):
    return {
        "seed": 0,
        "temperature": None,
        "self_refine": {"redraft": redraft},
        "controller": {"type": "heuristic", "max_turns": 6, "soft_limit": 100, "scratch_budget": 20, "k": 2.0, **controller},
    }


def script(replies):
    def s(ctx, messages, max_tokens):
        if ctx.space == "scratchpad":
            return f"note t{ctx.turn}"
        if ctx.space == "synthesis":
            return "SOLUTION:\n1. 3 x 12 = 36\nANSWER: 36"
        return replies[ctx.turn]
    return s


def modes(llm):
    return [(c.ctx.turn, c.tail.split(".")[0]) for c in llm.calls if c.ctx.space == "core"]


async def test_roles_cycle_and_no_stop_before_first_critique():
    llm = FakeLLM(script([f"DRAFT-0\n{trailer(consensus='yes')}", f"CRIT-1\n{trailer(consensus='no')}",
                          f"REV-2\n{trailer(consensus='no')}", f"CRIT-3\n{trailer(consensus='yes')}"]))
    r = await SelfRefineRunner.from_config(cfg(), llm).run(PROBLEM)
    assert modes(llm) == [(0, "MODE: DRAFT"), (1, "MODE: CRITIQUE"), (2, "MODE: REVISE"), (3, "MODE: CRITIQUE")]
    assert (r.stop_reason, r.turns, r.method, r.final.answer) == ("consensus", 4, "self_refine", "36")
    assert {c.ctx.agent for c in llm.calls} == {"A"}


async def test_critique_objective_is_skepticism_and_drafts_accuracy():
    llm = FakeLLM(script([trailer(consensus="no"), trailer(consensus="yes")]))
    await SelfRefineRunner.from_config(cfg(), llm).run(PROBLEM)
    core = [c for c in llm.calls if c.ctx.space == "core"]
    assert "Accuracy." in core[0].messages[0]["content"] and "Skepticism." in core[1].messages[0]["content"]
    assert "There is no other agent" in core[0].messages[0]["content"]


async def test_redraft_drafts_are_independent():
    llm = FakeLLM(script([f"DRAFT-ZERO\n{trailer('36', consensus='no')}", f"DRAFT-ONE\n{trailer('40', consensus='no')}",
                          f"CRIT\n{trailer('36', consensus='yes')}"]))
    r = await SelfRefineRunner.from_config(cfg(redraft=True), llm).run(PROBLEM)
    early = [c for c in llm.calls if c.ctx.turn in (0, 1)]
    assert len(early) == 4 and all("DRAFT-ZERO" not in c.prompt_text and "DRAFT-ONE" not in c.prompt_text for c in early)
    assert all("note t0" not in c.prompt_text for c in early if c.ctx.turn == 1)
    assert all("note t1" not in c.prompt_text for c in early if c.ctx.turn == 0)
    crit = [c for c in llm.calls if c.ctx.turn == 2 and c.ctx.space == "core"][0]
    assert "DRAFT-ZERO" in crit.prompt_text and "DRAFT-ONE" in crit.prompt_text and "MODE: CRITIQUE" in crit.tail
    assert r.turns == 3 and r.answer_trajectory[:2] == [{"A": "36"}, {"A": "40"}]


async def test_prefix_cacheable_and_trace_rows_labelled(tmp_path):
    from dialogic.trace import Tracer
    import json
    llm = FakeLLM(script([trailer(consensus="no"), trailer(consensus="yes")]))
    c = {**cfg(), "self_refine": {"label": "self_refine_x"}}
    with Tracer(tmp_path, "r") as tr:
        rs = await SelfRefineRunner.from_config(c, llm, tr).run_all([PROBLEM])
    assert rs[0].method == "self_refine_x"
    rows = [json.loads(l) for l in (tmp_path / "problems.jsonl").read_text().splitlines()]
    assert rows[0]["method"] == "self_refine_x"
    turns = [json.loads(l) for l in (tmp_path / "turns.jsonl").read_text().splitlines()]
    assert [t["role"] for t in turns] == ["turn_draft", "turn_critique"]
    assert all(BREAKPOINT_KEY in b for b in llm.calls[-2].messages[1]["content"])  # cacheable prefix, as the dialogue's


async def test_ledger_has_no_confirmations_with_one_agent():
    llm = FakeLLM(script([trailer(consensus="no", extra="FACT+: 12 per box"), trailer(consensus="yes", extra="FACT_OK: F1")]))
    r = await SelfRefineRunner.from_config(cfg(), llm).run(PROBLEM)
    assert r.ledger_agreed == 0


async def test_min_turns_mixture_forces_more_critique_rounds():
    replies = [trailer(consensus="yes")] * 8
    probs = [Problem(f"p{i}", "q", "36") for i in range(60)]
    c = {**cfg(), "self_refine": {"min_turns": {"low": 2, "high": 4, "p_high": 0.5}}}
    rs = await SelfRefineRunner.from_config(c, FakeLLM(script(replies))).run_all(probs)
    turns = [r.turns for r in rs]
    assert set(turns) == {2, 4} and 15 < turns.count(4) < 45


def test_min_turns_below_floor_rejected():
    import pytest
    with pytest.raises(ValueError):
        SelfRefineRunner.from_config({**cfg(redraft=True), "self_refine": {"redraft": True, "min_turns": 2}}, FakeLLM(script([])))
