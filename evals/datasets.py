"""Common dataset interface. Loaders (GSM8K, later FinQA) return lists of `Problem`."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Problem:
    id: str
    question: str
    gold: str  # normalized gold answer
    meta: dict[str, Any] = field(default_factory=dict)
