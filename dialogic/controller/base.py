"""Turn-controller interface shared by the heuristic, learned and RL controllers.

The orchestrator only ever calls `controller.decide(state)` before each post and
`state.after(...)` after it, so swapping controller phases never touches it.
`ControllerState.features()` is the Phase 2 feature vector.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field, replace
from types import MappingProxyType
from typing import Mapping

from dialogic.memory import LedgerDelta, Post

_STANCES = ("agree", "disagree", "unsure")
DISAGREE_WINDOW = 4


def _frozen(d: Mapping) -> Mapping:
    return MappingProxyType(dict(d))


@dataclass(frozen=True)
class ControllerState:
    problem_id: str
    agent_ids: tuple[str, ...]
    max_turns: int
    turn: int = 0  # index of the next post == number of posts so far
    core_tokens: int = 0
    scratch_tokens: int = 0
    last_post_tokens: int = 0
    answers: Mapping[str, str | None] = field(default_factory=dict)  # latest ANSWER per agent
    last_known: Mapping[str, str | None] = field(default_factory=dict)  # latest non-None ANSWER
    consensus: Mapping[str, bool] = field(default_factory=dict)
    stances: tuple[str, ...] = ()
    answer_changes: Mapping[str, int] = field(default_factory=dict)
    last_change_turn: int | None = None
    ledger_agreed: int = 0
    ledger_delta: int = 0
    ledger_disputes: int = 0

    @classmethod
    def initial(cls, problem_id: str, agent_ids: tuple[str, ...] | list[str], max_turns: int) -> ControllerState:
        ids = tuple(agent_ids)
        return cls(
            problem_id=problem_id,
            agent_ids=ids,
            max_turns=max_turns,
            answers=_frozen({a: None for a in ids}),
            last_known=_frozen({a: None for a in ids}),
            consensus=_frozen({a: False for a in ids}),
            answer_changes=_frozen({a: 0 for a in ids}),
        )

    def after(self, post: Post, delta: LedgerDelta, *, ledger_agreed: int, scratch_tokens: int = 0) -> ControllerState:
        """State after `post` (and any scratchpad work that preceded it) is appended to core."""
        prev = self.last_known[post.agent]
        changed = prev is not None and post.answer is not None and post.answer != prev
        changes = dict(self.answer_changes)
        changes[post.agent] += int(changed)
        return replace(
            self,
            turn=self.turn + 1,
            core_tokens=self.core_tokens + post.completion_tokens,
            scratch_tokens=self.scratch_tokens + scratch_tokens,
            last_post_tokens=post.completion_tokens,
            answers=_frozen({**self.answers, post.agent: post.answer}),
            last_known=_frozen({**self.last_known, post.agent: post.answer if post.answer is not None else prev}),
            consensus=_frozen({**self.consensus, post.agent: post.consensus}),
            stances=self.stances + (post.stance,),
            answer_changes=_frozen(changes),
            last_change_turn=post.turn if changed else self.last_change_turn,
            ledger_agreed=ledger_agreed,
            ledger_delta=delta.size,
            ledger_disputes=self.ledger_disputes + len(delta.disputed),
        )

    # ------------------------------------------------------------------ derived signals

    @property
    def all_answered(self) -> bool:
        return all(self.answers[a] is not None for a in self.agent_ids)

    @property
    def answers_agree(self) -> bool:
        return self.all_answered and len({self.answers[a] for a in self.agent_ids}) == 1

    @property
    def mutual_consensus(self) -> bool:
        """Every agent's latest post says CONSENSUS: yes, with the same non-empty answer."""
        return self.answers_agree and all(self.consensus[a] for a in self.agent_ids)

    def features(self) -> dict[str, float]:
        """Phase 2 controller inputs. Key order is stable; add new keys at the end."""
        last_stance = self.stances[-1] if self.stances else None
        since_change = self.turn - (self.last_change_turn + 1 if self.last_change_turn is not None else 0)
        f: dict[str, float] = {
            "turn": self.turn,
            "turn_frac": self.turn / self.max_turns if self.max_turns else 0.0,
            "core_tokens": self.core_tokens,
            "scratch_tokens": self.scratch_tokens,
            "last_post_tokens": self.last_post_tokens,
            "answers_agree": float(self.answers_agree),
            "all_answered": float(self.all_answered),
            "turns_since_answer_change": since_change,
            "disagree_recent": sum(s == "disagree" for s in self.stances[-DISAGREE_WINDOW:]),
            "ledger_agreed": self.ledger_agreed,
            "ledger_delta": self.ledger_delta,
            "ledger_disputes": self.ledger_disputes,
        }
        for s in _STANCES:
            f[f"last_stance_{s}"] = float(last_stance == s)
        for a in self.agent_ids:
            f[f"answer_changes_{a}"] = self.answer_changes[a]
            f[f"consensus_{a}"] = float(self.consensus[a])
        return f


@dataclass(frozen=True)
class TurnDecision:
    soft_limit: int  # target length for the next post, in tokens
    scratch_budget: int  # private work budget before the next post; 0 = skip
    stop: bool
    stop_prob: float
    reason: str  # "continue" | "consensus" | "max_turns" | controller-specific


class TurnController(ABC):
    @abstractmethod
    def decide(self, state: ControllerState) -> TurnDecision:
        """Called before every post. Must be a pure function of `state` (plus fixed config/seed)."""
