"""Scripted stand-in for `LLM` with the same `complete()` signature. No network."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from dialogic.llm import CallContext, Completion, UsageTracker
from dialogic.prompts import text_of

Script = Callable[[CallContext, list[dict], int], "str | tuple[str, str]"]


@dataclass
class Call:
    ctx: CallContext
    messages: list[dict]
    max_tokens: int
    temperature: float | None

    @property
    def prompt_text(self) -> str:
        return text_of(self.messages)

    @property
    def tail(self) -> str:
        """The volatile last message (ledger state + mode line)."""
        return text_of(self.messages[-1:])


class FakeLLM:
    model = "fake"

    def __init__(self, script: Script):
        self.script = script
        self.calls: list[Call] = []
        self.usage = UsageTracker()

    async def complete(self, ctx, messages, *, max_tokens, temperature=0.0) -> Completion:
        self.calls.append(Call(ctx, messages, max_tokens, temperature))
        out = self.script(ctx, messages, max_tokens)
        text, finish = out if isinstance(out, tuple) else (out, "stop")
        c = Completion(
            text=text,
            prompt_tokens=len(text_of(messages).split()),
            completion_tokens=len(text.split()),
            reasoning_tokens=0,
            finish_reason=finish,
            latency_s=0.0,
            cached=False,
        )
        self.usage.add(ctx, c)
        return c


def trailer(answer="36", stance="agree", consensus="no", extra=""):
    return f"ANSWER: {answer}\nSTANCE: {stance}\nCONSENSUS: {consensus}\n{extra}".strip()
