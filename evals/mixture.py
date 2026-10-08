"""Seeded per-problem mixtures of two settings, for matching a cost that a discrete knob cannot hit.

A baseline whose cost moves in steps (7 vs 8 samples, effort low vs medium, k vs k+1 attempts) uses
`high` on a fraction `p_high` of problems and `low` on the rest, so its MEAN cost matches a target.
The choice depends only on (salt, problem id), so it is identical across reruns and independent of
async ordering, and two different mixtures (different salts) are independent of each other.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Generic, Mapping, TypeVar

T = TypeVar("T")


def unit_hash(salt: str, problem_id: str) -> float:
    """Deterministic value in [0, 1) for (salt, problem)."""
    digest = hashlib.sha256(f"{salt}:{problem_id}".encode()).digest()
    return int.from_bytes(digest[:8], "big") / 2**64


@dataclass(frozen=True)
class Mixture(Generic[T]):
    low: T
    high: T
    p_high: float
    salt: str

    def __post_init__(self) -> None:
        if not 0.0 <= self.p_high <= 1.0:
            raise ValueError("p_high must be in [0, 1]")

    def pick(self, problem_id: str) -> T:
        return self.high if unit_hash(self.salt, problem_id) < self.p_high else self.low

    @classmethod
    def from_config(cls, cfg: Mapping[str, Any] | Any, salt: str) -> "Mixture":
        """A plain value means no mixture; {low, high, p_high} means a mixture."""
        if isinstance(cfg, Mapping):
            return cls(cfg["low"], cfg["high"], float(cfg["p_high"]), salt)
        return cls(cfg, cfg, 0.0, salt)


def solve_p_high(cost_low: float, cost_high: float, target: float) -> float:
    """Share of problems on `high` so the expected cost equals `target` (clipped to [0, 1])."""
    if cost_high == cost_low:
        return 0.0
    return min(1.0, max(0.0, (target - cost_low) / (cost_high - cost_low)))
