"""Single-agent baselines at matched generated-token budget (same model, same LLM wrapper).

- direct: answer only.
- cot: step by step, max_tokens = budget B (the prompt states B; real usage is reported).
- self_consistency: n = max(min_samples, round(B / mean CoT tokens)) CoT samples at
  temperature > 0, per-sample cap = cot cap, majority vote (ties -> earliest sample).
  `sc_samples` fixes n instead (e.g. to match the dialogue's cost rather than its tokens).
- two_plus_judge: two independent CoT samples (as in SC); if their answers match, accept;
  otherwise one judge call sees both attempts and produces the answer. The structural analog
  of the dialogue (independent openings + reconciliation) without any back-and-forth.
"""

from __future__ import annotations

import asyncio
from collections import Counter
from dataclasses import dataclass, field
from statistics import mean
from typing import Any, Mapping, Sequence

from dialogic.llm import LLM, CallContext
from evals.mixture import Mixture
from dialogic.prompts import PromptLibrary
from dialogic.protocol import extract_answer
from dialogic.trace import Tracer
from evals.datasets import Problem


@dataclass
class BaselineResult:
    method: str
    problem_id: str
    gold: str
    final_answer: str | None
    final_text: str
    correct: bool
    tokens: dict[str, int]  # generated, prompt
    n_samples: int = 1
    sample_answers: list[str | None] = field(default_factory=list)
    truncated: int = 0  # samples cut off at the cap
    judged: bool | None = None  # judge baselines: whether the attempts disagreed and the judge was called
    setting: str | None = None  # the per-problem setting a mixture picked (sample count, k, effort)

    def row(self) -> dict[str, Any]:
        return dict(self.__dict__)


def majority_vote(answers: Sequence[str | None]) -> str | None:
    counts = Counter(a for a in answers if a is not None)
    if not counts:
        return None
    top = max(counts.values())
    return next(a for a in answers if a is not None and counts[a] == top)


class Baselines:
    def __init__(self, llm: LLM, prompts: PromptLibrary | None = None, tracer: Tracer | None = None, *, temperature: float | None = 0.0):
        self.llm = llm
        self.prompts = prompts or PromptLibrary()
        self.tracer = tracer
        self.temperature = temperature

    def _msgs(self, name: str, **kw: Any) -> list[dict[str, str]]:
        return [{"role": "user", "content": self.prompts.render(name, **kw)}]

    def _ctx(self, method: str, p: Problem, sample_idx: int = 0) -> CallContext:
        return CallContext(problem_id=p.id, method=method, agent="baseline", space="baseline", sample_idx=sample_idx)

    async def direct(self, p: Problem, max_tokens: int = 32) -> BaselineResult:
        c = await self.llm.complete(self._ctx("direct", p), self._msgs("baseline_direct", task=p.question), max_tokens=max_tokens, temperature=self.temperature)
        ans = extract_answer(c.text)
        return BaselineResult("direct", p.id, p.gold, ans, c.text, ans == p.gold,
                              {"generated": c.completion_tokens, "prompt": c.prompt_tokens}, 1, [ans], int(c.truncated))

    async def cot(self, p: Problem, budget: int) -> BaselineResult:
        c = await self.llm.complete(self._ctx("cot", p), self._msgs("baseline_cot", task=p.question, budget=budget), max_tokens=budget, temperature=self.temperature)
        ans = extract_answer(c.text)
        return BaselineResult("cot", p.id, p.gold, ans, c.text, ans == p.gold,
                              {"generated": c.completion_tokens, "prompt": c.prompt_tokens}, 1, [ans], int(c.truncated))

    async def self_consistency(self, p: Problem, n: int | Mixture, sample_budget: int, temperature: float = 0.7) -> BaselineResult:
        mixed = isinstance(n, Mixture)
        n = n.pick(p.id) if mixed else n
        msgs = self._msgs("baseline_cot", task=p.question, budget=sample_budget)
        cs = await asyncio.gather(*(
            self.llm.complete(self._ctx("self_consistency", p, i), msgs, max_tokens=sample_budget, temperature=temperature) for i in range(n)
        ))
        answers = [extract_answer(c.text) for c in cs]
        ans = majority_vote(answers)
        return BaselineResult(
            "self_consistency", p.id, p.gold, ans, cs[0].text, ans == p.gold,
            {"generated": sum(c.completion_tokens for c in cs), "prompt": sum(c.prompt_tokens for c in cs)},
            n, answers, sum(c.truncated for c in cs), setting=f"n={n}" if mixed else None,
        )

    async def reasoning(self, p: Problem, effort: str | Mixture, max_tokens: int, prompt: str = "baseline_cot_free",
                        samples: int | Mixture = 1) -> BaselineResult:
        """Hidden reasoning on (WS3b): one call, or a majority vote over `samples` calls. Either knob may be a
        per-problem mixture. Draw i is cached under sample_idx i, so n = 1..N reuse the same draws."""
        level = effort.pick(p.id) if isinstance(effort, Mixture) else effort
        n = samples.pick(p.id) if isinstance(samples, Mixture) else samples
        msgs = self._msgs(prompt, task=p.question, budget=max_tokens)
        cs = await asyncio.gather(*(
            self.llm.complete(self._ctx("reasoning", p, i), msgs, max_tokens=max_tokens, temperature=None, reasoning_effort=level)
            for i in range(n)
        ))
        answers = [extract_answer(c.text) for c in cs]
        ans = majority_vote(answers) if n > 1 else answers[0]
        return BaselineResult("reasoning", p.id, p.gold, ans, cs[0].text, ans == p.gold,
                              {"generated": sum(c.completion_tokens for c in cs), "prompt": sum(c.prompt_tokens for c in cs),
                               "reasoning": sum(c.reasoning_tokens for c in cs)},
                              n, answers, sum(c.truncated for c in cs), setting=f"{level} n={n}" if n > 1 or isinstance(samples, Mixture) else level)

    async def k_plus_judge(self, p: Problem, k: int | Mixture, sample_budget: int, judge_budget: int, temperature: float = 0.7) -> BaselineResult:
        """k independent CoT attempts (SC's first k draws) + one judge seeing all k when any disagree (WS3c)."""
        mixed = isinstance(k, Mixture)
        k = k.pick(p.id) if mixed else k
        msgs = self._msgs("baseline_cot", task=p.question, budget=sample_budget)
        cs = await asyncio.gather(*(
            self.llm.complete(self._ctx("k_plus_judge", p, i), msgs, max_tokens=sample_budget, temperature=temperature) for i in range(k)
        ))
        answers = [extract_answer(c.text) for c in cs]
        gen, prompt = sum(c.completion_tokens for c in cs), sum(c.prompt_tokens for c in cs)
        judged = not (answers[0] is not None and all(a == answers[0] for a in answers))
        text, ans = cs[0].text, answers[0]
        if judged:
            attempts = "\n\n".join(f"ATTEMPT {i + 1}:\n{c.text.strip()}" for i, c in enumerate(cs))
            jmsgs = self._msgs("baseline_judge_k", task=p.question, k=k, attempts=attempts, budget=judge_budget)
            j = await self.llm.complete(self._ctx("k_plus_judge", p, sample_idx=1000), jmsgs, max_tokens=judge_budget, temperature=self.temperature)
            text, ans = j.text, extract_answer(j.text)
            gen += j.completion_tokens
            prompt += j.prompt_tokens
        return BaselineResult("k_plus_judge", p.id, p.gold, ans, text, ans == p.gold, {"generated": gen, "prompt": prompt}, k,
                              answers, sum(c.truncated for c in cs), judged, setting=f"k={k}" if mixed else None)

    async def two_plus_judge(self, p: Problem, sample_budget: int, judge_budget: int, temperature: float = 0.7) -> BaselineResult:
        msgs = self._msgs("baseline_cot", task=p.question, budget=sample_budget)
        # sample_idx 0/1 with SC's prompt and temperature: the same two draws as SC's first two samples
        # (the response cache key ignores the method label, so these replay when SC already ran).
        cs = await asyncio.gather(*(
            self.llm.complete(self._ctx("two_plus_judge", p, i), msgs, max_tokens=sample_budget, temperature=temperature) for i in range(2)
        ))
        answers = [extract_answer(c.text) for c in cs]
        gen = sum(c.completion_tokens for c in cs)
        prompt = sum(c.prompt_tokens for c in cs)
        judged = not (answers[0] is not None and answers[0] == answers[1])
        text, ans = cs[0].text, answers[0]
        if judged:
            jmsgs = self._msgs("baseline_judge", task=p.question, attempt_1=cs[0].text, attempt_2=cs[1].text, budget=judge_budget)
            j = await self.llm.complete(self._ctx("two_plus_judge", p, sample_idx=2), jmsgs, max_tokens=judge_budget, temperature=self.temperature)
            text, ans = j.text, extract_answer(j.text)
            gen += j.completion_tokens
            prompt += j.prompt_tokens
        return BaselineResult("two_plus_judge", p.id, p.gold, ans, text, ans == p.gold, {"generated": gen, "prompt": prompt}, 2,
                              answers, sum(c.truncated for c in cs), judged)

    async def run(self, method: str, problems: Sequence[Problem], **kw: Any) -> list[BaselineResult]:
        fn = {"direct": self.direct, "cot": self.cot, "self_consistency": self.self_consistency, "two_plus_judge": self.two_plus_judge,
              "reasoning": self.reasoning, "k_plus_judge": self.k_plus_judge}[method]

        async def one(p: Problem) -> BaselineResult | None:
            try:
                r = await fn(p, **kw)
            except Exception as e:  # one failed problem must not sink the run
                if self.tracer:
                    self.tracer.record("errors", {"method": method, "problem_id": p.id, "error": repr(e)})
                return None
            if self.tracer:
                self.tracer.problem(r.row())
            return r

        return [r for r in await asyncio.gather(*(one(p) for p in problems)) if r is not None]


def sc_num_samples(budget: int, cot_tokens_mean: float, min_samples: int = 3) -> int:
    return max(min_samples, round(budget / max(cot_tokens_mean, 1.0)))


async def run_baselines(
    cfg: Mapping[str, Any], problems: Sequence[Problem], budget: int, llm: LLM, tracer: Tracer | None = None
) -> tuple[dict[str, list[BaselineResult]], dict[str, Any]]:
    """Run the configured baselines in order. SC sizes itself from the CoT run's measured tokens."""
    bcfg = cfg.get("baselines", {})
    methods = bcfg.get("methods", ["direct", "cot", "self_consistency"])
    b = Baselines(llm, tracer=tracer, temperature=cfg.get("temperature", 0.0))
    results: dict[str, list[BaselineResult]] = {}
    info: dict[str, Any] = {"budget": budget}

    for m in methods:
        if m == "direct":
            results[m] = await b.run("direct", problems, max_tokens=bcfg.get("direct_max_tokens", 32))
        elif m == "cot":
            results[m] = await b.run("cot", problems, budget=budget)
        elif m == "self_consistency":
            ref = bcfg.get("cot_tokens_ref")
            if ref is None and results.get("cot"):
                ref = mean(r.tokens["generated"] for r in results["cot"])
            if bcfg.get("sc_samples"):
                n = Mixture.from_config(bcfg["sc_samples"], "sc_samples") if isinstance(bcfg["sc_samples"], dict) else bcfg["sc_samples"]
            elif ref is not None:
                n = sc_num_samples(budget, ref, bcfg.get("sc_min_samples", 3))
            else:
                raise ValueError("self_consistency needs a cot run first, baselines.cot_tokens_ref, or baselines.sc_samples")
            sample_budget = bcfg.get("sc_sample_max_tokens", budget)
            info["self_consistency"] = {"n": bcfg["sc_samples"] if isinstance(n, Mixture) else n, "cot_tokens_ref": ref,
                                        "sample_max_tokens": sample_budget}
            results[m] = await b.run("self_consistency", problems, n=n, sample_budget=sample_budget, temperature=bcfg.get("sc_temperature", 0.7))
        elif m == "reasoning":
            effort = bcfg.get("reasoning_effort", "medium")
            effort = Mixture.from_config(effort, "reasoning_effort") if isinstance(effort, dict) else effort
            info["reasoning"] = {"effort": bcfg.get("reasoning_effort", "medium"), "prompt": bcfg.get("reasoning_prompt", "baseline_cot_free")}
            samples = bcfg.get("reasoning_samples", 1)
            samples = Mixture.from_config(samples, "reasoning_samples") if isinstance(samples, dict) else samples
            info["reasoning"]["samples"] = bcfg.get("reasoning_samples", 1)
            results[m] = await b.run("reasoning", problems, effort=effort, max_tokens=bcfg.get("reasoning_max_tokens", 32000),
                                     prompt=bcfg.get("reasoning_prompt", "baseline_cot_free"), samples=samples)
        elif m == "k_plus_judge":
            k = bcfg.get("judge_k", 4)
            k = Mixture.from_config(k, "judge_k") if isinstance(k, dict) else k
            sample_budget = bcfg.get("sc_sample_max_tokens", budget)
            judge_budget = bcfg.get("judge_max_tokens", budget)
            info["k_plus_judge"] = {"k": bcfg.get("judge_k", 4), "sample_max_tokens": sample_budget, "judge_max_tokens": judge_budget}
            results[m] = await b.run("k_plus_judge", problems, k=k, sample_budget=sample_budget, judge_budget=judge_budget,
                                     temperature=bcfg.get("sc_temperature", 0.7))
        elif m == "two_plus_judge":
            sample_budget = bcfg.get("sc_sample_max_tokens", budget)
            judge_budget = bcfg.get("judge_max_tokens", budget)
            info["two_plus_judge"] = {"sample_max_tokens": sample_budget, "judge_max_tokens": judge_budget}
            results[m] = await b.run("two_plus_judge", problems, sample_budget=sample_budget, judge_budget=judge_budget,
                                     temperature=bcfg.get("sc_temperature", 0.7))
        else:
            raise ValueError(f"unknown baseline {m!r}")
    return results, info
