"""Single-agent self-refine baseline (docs/PLAN_v2.md WS3a).

One agent, on the dialogue's machinery (post format, private budget, soft-limit sampling, hard cap,
turn cap, single-writer synthesis), cycling through roles:
    draft -> critique -> revise -> critique -> revise ...
Draft and revise use the accuracy objective; critique uses skepticism. Every post and note belongs to
the same agent ("A"), so the only differences from the dialogue are one agent instead of two and,
by default, a single draft instead of two independent openings.

`redraft: true` starts with TWO independent drafts (turns 0 and 1, each in an isolated memory, so
neither sees the other's notes or post), then critique/revise: the single-agent analogue of
independent openings.

Stopping uses the heuristic controller: a post with `CONSENSUS: yes` and an answer stops the run,
but never before the first critique (min_turns).
"""

from __future__ import annotations

import asyncio
from dataclasses import asdict
from typing import Any, Mapping, Sequence

from dialogic.agents import Agent
from dialogic.controller import ControllerState, TurnController, TurnDecision, make_controller
from dialogic.llm import LLM, CallContext
from dialogic.memory import Memory
from dialogic.orchestrator import DialogueResult, _Acc, _Turn, _turn_row
from dialogic.prompts import PromptLibrary
from dialogic.protocol import normalize_answer
from dialogic.synthesis import SingleWriter
from dialogic.trace import Tracer
from evals.datasets import Problem

METHOD = "self_refine"
AGENT = "A"


def role_agent(objective: str, post_template: str, llm: LLM, prompts: PromptLibrary, temperature: float | None) -> Agent:
    return Agent(AGENT, AGENT, objective, llm, prompts, temperature=temperature, system_template="base_self",
                 instructions_template="instructions_self", post_template=post_template, private_template="turn_private_self")


class SelfRefineRunner:
    def __init__(self, drafter: Agent, critic: Agent, reviser: Agent, controller: TurnController, *, tracer: Tracer | None = None,
                 k: float = 2.0, max_turns: int, redraft: bool = False, method: str = METHOD):
        self.drafter, self.critic, self.reviser = drafter, critic, reviser
        self.controller = controller
        self.synthesizer = SingleWriter(drafter)
        self.tracer = tracer
        self.k = k
        self.max_turns = max_turns
        self.redraft = redraft
        self.n_drafts = 2 if redraft else 1
        self.method = method

    @classmethod
    def from_config(cls, cfg: Mapping[str, Any], llm: LLM, tracer: Tracer | None = None, prompts: PromptLibrary | None = None) -> SelfRefineRunner:
        prompts = prompts or PromptLibrary()
        sr = cfg.get("self_refine", {})
        t = cfg.get("temperature", 0.0)
        redraft = sr.get("redraft", False)
        # Stop no earlier than after the first critique; `self_refine.min_turns` can require more (an int, or a
        # {low, high, p_high} mixture used to match the dialogue's cost).
        floor = (2 if redraft else 1) + 1
        mt = sr.get("min_turns", floor)
        if isinstance(mt, dict):
            if min(mt["low"], mt["high"]) < floor:
                raise ValueError(f"self_refine.min_turns must be >= {floor}")
        elif mt < floor:
            raise ValueError(f"self_refine.min_turns must be >= {floor}")
        ctl = {**cfg["controller"], "min_turns": mt}
        return cls(
            role_agent(sr.get("draft_objective", "accuracy"), "turn_draft", llm, prompts, t),
            role_agent(sr.get("critique_objective", "skepticism"), "turn_critique", llm, prompts, t),
            role_agent(sr.get("draft_objective", "accuracy"), "turn_revise", llm, prompts, t),
            make_controller(ctl, seed=cfg.get("seed", 0)),
            tracer=tracer, k=ctl.get("k", 2.0), max_turns=ctl["max_turns"], redraft=redraft,
            method=sr.get("label", METHOD),
        )

    def role(self, turn: int) -> Agent:
        if turn < self.n_drafts:
            return self.drafter
        return self.critic if (turn - self.n_drafts) % 2 == 0 else self.reviser

    def _ctx(self, problem: Problem, space: str, turn: int | None) -> CallContext:
        return CallContext(problem_id=problem.id, method=self.method, agent=AGENT, space=space, turn=turn)

    async def _work(self, mem: Memory, problem: Problem, agent: Agent, d: TurnDecision, turn: int) -> _Turn:
        hard_cap = max(1, int(d.soft_limit * self.k))
        note = None
        if d.scratch_budget > 0:
            note = await agent.think(mem.view_for(AGENT), d.scratch_budget, self._ctx(problem, "scratchpad", turn), turn=turn)
            mem.write_scratch(AGENT, note.text, turn=turn)
        post, c = await agent.speak(mem.view_for(AGENT), d.soft_limit, hard_cap, self._ctx(problem, "core", turn), turn=turn)
        return _Turn(agent, d, hard_cap, post, c, note)

    async def run(self, problem: Problem) -> DialogueResult:
        mem = Memory(problem.question, [AGENT])
        state = ControllerState.initial(problem.id, (AGENT,), self.max_turns)
        acc = _Acc()

        def decide(st: ControllerState) -> TurnDecision:
            d = self.controller.decide(st)
            if self.tracer:
                self.tracer.decision({"problem_id": problem.id, "turn": st.turn, "features": st.features(), **asdict(d)})
            return d

        def commit(t: _Turn, note_first: bool = True) -> None:
            nonlocal state
            delta = mem.post(t.post)
            scratch = t.note.completion_tokens if t.note else 0
            state = state.after(t.post, delta, ledger_agreed=len(mem.ledger.agreed()), scratch_tokens=scratch)
            acc.add_turn(t, state)
            if self.tracer:
                self.tracer.turn({**_turn_row(problem.id, t, delta, scratch), "role": self.role(t.post.turn).post_template})

        decision = decide(state)
        if self.redraft and not decision.stop and self.max_turns >= 2:
            # Two drafts, each in its own memory so neither sees the other's notes or post.
            from dataclasses import replace
            d1 = decide(replace(state, turn=1))
            drafts = await asyncio.gather(
                self._work(Memory(problem.question, [AGENT]), problem, self.drafter, decision, 0),
                self._work(Memory(problem.question, [AGENT]), problem, self.drafter, d1, 1),
            )
            for t in drafts:  # notes first (both were written seeing no posts), then posts in order
                if t.note:
                    mem.write_scratch(AGENT, t.note.text, turn=t.post.turn)
            for t in drafts:
                commit(t)
            decision = decide(state)

        while not decision.stop:
            commit(await self._work(mem, problem, self.role(state.turn), decision, state.turn))
            decision = decide(state)

        final = await self.synthesizer.final(mem.core_view(), self._ctx(problem, "synthesis", None))
        acc.tokens["synthesis"] = final.completion_tokens
        acc.add_prompt(final.prompt_tokens, final.prompt_cache_read_tokens, final.prompt_cache_write_tokens)
        acc.tokens["generated"] = acc.tokens["core"] + acc.tokens["scratchpad"] + acc.tokens["synthesis"]
        gold = normalize_answer(problem.gold) or problem.gold
        return DialogueResult(
            problem_id=problem.id, gold=gold, final=final, correct=final.answer is not None and final.answer == gold,
            stop_reason=decision.reason, turns=state.turn, first_speaker=AGENT, tokens=acc.tokens,
            answer_trajectory=acc.answers, agreement_trajectory=acc.agree, answer_changes=dict(state.answer_changes),
            ledger_agreed=state.ledger_agreed, ledger_total=len(mem.ledger.snapshot()), ledger_disputes=state.ledger_disputes,
            protocol_errors=acc.protocol_errors, method=self.method,
        )

    async def run_all(self, problems: Sequence[Problem]) -> list[DialogueResult]:
        async def one(p: Problem) -> DialogueResult | None:
            try:
                r = await self.run(p)
            except Exception as e:  # one failed problem must not sink the run
                if self.tracer:
                    self.tracer.record("errors", {"method": self.method, "problem_id": p.id, "error": repr(e)})
                return None
            if self.tracer:
                self.tracer.problem(r.row())
            return r

        return [r for r in await asyncio.gather(*(one(p) for p in problems)) if r is not None]
