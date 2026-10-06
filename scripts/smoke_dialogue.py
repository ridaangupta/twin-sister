"""Run one live dialogue end to end and print the thread, to eyeball prompts and protocol compliance.

    uv run python scripts/smoke_dialogue.py
Traces go to runs/smoke_dialogue/.
"""

import asyncio
import os

from dotenv import load_dotenv

from dialogic.llm import LLM
from dialogic.orchestrator import DialogueRunner
from dialogic.trace import Tracer
from evals.datasets import Problem

PROBLEM = Problem(
    "smoke-1",
    "Janet's ducks lay 16 eggs per day. She eats three for breakfast every morning and bakes muffins for her "
    "friends every day with four. She sells the remainder at the farmers' market daily for $2 per fresh duck egg. "
    "How much in dollars does she make every day at the farmers' market?",
    "18",
)


async def main() -> None:
    load_dotenv()
    cfg = {
        "model": os.environ["MODEL"],
        "seed": 0,
        "temperature": float(os.environ["TEMPERATURE"]) if os.environ.get("TEMPERATURE") else None,
        "first_speaker": "seeded",
        "agents": {"A": {"objective": "accuracy"}, "B": {"objective": "simplicity"}},
        "controller": {"type": "heuristic", "max_turns": 6, "soft_limit": 250, "scratch_budget": 200, "k": 2.0},
        "synthesis": {"type": "single_writer", "writer": "A"},
    }
    with Tracer("runs/smoke_dialogue", "smoke_dialogue") as tracer:
        llm = LLM.from_config(cfg, tracer)
        r = (await DialogueRunner.from_config(cfg, llm, tracer).run_all([PROBLEM]))[0]

    print(f"stop={r.stop_reason} turns={r.turns} first={r.first_speaker} answer={r.final.answer} "
          f"gold={r.gold} correct={r.correct} protocol_errors={r.protocol_errors}")
    print(f"tokens={r.tokens}  ledger agreed/total={r.ledger_agreed}/{r.ledger_total}")
    print(f"answers per turn: {r.answer_trajectory}")
    print("\n--- final ---\n" + r.final.text)
    print("\nFull thread: runs/smoke_dialogue/calls.jsonl (one row per call)")


if __name__ == "__main__":
    asyncio.run(main())
