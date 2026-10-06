from typing import Any, Mapping

from dialogic.controller.base import ControllerState, TurnController, TurnDecision
from dialogic.controller.heuristic import HeuristicController

__all__ = ["ControllerState", "TurnController", "TurnDecision", "HeuristicController", "make_controller"]


def make_controller(cfg: Mapping[str, Any], seed: int = 0) -> TurnController:
    kind = cfg.get("type", "heuristic")
    if kind == "heuristic":
        return HeuristicController.from_config(cfg, seed=seed)
    raise ValueError(f"unknown controller type {kind!r}")
