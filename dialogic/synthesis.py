"""Final-answer synthesis from core memory only.

`single_writer` is implemented; `joint` and `synthesizer` plug in behind the same
`Synthesizer.final(core, ctx)` interface (build step 5).
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Mapping

from dialogic.agents import Agent
from dialogic.llm import CallContext
from dialogic.memory import CoreView
from dialogic.prompts import render_facts, render_thread
from dialogic.protocol import extract_answer

_SOLUTION = re.compile(r"SOLUTION[*_`]*\s*:(.*?)(?=^[ \t>*_`-]*ANSWER[*_`]*\s*:|\Z)", re.IGNORECASE | re.DOTALL | re.MULTILINE)
_STEP = re.compile(r"^\s*\d+[.)]\s+\S", re.MULTILINE)


@dataclass(frozen=True)
class FinalAnswer:
    text: str
    answer: str | None
    solution_steps: int  # simplicity proxy
    solution_tokens_est: int  # whitespace tokens in the SOLUTION block
    prompt_tokens: int
    completion_tokens: int
    strategy: str


def extract_final(text: str) -> tuple[str | None, int, int]:
    """(answer, steps, solution length). Answer: last ANSWER line, else last number in the text."""
    answer = extract_answer(text)
    m = _SOLUTION.search(text)
    solution = m.group(1) if m else ""
    return answer, len(_STEP.findall(solution)), len(solution.split())


class Synthesizer(ABC):
    name: str

    @abstractmethod
    async def final(self, core: CoreView, ctx: CallContext) -> FinalAnswer: ...


class SingleWriter(Synthesizer):
    """One configured dialogue agent writes the final answer from core (same objective and system prompt)."""

    name = "single_writer"

    def __init__(self, writer: Agent, max_tokens: int = 512):
        self.writer = writer
        self.max_tokens = max_tokens

    def messages(self, core: CoreView) -> list[dict[str, str]]:
        if not isinstance(core, CoreView):
            raise TypeError("synthesis reads core only")
        user = self.writer.prompts.render(
            "final_writer",
            task=core.task,
            agreed_facts=render_facts(core.agreed_facts),
            open_claims=render_facts(core.open_claims),
            thread=render_thread(core.thread),
        )
        return [{"role": "system", "content": self.writer.system_prompt()}, {"role": "user", "content": user}]

    async def final(self, core: CoreView, ctx: CallContext) -> FinalAnswer:
        c = await self.writer.llm.complete(ctx, self.messages(core), max_tokens=self.max_tokens, temperature=self.writer.temperature)
        answer, steps, length = extract_final(c.text)
        return FinalAnswer(c.text, answer, steps, length, c.prompt_tokens, c.completion_tokens, self.name)


def make_synthesizer(cfg: Mapping[str, Any], agents: Mapping[str, Agent]) -> Synthesizer:
    kind = cfg.get("type", "single_writer")
    if kind == "single_writer":
        return SingleWriter(agents[cfg.get("writer", "A")], max_tokens=cfg.get("max_tokens", 512))
    if kind in ("joint", "synthesizer"):
        raise NotImplementedError(f"synthesis {kind!r} is build step 5")
    raise ValueError(f"unknown synthesis type {kind!r}")
