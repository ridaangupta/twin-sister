"""OpenAI wrapper: per-agent keys, response cache, retries, concurrency, usage, tracing.

Every call goes through `LLM.complete`, which:
  1. hashes the request and checks the SQLite cache,
  2. otherwise calls the API under a shared semaphore with retries,
  3. records usage per (agent, space) and writes one row to `calls.jsonl`.

Cache hits are traced with `cached=true` and still count toward token usage:
they are free in dollars, not in budget.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sqlite3
import time
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Mapping

import openai
from tenacity import (
    AsyncRetrying,
    retry_if_exception,
    stop_after_attempt,
    wait_random_exponential,
)

from dialogic.trace import Tracer

Messages = list[dict[str, Any]]


@dataclass(frozen=True)
class CallContext:
    problem_id: str
    method: str  # dialogue | direct | cot | self_consistency
    agent: str  # "A" | "B" | "writer" | "synthesizer" | "baseline"
    space: str  # "core" | "scratchpad" | "synthesis" | "baseline"
    turn: int | None = None
    sample_idx: int = 0  # distinguishes otherwise-identical samples in the cache


@dataclass(frozen=True)
class Completion:
    text: str
    prompt_tokens: int
    completion_tokens: int  # includes reasoning tokens
    reasoning_tokens: int
    finish_reason: str | None
    latency_s: float
    cached: bool  # served from our local response cache (no API call)
    system_fingerprint: str | None = None
    prompt_cache_read_tokens: int = 0  # API prompt cache: prompt tokens read from cache (billed at a discount)
    prompt_cache_write_tokens: int = 0  # API prompt cache: prompt tokens written to cache (billed at a premium)

    @property
    def truncated(self) -> bool:
        return self.finish_reason == "length"


# --------------------------------------------------------------------------- keys


def key_slot(agent: str) -> str:
    """Agent B uses its own key; every other caller shares Agent A's."""
    return "B" if agent == "B" else "A"


def resolve_api_key(slot: str, env: Mapping[str, str] | None = None) -> str:
    env = os.environ if env is None else env
    key = env.get(f"OPENAI_API_KEY_{slot}") or env.get("OPENAI_API_KEY")
    if not key:
        raise RuntimeError(f"No API key for agent slot {slot}: set OPENAI_API_KEY_{slot} or OPENAI_API_KEY")
    return key


# -------------------------------------------------------------------------- cache


def _canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def prompt_hash(messages: Messages) -> str:
    return "sha256:" + hashlib.sha256(_canonical(messages).encode()).hexdigest()


def cache_key(model: str, messages: Messages, params: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical({"model": model, "messages": messages, "params": dict(params)}).encode()).hexdigest()


class ResponseCache:
    """SQLite-backed cache of successful completions, keyed by (model, prompt, params)."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(self.path)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("CREATE TABLE IF NOT EXISTS responses (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        self._db.commit()

    def get(self, key: str) -> dict[str, Any] | None:
        row = self._db.execute("SELECT value FROM responses WHERE key = ?", (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def put(self, key: str, value: dict[str, Any]) -> None:
        self._db.execute("INSERT OR REPLACE INTO responses (key, value) VALUES (?, ?)", (key, json.dumps(value)))
        self._db.commit()

    def close(self) -> None:
        self._db.close()


# -------------------------------------------------------------------------- usage


@dataclass
class Usage:
    calls: int = 0
    cached_calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    reasoning_tokens: int = 0
    prompt_cache_read_tokens: int = 0
    prompt_cache_write_tokens: int = 0
    billed_prompt_tokens: int = 0  # everything below excludes local-cache hits
    billed_completion_tokens: int = 0
    billed_prompt_cache_read_tokens: int = 0
    billed_prompt_cache_write_tokens: int = 0

    def add(self, c: Completion) -> None:
        self.calls += 1
        self.prompt_tokens += c.prompt_tokens
        self.completion_tokens += c.completion_tokens
        self.reasoning_tokens += c.reasoning_tokens
        self.prompt_cache_read_tokens += c.prompt_cache_read_tokens
        self.prompt_cache_write_tokens += c.prompt_cache_write_tokens
        if c.cached:
            self.cached_calls += 1
        else:
            self.billed_prompt_tokens += c.prompt_tokens
            self.billed_completion_tokens += c.completion_tokens
            self.billed_prompt_cache_read_tokens += c.prompt_cache_read_tokens
            self.billed_prompt_cache_write_tokens += c.prompt_cache_write_tokens


@dataclass
class UsageTracker:
    by_key: dict[tuple[str, str], Usage] = field(default_factory=lambda: defaultdict(Usage))

    def add(self, ctx: CallContext, c: Completion) -> None:
        self.by_key[(ctx.agent, ctx.space)].add(c)

    def total(self, agent: str | None = None, space: str | None = None) -> Usage:
        out = Usage()
        for (a, s), u in self.by_key.items():
            if (agent is None or a == agent) and (space is None or s == space):
                for k, v in asdict(u).items():
                    setattr(out, k, getattr(out, k) + v)
        return out

    def snapshot(self) -> dict[str, dict[str, int]]:
        return {f"{a}/{s}": asdict(u) for (a, s), u in sorted(self.by_key.items())}


# -------------------------------------------------------------------------- client

_RETRYABLE = (openai.RateLimitError, openai.APITimeoutError, openai.APIConnectionError, openai.InternalServerError)


def _is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, _RETRYABLE):
        return True
    # Sporadic false-positive policy flag on reasoning models; the same prompt passes on retry.
    if isinstance(exc, openai.BadRequestError) and getattr(exc, "code", None) == "invalid_prompt":
        return True
    return isinstance(exc, openai.APIStatusError) and exc.status_code >= 500


class LLM:
    def __init__(
        self,
        model: str,
        *,
        tracer: Tracer | None = None,
        cache: ResponseCache | None = None,
        concurrency: int = 8,
        seed: int | None = None,
        reasoning_effort: str | None = None,
        prompt_cache: str | None = None,
        timeout_s: float = 120.0,
        max_attempts: int = 6,
        retry_wait: Any = None,
        clients: Mapping[str, Any] | None = None,
        env: Mapping[str, str] | None = None,
    ):
        if not model:
            raise ValueError("model must be set in config")
        self.model = model
        self.tracer = tracer
        self.cache = cache
        self.seed = seed
        self.reasoning_effort = reasoning_effort  # None = model default; omitted from the request
        if prompt_cache not in (None, "explicit"):
            raise ValueError("prompt_cache must be null or 'explicit'")
        self.prompt_cache = prompt_cache  # "explicit": send breakpoint markers (GPT-5.6+); None: strip them
        self.timeout_s = timeout_s
        self.max_attempts = max_attempts
        self.retry_wait = retry_wait or wait_random_exponential(multiplier=1, max=60)
        self.usage = UsageTracker()
        self._sem = asyncio.Semaphore(concurrency)
        self._clients: dict[str, Any] = dict(clients or {})
        self._env = env

    @classmethod
    def from_config(cls, cfg: Mapping[str, Any], tracer: Tracer | None = None, cache_path: str | Path = "runs/.cache.sqlite") -> LLM:
        return cls(
            cfg["model"],
            tracer=tracer,
            cache=ResponseCache(cache_path) if cfg.get("cache", True) else None,
            concurrency=cfg.get("concurrency", 8),
            seed=cfg.get("seed"),
            reasoning_effort=cfg.get("reasoning_effort"),
            prompt_cache=cfg.get("prompt_cache"),
            timeout_s=cfg.get("timeout_s", 120.0),
        )

    def _client(self, agent: str) -> Any:
        slot = key_slot(agent)
        if slot not in self._clients:
            # Retries are handled here, not by the SDK, so they are visible and bounded.
            self._clients[slot] = openai.AsyncOpenAI(api_key=resolve_api_key(slot, self._env), max_retries=0, timeout=self.timeout_s)
        return self._clients[slot]

    async def complete(
        self,
        ctx: CallContext,
        messages: Messages,
        *,
        max_tokens: int,
        temperature: float | None = 0.0,
    ) -> Completion:
        params = {"max_tokens": max_tokens, "temperature": temperature, "seed": self.seed, "sample_idx": ctx.sample_idx}
        if self.reasoning_effort is not None:  # only keyed when set, so existing cache entries stay valid
            params["reasoning_effort"] = self.reasoning_effort
        key = cache_key(self.model, messages, params)
        p_hash = prompt_hash(messages)

        hit = self.cache.get(key) if self.cache else None
        if hit is not None:
            completion = Completion(**{**hit, "latency_s": 0.0, "cached": True})
        else:
            completion = await self._call_api(ctx, messages, max_tokens, temperature)
            if self.cache:
                self.cache.put(key, {k: v for k, v in asdict(completion).items() if k not in ("latency_s", "cached")})

        self.usage.add(ctx, completion)
        if self.tracer:
            self.tracer.prompt(p_hash, messages)
            self.tracer.call(
                {
                    **asdict(ctx),
                    "model": self.model,
                    "prompt_hash": p_hash,
                    "max_tokens": max_tokens,
                    "temperature": temperature,
                    "seed": self.seed,
                    "reasoning_effort": self.reasoning_effort,
                    "response": completion.text,
                    "prompt_tokens": completion.prompt_tokens,
                    "completion_tokens": completion.completion_tokens,
                    "reasoning_tokens": completion.reasoning_tokens,
                    "finish_reason": completion.finish_reason,
                    "latency_s": round(completion.latency_s, 3),
                    "cached": completion.cached,
                    "prompt_cache_read_tokens": completion.prompt_cache_read_tokens,
                    "prompt_cache_write_tokens": completion.prompt_cache_write_tokens,
                    "system_fingerprint": completion.system_fingerprint,
                }
            )
        return completion

    async def _call_api(self, ctx: CallContext, messages: Messages, max_tokens: int, temperature: float | None) -> Completion:
        kwargs: dict[str, Any] = {"model": self.model, "messages": self._wire(messages), "max_completion_tokens": max_tokens}
        if self.prompt_cache:
            kwargs["extra_body"] = {"prompt_cache_options": {"mode": self.prompt_cache}}
        if temperature is not None:  # reasoning models reject explicit temperature
            kwargs["temperature"] = temperature
        if self.seed is not None:
            kwargs["seed"] = self.seed
        if self.reasoning_effort is not None:
            kwargs["reasoning_effort"] = self.reasoning_effort
        client = self._client(ctx.agent)

        async with self._sem:
            async for attempt in AsyncRetrying(
                retry=retry_if_exception(_is_retryable),
                stop=stop_after_attempt(self.max_attempts),
                wait=self.retry_wait,
                reraise=True,
            ):
                with attempt:
                    t0 = time.perf_counter()
                    resp = await client.chat.completions.create(**kwargs)
                    latency = time.perf_counter() - t0

        choice = resp.choices[0]
        usage = resp.usage
        details = getattr(usage, "completion_tokens_details", None)
        pdetails = getattr(usage, "prompt_tokens_details", None)
        return Completion(
            text=choice.message.content or "",
            prompt_tokens=usage.prompt_tokens,
            completion_tokens=usage.completion_tokens,
            reasoning_tokens=(getattr(details, "reasoning_tokens", None) or 0) if details else 0,
            finish_reason=choice.finish_reason,
            latency_s=latency,
            cached=False,
            system_fingerprint=getattr(resp, "system_fingerprint", None),
            prompt_cache_read_tokens=(getattr(pdetails, "cached_tokens", None) or 0) if pdetails else 0,
            prompt_cache_write_tokens=(getattr(pdetails, "cache_write_tokens", None) or 0) if pdetails else 0,
        )

    def _wire(self, messages: Messages) -> Messages:
        """Messages as sent: cache breakpoint markers kept only when explicit prompt caching is on."""
        if self.prompt_cache:
            return messages
        out = []
        for m in messages:
            c = m["content"]
            if isinstance(c, list):
                c = [{k: v for k, v in b.items() if k != "prompt_cache_breakpoint"} for b in c]
            out.append({**m, "content": c})
        return out
