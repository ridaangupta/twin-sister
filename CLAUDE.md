# Dialogic Reasoning

Research tool for studying reasoning as a conversation between two agents instead of a single model talking to itself. No UI. The deliverable is clean experiments, traces, and metrics.

## Research question

Does turn-based dialogue between two same-model agents with different objectives, sharing a core reasoning space, outperform single-agent reasoning at a matched token budget? Which dynamics (disagreement, persuasion, convergence) predict when it helps?

## Core design

- Model: one OpenAI model, two instances (Agent A, Agent B). Model name set in config, never hardcoded.
- API: OpenAI Python SDK. Keys read from `OPENAI_API_KEY_A` and `OPENAI_API_KEY_B`; if only `OPENAI_API_KEY` is set, both agents use it. Usage is tracked per agent in code regardless of keys.
- Agents differ by objective only: same model, same base prompt template, different objective block.

### Objectives

- Library in `/prompts/objectives/`, one file per objective.
- Initial pair: `accuracy` vs `simplicity`.
- Candidate pool (up to 5): accuracy, simplicity, efficiency (fewest steps), skepticism (actively find flaws), generality (method should transfer to similar problems).
- Experiments can run any pairing from the pool; pairing is set in config.
- Every objective needs an operational definition and, where possible, a measurable proxy (e.g. simplicity = steps or tokens in the final solution path).

### Memory architecture

- **Core (shared):** task, main reasoning thread where the dialogue happens, and an agreed-facts ledger. Both agents read and write.
- **Auxiliary scratchpads (private):** one per agent. An agent can work privately before contributing to core. The other agent can never read it.
- **Dedicated work time:** each turn an agent may spend a separate scratchpad token budget before posting to core. Scratchpad and core budgets are tracked and logged separately.
- Final answers are extracted from core only.

### Turn controller

A small learned model sets the soft turn-length limit and decides when to stop. Built in phases behind one interface so the orchestrator never changes.

1. **Heuristic (Phase 1):** fixed per-turn token target and max turns from config. Stop on explicit consensus marker from both agents or max turns. Purpose: generate traces for training.
2. **Supervised (Phase 2):** train a tiny model (logistic regression, small MLP, or gradient boosting) on Phase 1 traces.
   - Inputs: turn index, tokens used so far, disagreement signal, ledger changes, whether current answers agree.
   - Outputs: soft token limit for next turn, stop probability.
   - Labels derived from outcomes (e.g. point after which accuracy stopped improving).
3. **RL fine-tune (Phase 3):** controller as policy in an RL env, initialized from Phase 2.
   - Reward = correctness minus lambda times total tokens.
   - Human-supervised: training pauses at checkpoints for review of reward curves and sample traces before continuing.

Soft limit is injected into the agent prompt as a target length, with a hard cap at `soft_limit * k` (k in config).

### Final answer synthesis

All three implemented, selectable in config:

1. `single_writer`: one configurable agent writes the final answer from core.
2. `joint`: both propose a final answer; if they match, accept; otherwise one reconciliation turn.
3. `synthesizer`: a third instance of the same model with a neutral prompt reads core only and answers.

## Evaluation

- **Benchmark 1:** GSM8K test split. Extract final numeric answer, exact match.
- **Benchmark 2 (later):** finance-specific tasks, TBD. All datasets sit behind a common loader interface.
- **Baselines (mandatory, same model):**
  - single-agent direct answer
  - single-agent chain of thought with token budget matched to the dialogue run's total tokens
  - self-consistency (majority vote) at matched tokens
- **Metrics:** accuracy, tokens (core, scratchpad, controller overhead), turns, cost, agreement trajectory, answer flips (who changed whose mind), ledger growth.
- GSM8K is near ceiling for strong models. Also run a smaller model, or a harder variant, so there is headroom to see effects.
- Fixed seeds. Fixed dev subset (e.g. 200 problems) for iteration; full test split only for final runs.

## Repo layout

```
dialogic/
  llm.py            # OpenAI wrapper: retries, rate limits, caching, usage tracking
  agents.py
  memory.py         # CoreMemory, Scratchpad, Ledger, visibility rules
  orchestrator.py
  synthesis.py
  controller/
    base.py
    heuristic.py
    learned.py
    rl_env.py
evals/
  datasets.py
  gsm8k.py
  metrics.py
  baselines.py
prompts/
  base_agent.txt
  synthesizer.txt
  objectives/
configs/            # one YAML per experiment
runs/               # gitignored; JSONL traces, one dir per run
analysis/           # notebooks and plots
tests/
```

## Conventions

- Prompts live in `/prompts` as text files, never inline.
- Every experiment is a YAML config. Each run dir stores a copy of the config, git hash, and model name.
- Trace every API call: run_id, problem_id, turn, agent, space (core or scratchpad), prompt hash, response, tokens, latency.
- Cache API responses keyed by (model, prompt, params) so reruns are free.
- Async calls with concurrency set in config.
- No UI. Outputs are traces, CSV summaries, and plots.
- Tests required for: answer extraction, memory visibility (Agent B can never read Agent A's scratchpad and vice versa), controller interface.

## Build order

1. `llm.py` wrapper with caching and usage tracking
2. Memory, agents, orchestrator with heuristic controller
3. GSM8K loader, metrics, baselines
4. Dev run on 50 problems; inspect traces manually before scaling
5. Three synthesis strategies
6. Objective pairing sweep
7. Phase 2 controller, then Phase 3
8. Finance tasks

## Decisions (formerly open questions)

Implementation plan for build steps 1–4: `docs/PLAN.md`.

- **Finance benchmark: FinQA** (numerical reasoning over earnings-report text + tables; 1,147 test problems; numeric answers). It reuses the numeric-extraction pipeline with a tolerance match (relative error ≤ 1e-2 after normalizing % and scale words). Rejected alternatives: TAT-QA has span answers and is hard to score; ConvFinQA is already multi-turn, which confounds the dialogue variable; FinanceBench is open-ended and needs an LLM judge. TAT-QA is the fallback if FinQA proves near ceiling.
- **Controller feature set:** every feature is computed from the structured post trailer (`ANSWER / STANCE / CONSENSUS / FACT±`), so it costs no extra LLM calls. Features:
  - turn index and turn / max_turns
  - cumulative core tokens, cumulative scratchpad tokens, last post's tokens
  - whether the current answers agree, and whether both agents have an answer
  - answer changes per agent, and turns since the last change
  - last stance, and number of disagree stances in the last 4 posts
  - each agent's consensus flag
  - ledger agreed size, ledger change this turn, cumulative disputes

  The disagreement signal is the stated stance plus answer mismatch; no embeddings in v1. Phase 1 samples the soft limit from `soft_limit_choices` so the traces contain the variation Phase 2 needs to learn the limit head.
- **Lambda:** reward = correct − λ · (generated_tokens / T_ref), where T_ref is the mean generated tokens of single-agent CoT on the dev subset, fixed once per model and stored in config. Default λ = 0.05: each extra CoT's worth of tokens must raise P(correct) by ≥ 5 pp. Sweep {0.02, 0.05, 0.1, 0.2} on Phase 1 traces. For the RL run, keep the λ whose reward-optimal stopping point is neither always turn 1 nor always max_turns.
- **Objective proxies:**
  - accuracy: exact match.
  - simplicity: number of steps in the final `SOLUTION:` path, plus the token count of that path (a property of the product).
  - efficiency: turns to consensus, plus total generated tokens (a property of the process).
  - skepticism: challenge yield = share of the agent's disagree stances / `FACT_DISPUTE`s that are followed by the other agent moving to the correct answer, reported together with the false-alarm rate (challenges against an already-correct answer).
  - generality: a fresh instance gets only the final solution method and must solve a numerically perturbed variant (GSM-Symbolic templates); score = solve rate. Deferred until the objective sweep.
- **Token matching for baselines:** match on generated tokens (completion + reasoning, across core + scratchpad + synthesis), using the mean per problem over the subset rather than a per-problem budget. Prompt tokens and cost are reported for every method but are not matched.
- **Turn definition:** one turn = one post by one agent; `max_turns` counts posts. Who speaks first is seeded per problem and logged.
- **Consensus:** both agents' latest posts say `CONSENSUS: yes` with the same normalized `ANSWER`.
