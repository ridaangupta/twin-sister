"""Run one problem as a dialogue: controller decision → optional private work → core post → repeat.

A turn is one post by one agent. Turns within a problem are sequential;
problems run concurrently under the LLM's shared semaphore.
"""

from __future__ import annotations

import asyncio
import hashlib
from dataclasses import asdict, dataclass, field
from typing import Any, Mapping, Sequence

from dialogic.agents import Agent
from dialogic.controller import ControllerState, TurnController, make_controller
from dialogic.llm import LLM, CallContext
from dialogic.memory import Memory
from dialogic.prompts import PromptLibrary
from dialogic.protocol import normalize_answer
from dialogic.synthesis import FinalAnswer, Synthesizer, make_synthesizer
from dialogic.trace import Tracer
from evals.datasets import Problem

METHOD = "dialogue"


def speaker_order(agent_ids: Sequence[str], problem_id: str, seed: int, mode: str = "seeded") -> tuple[str, str]:
    a, b = agent_ids
    if mode == a:
        return (a, b)
    if mode == b:
        return (b, a)
    if mode != "seeded":
        raise ValueError(f"first_speaker must be 'seeded', {a!r} or {b!r}")
    flip = hashlib.sha256(f"{seed}:{problem_id}".encode()).digest()[0] % 2
    return (b, a) if flip else (a, b)


@dataclass
class DialogueResult:
    problem_id: str
    gold: str
    final: FinalAnswer
    correct: bool
    stop_reason: str
    turns: int
    first_speaker: str
    tokens: dict[str, int]  # generated tokens by space, plus prompt tokens
    answer_trajectory: list[dict[str, str | None]]  # per turn: latest answer per agent
    agreement_trajectory: list[bool]
    answer_changes: dict[str, int]
    ledger_agreed: int
    ledger_total: int
    ledger_disputes: int
    protocol_errors: int
    extra: dict[str, Any] = field(default_factory=dict)

    def row(self) -> dict[str, Any]:
        r = asdict(self)
        r["final_answer"] = self.final.answer
        r["final_text"] = self.final.text
        r["solution_steps"] = self.final.solution_steps
        r["solution_tokens_est"] = self.final.solution_tokens_est
        del r["final"]
        return {"method": METHOD, **r}


class DialogueRunner:
    def __init__(
        self,
        agents: Mapping[str, Agent],
        controller: TurnController,
        synthesizer: Synthesizer,
        *,
        tracer: Tracer | None = None,
        k: float = 2.0,
        seed: int = 0,
        max_turns: int,
        first_speaker: str = "seeded",
    ):
        if len(agents) != 2:
            raise ValueError("dialogue needs exactly two agents")
        self.agents = dict(agents)
        self.agent_ids = tuple(agents)
        self.controller = controller
        self.synthesizer = synthesizer
        self.tracer = tracer
        self.k = k
        self.seed = seed
        self.max_turns = max_turns
        self.first_speaker = first_speaker

    @classmethod
    def from_config(cls, cfg: Mapping[str, Any], llm: LLM, tracer: Tracer | None = None, prompts: PromptLibrary | None = None) -> DialogueRunner:
        prompts = prompts or PromptLibrary()
        ids = tuple(cfg["agents"])
        if len(ids) != 2:
            raise ValueError("config.agents must name exactly two agents")
        agents = {
            aid: Agent(aid, ids[1 - i], cfg["agents"][aid]["objective"], llm, prompts, temperature=cfg.get("temperature", 0.0))
            for i, aid in enumerate(ids)
        }
        ctl = cfg["controller"]
        return cls(
            agents,
            make_controller(ctl, seed=cfg.get("seed", 0)),
            make_synthesizer(cfg.get("synthesis", {}), agents),
            tracer=tracer,
            k=ctl.get("k", 2.0),
            seed=cfg.get("seed", 0),
            max_turns=ctl["max_turns"],
            first_speaker=cfg.get("first_speaker", "seeded"),
        )

    def _ctx(self, problem: Problem, agent: str, space: str, turn: int | None) -> CallContext:
        return CallContext(problem_id=problem.id, method=METHOD, agent=agent, space=space, turn=turn)

    async def run(self, problem: Problem) -> DialogueResult:
        mem = Memory(problem.question, self.agent_ids)
        order = speaker_order(self.agent_ids, problem.id, self.seed, self.first_speaker)
        state = ControllerState.initial(problem.id, self.agent_ids, self.max_turns)
        prompt_tokens = 0
        tokens = {"core": 0, "scratchpad": 0, "synthesis": 0}
        answers_traj: list[dict[str, str | None]] = []
        agree_traj: list[bool] = []
        protocol_errors = 0

        while True:
            decision = self.controller.decide(state)
            if self.tracer:
                self.tracer.decision({"problem_id": problem.id, "turn": state.turn, "features": state.features(), **asdict(decision)})
            if decision.stop:
                break

            turn = state.turn
            agent = self.agents[order[turn % 2]]
            hard_cap = max(1, int(decision.soft_limit * self.k))

            scratch = 0
            if decision.scratch_budget > 0:
                note = await agent.think(mem.view_for(agent.id), decision.scratch_budget, self._ctx(problem, agent.id, "scratchpad", turn))
                mem.write_scratch(agent.id, note.text)
                scratch = note.completion_tokens
                prompt_tokens += note.prompt_tokens

            post, c = await agent.speak(mem.view_for(agent.id), decision.soft_limit, hard_cap, self._ctx(problem, agent.id, "core", turn))
            prompt_tokens += c.prompt_tokens
            delta = mem.post(post)
            state = state.after(post, delta, ledger_agreed=len(mem.ledger.agreed()), scratch_tokens=scratch)

            tokens["core"] += post.completion_tokens
            tokens["scratchpad"] += scratch
            answers_traj.append(dict(state.answers))
            agree_traj.append(state.answers_agree)
            protocol_errors += post.protocol_error

            if self.tracer:
                self.tracer.turn(
                    {
                        "problem_id": problem.id,
                        "turn": turn,
                        "agent": agent.id,
                        "objective": agent.objective,
                        "answer": post.answer,
                        "stance": post.stance,
                        "consensus": post.consensus,
                        "ledger_ops": [asdict(op) for op in post.ledger_ops],
                        "ledger_delta": {**asdict(delta), "rejected": [[asdict(op), why] for op, why in delta.rejected]},
                        "soft_limit": decision.soft_limit,
                        "hard_cap": hard_cap,
                        "scratch_budget": decision.scratch_budget,
                        "scratch_tokens": scratch,
                        "tokens": post.completion_tokens,
                        "truncated": post.truncated,
                        "protocol_error": post.protocol_error,
                        "protocol_errors": list(post.protocol_errors),
                    }
                )

        final = await self.synthesizer.final(mem.core_view(), self._ctx(problem, self._writer_label(), "synthesis", None))
        tokens["synthesis"] = final.completion_tokens
        tokens["generated"] = tokens["core"] + tokens["scratchpad"] + tokens["synthesis"]
        tokens["prompt"] = prompt_tokens + final.prompt_tokens

        gold = normalize_answer(problem.gold) or problem.gold
        return DialogueResult(
            problem_id=problem.id,
            gold=gold,
            final=final,
            correct=final.answer is not None and final.answer == gold,
            stop_reason=decision.reason,
            turns=state.turn,
            first_speaker=order[0],
            tokens=tokens,
            answer_trajectory=answers_traj,
            agreement_trajectory=agree_traj,
            answer_changes=dict(state.answer_changes),
            ledger_agreed=state.ledger_agreed,
            ledger_total=len(mem.ledger.snapshot()),
            ledger_disputes=state.ledger_disputes,
            protocol_errors=protocol_errors,
        )

    def _writer_label(self) -> str:
        writer = getattr(self.synthesizer, "writer", None)
        return writer.id if writer is not None else "synthesizer"

    async def run_all(self, problems: Sequence[Problem]) -> list[DialogueResult]:
        async def one(p: Problem) -> DialogueResult | None:
            try:
                r = await self.run(p)
            except Exception as e:  # one failed problem must not sink the run
                if self.tracer:
                    self.tracer.record("errors", {"method": METHOD, "problem_id": p.id, "error": repr(e)})
                return None
            if self.tracer:  # written as each problem finishes, so a later failure loses nothing
                self.tracer.problem(r.row())
            return r

        return [r for r in await asyncio.gather(*(one(p) for p in problems)) if r is not None]
