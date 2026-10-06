"""Phase 1 controller: fixed budgets from config, stop on mutual consensus or max turns."""

from __future__ import annotations

import hashlib
from typing import Any, Mapping, Sequence

from dialogic.controller.base import ControllerState, TurnController, TurnDecision


def _pick(choices: Sequence[int], seed: int, problem_id: str, turn: int) -> int:
    # Keyed on (seed, problem, turn) rather than a shared RNG, so the choice does not
    # depend on how concurrent problems interleave.
    digest = hashlib.sha256(f"{seed}:{problem_id}:{turn}".encode()).digest()
    return choices[int.from_bytes(digest[:8], "big") % len(choices)]


class HeuristicController(TurnController):
    def __init__(
        self,
        *,
        max_turns: int,
        soft_limit: int = 300,
        scratch_budget: int = 0,
        soft_limit_choices: Sequence[int] | None = None,
        seed: int = 0,
    ):
        if max_turns < 1:
            raise ValueError("max_turns must be >= 1")
        self.max_turns = max_turns
        self.soft_limit = soft_limit
        self.scratch_budget = scratch_budget
        self.soft_limit_choices = tuple(soft_limit_choices) if soft_limit_choices else None
        self.seed = seed

    @classmethod
    def from_config(cls, cfg: Mapping[str, Any], seed: int = 0) -> HeuristicController:
        return cls(
            max_turns=cfg["max_turns"],
            soft_limit=cfg.get("soft_limit", 300),
            scratch_budget=cfg.get("scratch_budget", 0),
            soft_limit_choices=cfg.get("soft_limit_choices"),
            seed=seed,
        )

    def decide(self, state: ControllerState) -> TurnDecision:
        if state.turn >= self.max_turns:
            stop, reason = True, "max_turns"
        elif state.mutual_consensus:
            stop, reason = True, "consensus"
        else:
            stop, reason = False, "continue"

        if self.soft_limit_choices:
            soft_limit = _pick(self.soft_limit_choices, self.seed, state.problem_id, state.turn)
        else:
            soft_limit = self.soft_limit
        return TurnDecision(soft_limit, self.scratch_budget, stop, float(stop), reason)
