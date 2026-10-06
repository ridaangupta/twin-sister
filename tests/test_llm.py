import json
from types import SimpleNamespace

import openai

try:  # openai>=3 ships httpx2; older releases use httpx
    import httpx2 as httpx
except ImportError:
    import httpx
import pytest
from tenacity import wait_none

from dialogic.llm import (
    LLM,
    CallContext,
    ResponseCache,
    cache_key,
    key_slot,
    resolve_api_key,
)
from dialogic.trace import Tracer

MSGS = [{"role": "user", "content": "What is 2+2?"}]


def _response(text="4", prompt_tokens=10, completion_tokens=3, reasoning_tokens=0, finish_reason="stop"):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=text), finish_reason=finish_reason)],
        usage=SimpleNamespace(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            completion_tokens_details=SimpleNamespace(reasoning_tokens=reasoning_tokens),
        ),
        system_fingerprint="fp_test",
    )


class FakeClient:
    """Mimics `AsyncOpenAI` far enough for `LLM`: `client.chat.completions.create(**kw)`."""

    def __init__(self, *outcomes):
        self.outcomes = list(outcomes) or [_response()]
        self.calls = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    async def _create(self, **kwargs):
        self.calls.append(kwargs)
        out = self.outcomes.pop(0) if len(self.outcomes) > 1 else self.outcomes[0]
        if isinstance(out, BaseException):
            raise out
        return out


def _rate_limit_error():
    req = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
    return openai.RateLimitError("rate limited", response=httpx.Response(429, request=req), body=None)


def ctx(**kw):
    return CallContext(**{"problem_id": "p1", "method": "dialogue", "agent": "A", "space": "core", "turn": 0, **kw})


@pytest.fixture
def cache(tmp_path):
    c = ResponseCache(tmp_path / "cache.sqlite")
    yield c
    c.close()


# ---------------------------------------------------------------- keys


def test_key_slot_and_fallback():
    assert key_slot("A") == "A"
    assert key_slot("B") == "B"
    assert key_slot("writer") == key_slot("baseline") == "A"
    assert resolve_api_key("A", {"OPENAI_API_KEY": "shared"}) == "shared"
    assert resolve_api_key("B", {"OPENAI_API_KEY": "shared", "OPENAI_API_KEY_B": "b"}) == "b"
    with pytest.raises(RuntimeError):
        resolve_api_key("A", {})


async def test_agents_use_separate_clients(cache):
    a, b = FakeClient(), FakeClient()
    llm = LLM("m", cache=cache, clients={"A": a, "B": b})
    await llm.complete(ctx(agent="A"), MSGS, max_tokens=16)
    await llm.complete(ctx(agent="B"), MSGS + [{"role": "user", "content": "again"}], max_tokens=16)
    assert len(a.calls) == 1 and len(b.calls) == 1


# ---------------------------------------------------------------- cache


def test_cache_key_depends_on_every_input():
    base = cache_key("m", MSGS, {"max_tokens": 16, "temperature": 0.0, "seed": 0, "sample_idx": 0})
    assert base == cache_key("m", MSGS, {"sample_idx": 0, "seed": 0, "temperature": 0.0, "max_tokens": 16})
    assert base != cache_key("m2", MSGS, {"max_tokens": 16, "temperature": 0.0, "seed": 0, "sample_idx": 0})
    assert base != cache_key("m", MSGS, {"max_tokens": 32, "temperature": 0.0, "seed": 0, "sample_idx": 0})
    assert base != cache_key("m", MSGS, {"max_tokens": 16, "temperature": 0.7, "seed": 0, "sample_idx": 0})
    assert base != cache_key("m", MSGS, {"max_tokens": 16, "temperature": 0.0, "seed": 0, "sample_idx": 1})
    assert base != cache_key("m", [{"role": "user", "content": "x"}], {"max_tokens": 16, "temperature": 0.0, "seed": 0, "sample_idx": 0})


async def test_second_identical_call_is_served_from_cache(cache):
    client = FakeClient(_response("4", 10, 3))
    llm = LLM("m", cache=cache, clients={"A": client})

    first = await llm.complete(ctx(), MSGS, max_tokens=16)
    second = await llm.complete(ctx(turn=5), MSGS, max_tokens=16)  # ctx metadata is not part of the key

    assert len(client.calls) == 1
    assert not first.cached and second.cached
    assert second.text == first.text == "4"
    assert (second.prompt_tokens, second.completion_tokens) == (10, 3)


async def test_sample_idx_bypasses_cache(cache):
    client = FakeClient(_response("4"), _response("5"))
    llm = LLM("m", cache=cache, clients={"A": client})
    r0 = await llm.complete(ctx(sample_idx=0), MSGS, max_tokens=16, temperature=0.7)
    r1 = await llm.complete(ctx(sample_idx=1), MSGS, max_tokens=16, temperature=0.7)
    assert len(client.calls) == 2
    assert (r0.text, r1.text) == ("4", "5")


async def test_cache_persists_across_instances(tmp_path):
    path = tmp_path / "cache.sqlite"
    c1 = ResponseCache(path)
    await LLM("m", cache=c1, clients={"A": FakeClient(_response("42"))}).complete(ctx(), MSGS, max_tokens=16)
    c1.close()

    c2 = ResponseCache(path)
    client = FakeClient()
    r = await LLM("m", cache=c2, clients={"A": client}).complete(ctx(), MSGS, max_tokens=16)
    c2.close()
    assert r.cached and r.text == "42" and client.calls == []


async def test_failed_calls_are_not_cached(cache):
    client = FakeClient(openai.BadRequestError("bad", response=httpx.Response(400, request=httpx.Request("POST", "http://x")), body=None))
    llm = LLM("m", cache=cache, clients={"A": client})
    with pytest.raises(openai.BadRequestError):
        await llm.complete(ctx(), MSGS, max_tokens=16)
    assert cache.get(cache_key("m", MSGS, {"max_tokens": 16, "temperature": 0.0, "seed": None, "sample_idx": 0})) is None


# ---------------------------------------------------------------- retries & request shape


async def test_retries_rate_limit_then_succeeds():
    client = FakeClient(_rate_limit_error(), _rate_limit_error(), _response("ok"))
    llm = LLM("m", clients={"A": client}, retry_wait=wait_none())
    r = await llm.complete(ctx(), MSGS, max_tokens=16)
    assert r.text == "ok" and len(client.calls) == 3


async def test_gives_up_after_max_attempts():
    client = FakeClient(_rate_limit_error())
    llm = LLM("m", clients={"A": client}, retry_wait=wait_none(), max_attempts=3)
    with pytest.raises(openai.RateLimitError):
        await llm.complete(ctx(), MSGS, max_tokens=16)
    assert len(client.calls) == 3


async def test_request_kwargs():
    client = FakeClient()
    await LLM("m", seed=7, clients={"A": client}).complete(ctx(), MSGS, max_tokens=99, temperature=0.3)
    assert client.calls[0] == {"model": "m", "messages": MSGS, "max_completion_tokens": 99, "temperature": 0.3, "seed": 7}

    client = FakeClient()
    await LLM("m", clients={"A": client}).complete(ctx(), MSGS, max_tokens=99, temperature=None)
    assert "temperature" not in client.calls[0] and "seed" not in client.calls[0]


async def test_reasoning_tokens_and_truncation():
    client = FakeClient(_response("partial", completion_tokens=50, reasoning_tokens=30, finish_reason="length"))
    r = await LLM("m", clients={"A": client}).complete(ctx(), MSGS, max_tokens=50)
    assert r.reasoning_tokens == 30 and r.completion_tokens == 50 and r.truncated


# ---------------------------------------------------------------- usage & tracing


async def test_usage_counts_cache_hits_but_does_not_bill_them(cache):
    llm = LLM("m", cache=cache, clients={"A": FakeClient(_response("4", 10, 3))})
    await llm.complete(ctx(space="scratchpad"), MSGS, max_tokens=16)
    await llm.complete(ctx(space="scratchpad"), MSGS, max_tokens=16)
    await llm.complete(ctx(space="core"), MSGS, max_tokens=32)

    pad = llm.usage.total(agent="A", space="scratchpad")
    assert (pad.calls, pad.cached_calls, pad.completion_tokens, pad.billed_completion_tokens) == (2, 1, 6, 3)
    assert llm.usage.total(space="core").completion_tokens == 3
    assert llm.usage.total().completion_tokens == 9
    assert set(llm.usage.snapshot()) == {"A/core", "A/scratchpad"}


async def test_every_call_is_traced(tmp_path, cache):
    with Tracer(tmp_path / "run", "run-1") as tracer:
        llm = LLM("m", tracer=tracer, cache=cache, clients={"A": FakeClient(_response("4")), "B": FakeClient(_response("5"))})
        await llm.complete(ctx(agent="A", turn=0), MSGS, max_tokens=16)
        await llm.complete(ctx(agent="A", turn=1), MSGS, max_tokens=16)  # cache hit, same prompt
        await llm.complete(ctx(agent="B", turn=2, space="scratchpad"), [{"role": "user", "content": "hi"}], max_tokens=16)

    calls = [json.loads(l) for l in (tmp_path / "run" / "calls.jsonl").read_text().splitlines()]
    prompts = [json.loads(l) for l in (tmp_path / "run" / "prompts.jsonl").read_text().splitlines()]

    assert [c["cached"] for c in calls] == [False, True, False]
    assert [(c["agent"], c["space"], c["turn"]) for c in calls] == [("A", "core", 0), ("A", "core", 1), ("B", "scratchpad", 2)]
    required = {"run_id", "problem_id", "turn", "agent", "space", "prompt_hash", "response", "prompt_tokens", "completion_tokens", "latency_s"}
    assert all(required <= c.keys() for c in calls)
    assert all(c["run_id"] == "run-1" for c in calls)
    assert len(prompts) == 2  # deduplicated by hash
    assert calls[0]["prompt_hash"] == calls[1]["prompt_hash"] == prompts[0]["prompt_hash"]


def test_model_required():
    with pytest.raises(ValueError):
        LLM("")
