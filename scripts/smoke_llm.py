"""One live call through `LLM`, twice, to check keys, usage parsing, tracing and the cache.

    MODEL=<model> uv run python scripts/smoke_llm.py
"""

import asyncio
import os

from dotenv import load_dotenv

from dialogic.llm import LLM, CallContext, ResponseCache
from dialogic.trace import Tracer


async def main() -> None:
    load_dotenv()
    with Tracer("runs/smoke", "smoke") as tracer:
        llm = LLM(os.environ["MODEL"], tracer=tracer, cache=ResponseCache("runs/.cache.sqlite"))
        ctx = CallContext(problem_id="smoke", method="direct", agent="baseline", space="baseline")
        msgs = [{"role": "user", "content": "What is 17 * 23? Reply with the number only."}]
        for _ in range(2):
            c = await llm.complete(ctx, msgs, max_tokens=256, temperature=None)
            print(f"{c.text!r} cached={c.cached} prompt={c.prompt_tokens} completion={c.completion_tokens} "
                  f"reasoning={c.reasoning_tokens} finish={c.finish_reason} latency={c.latency_s:.2f}s")
        print(llm.usage.snapshot())


if __name__ == "__main__":
    asyncio.run(main())
