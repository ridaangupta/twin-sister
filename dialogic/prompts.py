"""Load prompt templates from /prompts and render the shared state into text."""

from __future__ import annotations

import string
from functools import lru_cache
from pathlib import Path
from typing import Any, Sequence

from dialogic.memory import Fact, Post

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"
EMPTY = "(none)"


class PromptLibrary:
    def __init__(self, root: str | Path = PROMPTS_DIR):
        self.root = Path(root)

    @lru_cache(maxsize=None)
    def get(self, name: str) -> str:
        return (self.root / f"{name}.txt").read_text(encoding="utf-8").strip()

    def objective(self, name: str) -> str:
        return self.get(f"objectives/{name}")

    def render(self, name: str, **values: Any) -> str:
        template = self.get(name)
        needed = {f for _, f, _, _ in string.Formatter().parse(template) if f}
        if missing := needed - values.keys():
            raise KeyError(f"prompt {name!r} missing values: {sorted(missing)}")
        return template.format_map(values)


def render_thread(thread: Sequence[Post], viewer: str | None = None) -> str:
    if not thread:
        return EMPTY
    blocks = []
    for p in thread:
        who = f"Agent {p.agent}" + (" (you)" if p.agent == viewer else "")
        blocks.append(f"[Turn {p.turn} · {who}]\n{p.text.strip()}")
    return "\n\n".join(blocks)


def render_facts(facts: Sequence[Fact]) -> str:
    if not facts:
        return EMPTY
    lines = []
    for f in facts:
        status = f.status if f.status != "agreed" else f"agreed by {', '.join(sorted(f.confirmed_by))}"
        lines.append(f"{f.id} ({status}; proposed by {f.proposed_by}): {f.text}")
    return "\n".join(lines)


def render_notes(notes: Sequence[str]) -> str:
    if not notes:
        return EMPTY
    return "\n\n".join(f"[Note {i}]\n{n.strip()}" for i, n in enumerate(notes, 1))
