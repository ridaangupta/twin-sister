import json

import pytest

from fakes import FakeLLM, trailer

from dialogic.orchestrator import DialogueRunner, speaker_order
from dialogic.trace import Tracer
from evals.datasets import Problem

PROBLEM = Problem("p1", "A box holds 12 eggs. How many eggs are in 3 boxes?", "36")
CANARY = {"A": "CANARY-A-7f3e", "B": "CANARY-B-91c2"}


def cfg(**controller):
    return {
        "seed": 0,
        "temperature": 0.0,
        "first_speaker": "A",
        "agents": {"A": {"objective": "accuracy"}, "B": {"objective": "simplicity"}},
        "controller": {"type": "heuristic", "max_turns": 6, "soft_limit": 100, "scratch_budget": 0, "k": 2.0, **controller},
        "synthesis": {"type": "single_writer", "writer": "A"},
    }


def scripted(core_replies, final="SOLUTION:\n1. 3 x 12 = 36\nANSWER: 36"):
    """core_replies[turn] -> post text. Scratchpad replies contain the agent's canary."""

    def script(ctx, messages, max_tokens):
        if ctx.space == "scratchpad":
            return f"private work {CANARY[ctx.agent]}"
        if ctx.space == "synthesis":
            return final
        return core_replies[ctx.turn]

    return script


def runner(llm, tracer=None, **controller):
    return DialogueRunner.from_config(cfg(**controller), llm, tracer)


async def test_stops_on_consensus_and_extracts_from_core():
    llm = FakeLLM(scripted([
        "3 boxes of 12.\n" + trailer("36", "unsure", "yes"),
        "Agreed.\n" + trailer("36", "agree", "yes"),
    ]))
    r = await runner(llm).run(PROBLEM)
    assert (r.stop_reason, r.turns, r.final.answer, r.correct) == ("consensus", 2, "36", True)
    assert [c.ctx.agent for c in llm.calls] == ["A", "B", "A"]
    assert [c.ctx.space for c in llm.calls] == ["core", "core", "synthesis"]
    assert r.agreement_trajectory == [False, True]


async def test_runs_to_max_turns_without_consensus():
    replies = [trailer("36" if t % 2 == 0 else "40", "disagree", "no") for t in range(6)]
    r = await runner(FakeLLM(scripted(replies)), max_turns=4).run(PROBLEM)
    assert (r.stop_reason, r.turns) == ("max_turns", 4)
    assert r.answer_trajectory[-1] == {"A": "36", "B": "40"}


async def test_hard_cap_and_soft_limit_reach_llm():
    llm = FakeLLM(scripted([trailer(consensus="yes")] * 2))
    await runner(llm, soft_limit=150, k=1.5).run(PROBLEM)
    core = [c for c in llm.calls if c.ctx.space == "core"]
    assert all(c.max_tokens == 225 for c in core)
    assert all("about 150 tokens" in c.tail for c in core)


async def test_scratchpad_skipped_when_budget_zero_and_used_otherwise():
    llm = FakeLLM(scripted([trailer(consensus="yes")] * 2))
    await runner(llm, scratch_budget=0).run(PROBLEM)
    assert not any(c.ctx.space == "scratchpad" for c in llm.calls)

    llm = FakeLLM(scripted([trailer(consensus="yes")] * 2))
    r = await runner(llm, scratch_budget=80).run(PROBLEM)
    spaces = [(c.ctx.agent, c.ctx.space) for c in llm.calls]
    assert spaces == [("A", "scratchpad"), ("A", "core"), ("B", "scratchpad"), ("B", "core"), ("A", "synthesis")]
    assert [c.max_tokens for c in llm.calls if c.ctx.space == "scratchpad"] == [80, 80]
    assert r.tokens["scratchpad"] == 2 * len(f"private work {CANARY['A']}".split())


async def test_scratchpads_never_leak_end_to_end():
    """A's notes reach only A's own prompts; B's only B's; the writer sees neither."""
    replies = [trailer("36", "unsure", "no"), trailer("40", "disagree", "no"), trailer("36", "agree", "no"), trailer("36", "agree", "no")]
    llm = FakeLLM(scripted(replies))
    await runner(llm, scratch_budget=50, max_turns=4).run(PROBLEM)

    for call in llm.calls:
        text = call.prompt_text
        if call.ctx.space == "synthesis":
            assert CANARY["A"] not in text and CANARY["B"] not in text
        else:
            other = "B" if call.ctx.agent == "A" else "A"
            assert CANARY[other] not in text, f"{other}'s scratchpad leaked into {call.ctx.agent}/{call.ctx.space}"
    # and the notes do reach their owner on later turns
    a_turn2 = [c for c in llm.calls if c.ctx.agent == "A" and c.ctx.turn == 2 and c.ctx.space == "core"][0]
    assert CANARY["A"] in a_turn2.prompt_text


async def test_ledger_flows_through_dialogue():
    llm = FakeLLM(scripted([
        trailer("36", "unsure", "no", "FACT+: one box holds 12 eggs"),
        trailer("36", "agree", "yes", "FACT_OK: F1"),
        trailer("36", "agree", "yes"),
    ]))
    r = await runner(llm).run(PROBLEM)
    assert (r.ledger_total, r.ledger_agreed) == (1, 1)
    turn2_tail = [c for c in llm.calls if c.ctx.turn == 2][0].tail
    assert "F1 (agreed by B; proposed by A): one box holds 12 eggs" in turn2_tail


async def test_wrong_answer_is_scored_incorrect():
    llm = FakeLLM(scripted([trailer("40", consensus="yes")] * 2, final="SOLUTION:\n1. wrong\nANSWER: 40"))
    r = await runner(llm).run(PROBLEM)
    assert r.final.answer == "40" and not r.correct


async def test_trace_files_and_token_split(tmp_path):
    llm = FakeLLM(scripted([trailer(consensus="yes")] * 2))
    with Tracer(tmp_path, "run-x") as tracer:
        results = await runner(llm, tracer, scratch_budget=40).run_all([PROBLEM, Problem("p2", "Q2", "36")])

    rows = {name: [json.loads(l) for l in (tmp_path / f"{name}.jsonl").read_text().splitlines()] for name in ("turns", "decisions", "problems")}
    assert len(rows["turns"]) == 4 and len(rows["problems"]) == 2
    assert len(rows["decisions"]) == 6  # 2 continue + 1 stop, per problem
    assert {r["problem_id"] for r in rows["problems"]} == {"p1", "p2"}
    assert all(r["run_id"] == "run-x" for rs in rows.values() for r in rs)
    d = rows["decisions"][0]
    assert {"features", "soft_limit", "scratch_budget", "stop", "reason"} <= d.keys()

    t = results[0].tokens
    assert t["generated"] == t["core"] + t["scratchpad"] + t["synthesis"]
    assert t["core"] > 0 and t["scratchpad"] > 0 and t["synthesis"] > 0 and t["prompt"] > 0
    assert rows["problems"][0]["method"] == "dialogue" and "final_text" in rows["problems"][0]


def test_speaker_order():
    assert speaker_order(("A", "B"), "p", 0, "A") == ("A", "B")
    assert speaker_order(("A", "B"), "p", 0, "B") == ("B", "A")
    seeded = {speaker_order(("A", "B"), f"p{i}", 0)[0] for i in range(30)}
    assert seeded == {"A", "B"}
    assert speaker_order(("A", "B"), "p7", 0) == speaker_order(("A", "B"), "p7", 0)
    with pytest.raises(ValueError):
        speaker_order(("A", "B"), "p", 0, "C")


async def test_independent_openings_do_not_see_each_other():
    llm = FakeLLM(scripted([
        "OPEN-A\n" + trailer("36", "unsure", "no"),
        "OPEN-B\n" + trailer("40", "unsure", "no"),
        trailer("36", "agree", "yes"),
        trailer("36", "agree", "yes"),
    ]))
    c = {**cfg(scratch_budget=30), "independent_openings": True}
    r = await DialogueRunner.from_config(c, llm).run(PROBLEM)

    opening_calls = [x for x in llm.calls if x.ctx.turn in (0, 1)]
    assert {(x.ctx.agent, x.ctx.space) for x in opening_calls} == {("A", "scratchpad"), ("A", "core"), ("B", "scratchpad"), ("B", "core")}
    assert all("OPEN-A" not in x.prompt_text and "OPEN-B" not in x.prompt_text for x in opening_calls)
    assert all("opening post" in x.tail or "opening post" in x.tail.lower() for x in opening_calls)
    later = [x for x in llm.calls if x.ctx.turn == 2 and x.ctx.space == "core"][0]
    assert "OPEN-A" in later.prompt_text and "OPEN-B" in later.prompt_text
    assert r.answer_trajectory[:2] == [{"A": "36", "B": None}, {"A": "36", "B": "40"}]
    assert (r.stop_reason, r.turns) == ("consensus", 4)


async def test_stops_when_both_agree_no_answer_and_writer_still_answers():
    llm = FakeLLM(scripted([trailer("none", "unsure", "yes"), trailer("none", "agree", "yes")]))
    r = await runner(llm).run(PROBLEM)
    assert (r.stop_reason, r.turns, r.final.answer) == ("consensus_no_answer", 2, "36")


async def test_prompt_cache_tokens_are_totalled(tmp_path):
    llm = FakeLLM(scripted([trailer(consensus="yes")] * 2))
    r = await runner(llm).run(PROBLEM)
    assert {"prompt_cache_read", "prompt_cache_write"} <= r.tokens.keys()
