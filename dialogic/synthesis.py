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
from dialogic.prompts import log_blocks, problem_block, render_facts
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
    prompt_cache_read_tokens: int = 0
    prompt_cache_write_tokens: int = 0


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

    def messages(self, core: CoreView) -> list[dict[str, Any]]:
        if not isinstance(core, CoreView):
            raise TypeError("synthesis reads core only")
        tail = self.writer.prompts.render(
            "final_writer", agreed_facts=render_facts(core.agreed_facts), open_claims=render_facts(core.open_claims)
        )
        return [
            {"role": "system", "content": self.writer.system_prompt()},
            # Core only (no notes). One call that is never reused, so no cache breakpoints: writing costs extra.
            {"role": "user", "content": [problem_block(core.task, cache=False)] + log_blocks(core.thread, (), cache=False)},
            {"role": "user", "content": tail},
        ]

    async def final(self, core: CoreView, ctx: CallContext) -> FinalAnswer:
        c = await self.writer.llm.complete(ctx, self.messages(core), max_tokens=self.max_tokens, temperature=self.writer.temperature)
        answer, steps, length = extract_final(c.text)
        return FinalAnswer(c.text, answer, steps, length, c.prompt_tokens, c.completion_tokens, self.name,
                           c.prompt_cache_read_tokens, c.prompt_cache_write_tokens)


def make_synthesizer(cfg: Mapping[str, Any], agents: Mapping[str, Agent]) -> Synthesizer:
    kind = cfg.get("type", "single_writer")
    if kind == "single_writer":
        return SingleWriter(agents[cfg.get("writer", "A")], max_tokens=cfg.get("max_tokens", 512))
    if kind in ("joint", "synthesizer"):
        raise NotImplementedError(f"synthesis {kind!r} is build step 5")
    raise ValueError(f"unknown synthesis type {kind!r}")
