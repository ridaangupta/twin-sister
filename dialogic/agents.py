"""A dialogue agent: same model and base prompt for both agents, different objective block.

Message layout (cache-friendly, see prompts.py):
    system: base_agent (identity + objective)          -- fixed per agent
    user:   [problem][instructions][log entry]...       -- append-only, each a cache breakpoint
    user:   ledger state + mode line                    -- volatile tail
"""

from __future__ import annotations

from typing import Any

from dialogic.llm import LLM, CallContext, Completion
from dialogic.memory import AgentView, Post
from dialogic.prompts import PromptLibrary, block, log_blocks, problem_block, render_facts

OPENING = (
    "This is your opening post: the other agent is writing theirs at the same time and you will not see it "
    "until both are posted. Solve the problem in full yourself. "
)
OPENING_PRIVATE = "This is before your opening post: solve the problem independently. "


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

    def _prefix(self, view: AgentView) -> list[dict[str, Any]]:
        if view.agent_id != self.id:
            raise ValueError(f"Agent {self.id} was handed Agent {view.agent_id}'s view")
        return [
            {"role": "system", "content": self.system_prompt()},
            {
                "role": "user",
                "content": [problem_block(view.task), block(self.prompts.get("instructions"))]
                + log_blocks(view.thread, view.scratchpad, viewer=self.id),
            },
        ]

    def _ledger(self, view: AgentView) -> dict[str, str]:
        return {"agreed_facts": render_facts(view.agreed_facts), "open_claims": render_facts(view.open_claims)}

    def scratch_messages(self, view: AgentView, budget: int, turn: int, opening: bool = False) -> list[dict[str, Any]]:
        tail = self.prompts.render("turn_private", **self._ledger(view), turn=turn, budget=budget, opening=OPENING_PRIVATE if opening else "")
        return self._prefix(view) + [{"role": "user", "content": tail}]

    def core_messages(self, view: AgentView, target_tokens: int, turn: int, opening: bool = False) -> list[dict[str, Any]]:
        tail = self.prompts.render("turn_post", **self._ledger(view), turn=turn, target_tokens=target_tokens, opening=OPENING if opening else "")
        return self._prefix(view) + [{"role": "user", "content": tail}]

    async def think(self, view: AgentView, budget: int, ctx: CallContext, *, turn: int, opening: bool = False) -> Completion:
        """Private work; the caller appends the result to this agent's scratchpad."""
        msgs = self.scratch_messages(view, budget, turn, opening)
        return await self.llm.complete(ctx, msgs, max_tokens=budget, temperature=self.temperature)

    async def speak(
        self, view: AgentView, soft_limit: int, hard_cap: int, ctx: CallContext, *, turn: int, opening: bool = False
    ) -> tuple[Post, Completion]:
        msgs = self.core_messages(view, soft_limit, turn, opening)
        c = await self.llm.complete(ctx, msgs, max_tokens=hard_cap, temperature=self.temperature)
        post = Post.from_text(turn, self.id, c.text, completion_tokens=c.completion_tokens, truncated=c.truncated)
        return post, c
