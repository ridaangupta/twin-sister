"""Load prompt templates from /prompts and render the shared state into text.

Prompts are laid out for prompt caching: a stable prefix of content blocks (problem,
instructions, then an append-only log), each marked as a cache breakpoint, followed by
a short volatile tail (ledger state and the mode line). The LLM wrapper sends or strips
the breakpoint markers depending on config.
"""

from __future__ import annotations

import string
from functools import lru_cache
from pathlib import Path
from typing import Any, Sequence

from dialogic.memory import Fact, Note, Post

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"
EMPTY = "(none)"
BREAKPOINT_KEY = "prompt_cache_breakpoint"

Message = dict[str, Any]


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


# ------------------------------------------------------------------ blocks


def block(text: str, cache: bool = True) -> dict[str, Any]:
    """One content block; `cache` marks the end of a reusable prefix."""
    b: dict[str, Any] = {"type": "text", "text": text}
    if cache:
        b[BREAKPOINT_KEY] = {"mode": "explicit"}
    return b


def text_of(messages: Sequence[Message]) -> str:
    """Flatten messages (string or block content) to plain text, for tests and analysis."""
    out = []
    for m in messages:
        c = m["content"]
        out.append(c if isinstance(c, str) else "\n\n".join(b["text"] for b in c))
    return "\n\n".join(out)


def problem_block(task: str, cache: bool = True) -> dict[str, Any]:
    return block(f"PROBLEM:\n{task}", cache)


def post_text(p: Post, viewer: str | None = None) -> str:
    who = f"Agent {p.agent}" + (" (you)" if p.agent == viewer else "")
    return f"[Turn {p.turn} · {who}]\n{p.text.strip()}"


def note_text(turn: int, text: str) -> str:
    return f"[Your private note, before your post for turn {turn}]\n{text.strip()}"


def log_blocks(thread: Sequence[Post], notes: Sequence[Note], viewer: str | None = None, cache: bool = True) -> list[dict[str, Any]]:
    """Posts and the viewer's own notes in the order the viewer saw or wrote them.

    A note sits right after the posts that existed when it was written, so the log only ever
    grows at the end (also with parallel opening turns) and every earlier block stays a
    cacheable prefix.
    """
    entries = [((i, 1), post_text(p, viewer)) for i, p in enumerate(thread)]
    entries += [((n.seen, 0), note_text(n.turn, n.text)) for n in notes]
    return [block(text, cache) for _, text in sorted(entries, key=lambda e: e[0])]


# ------------------------------------------------------------------ plain renderers


def render_thread(thread: Sequence[Post], viewer: str | None = None) -> str:
    return "\n\n".join(post_text(p, viewer) for p in thread) if thread else EMPTY


def render_facts(facts: Sequence[Fact]) -> str:
    if not facts:
        return EMPTY
    lines = []
    for f in facts:
        status = f.status if f.status != "agreed" else f"agreed by {', '.join(sorted(f.confirmed_by))}"
        lines.append(f"{f.id} ({status}; proposed by {f.proposed_by}): {f.text}")
    return "\n".join(lines)
