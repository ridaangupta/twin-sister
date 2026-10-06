"""A dialogue agent: same model and base prompt for both agents, different objective block."""

from __future__ import annotations

from dialogic.llm import LLM, CallContext, Completion
from dialogic.memory import AgentView, Post
from dialogic.prompts import PromptLibrary, render_facts, render_notes, render_thread


class Agent:
    def __init__(
        self,
        agent_id: str,
        other_id: str,
        objective: str,
        llm: LLM,
        prompts: PromptLibrary,
        *,
        temperature: float | None = 0.0,
    ):
        self.id = agent_id
        self.other_id = other_id
        self.objective = objective
        self.llm = llm
        self.prompts = prompts
        self.temperature = temperature

    def system_prompt(self) -> str:
        return self.prompts.render(
            "base_agent",
            agent_id=self.id,
            other_id=self.other_id,
            objective=self.prompts.objective(self.objective),
        )

    def _state(self, view: AgentView) -> dict[str, str]:
        if view.agent_id != self.id:
            raise ValueError(f"Agent {self.id} was handed Agent {view.agent_id}'s view")
        return {
            "task": view.task,
            "agreed_facts": render_facts(view.agreed_facts),
            "open_claims": render_facts(view.open_claims),
            "thread": render_thread(view.thread, viewer=self.id),
            "scratchpad": render_notes(view.scratchpad),
            "turn": str(len(view.thread)),
        }

    def scratch_messages(self, view: AgentView, budget: int) -> list[dict[str, str]]:
        user = self.prompts.render("scratchpad", **self._state(view), budget=budget)
        return [{"role": "system", "content": self.system_prompt()}, {"role": "user", "content": user}]

    def core_messages(self, view: AgentView, target_tokens: int) -> list[dict[str, str]]:
        user = self.prompts.render("core_turn", **self._state(view), target_tokens=target_tokens)
        return [{"role": "system", "content": self.system_prompt()}, {"role": "user", "content": user}]

    async def think(self, view: AgentView, budget: int, ctx: CallContext) -> Completion:
        """Private work; the caller appends the result to this agent's scratchpad."""
        return await self.llm.complete(ctx, self.scratch_messages(view, budget), max_tokens=budget, temperature=self.temperature)

    async def speak(self, view: AgentView, soft_limit: int, hard_cap: int, ctx: CallContext) -> tuple[Post, Completion]:
        c = await self.llm.complete(ctx, self.core_messages(view, soft_limit), max_tokens=hard_cap, temperature=self.temperature)
        post = Post.from_text(len(view.thread), self.id, c.text, completion_tokens=c.completion_tokens, truncated=c.truncated)
        return post, c
