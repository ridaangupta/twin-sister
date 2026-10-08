# Dialogic Reasoning: findings, decisions and friction log

Working log for the project from 2026-10-05 to 2026-10-07, written as source material for a later report.
All numbers come from committed artifacts in `analysis/` or from run directories under `runs/`
(gitignored). Where a number was computed ad hoc during the work, that is noted.

---

## 1. Headline

On 400 held-out procedurally generated multi-step arithmetic word problems, a turn-based dialogue between
two instances of `gpt-5.6-luna` (reasoning effort `none`) reached **0.915 accuracy**. Cost-matched
self-consistency (7 samples, majority vote) reached **0.812**.

- Difference: **+10.2 points**, 95% CI [+6.0, +14.5].
- Problem by problem: 60 problems right only with dialogue, 19 right only with self-consistency.
  Exact McNemar p < 0.0001.
- The test was pre-registered and run once.

All four pre-registered secondary comparisons were also significant after Holm correction:

| Dialogue vs | Difference | Holm p |
|---|---|---|
| Two independent attempts + judge | +11.5 pts | < 0.0001 |
| Self-consistency, 16-step problems | +12.5 pts | 0.0008 |
| Token-matched self-consistency (5 samples) | +13.3 pts | < 0.0001 |
| Single chain of thought | +26.5 pts | < 0.0001 |

The gain comes mainly from the structure of the dialogue: two **independent opening posts**, followed
by reconciliation through back-and-forth.

- When exactly one opening is right, the dialogue ends on the right answer 96% of the time.
- When both openings are wrong, it still recovers 46% of the time. A one-shot judge given two wrong
  attempts recovers 24%.
- The second agent's objective (skepticism vs simplicity) made no detectable difference.

---

## 2. Research question and original spec

From `CLAUDE.md`:

> Does turn-based dialogue between two same-model agents with different objectives, sharing a core
> reasoning space, outperform single-agent reasoning at a matched token budget? Which dynamics
> (disagreement, persuasion, convergence) predict when it helps?

Spec elements and their status:

| Spec element | Status |
|---|---|
| One OpenAI model, two instances, objectives differ only | Built. A and B share the model, base prompt and template; they differ only in the objective block (enforced by a test). |
| Per-agent API keys (`OPENAI_API_KEY_A/B`, fallback `OPENAI_API_KEY`) | Built. Only the shared key has been used so far. |
| Shared core (task, thread, agreed-facts ledger) plus private scratchpads | Built, with visibility enforced by construction and by tests. |
| Separate scratchpad and core token budgets | Built and logged separately. |
| Turn controller in three phases behind one interface | Phase 1 (heuristic) built. Phases 2 and 3 not started. Phase 1 traces exist for about 1,400 dialogues. |
| Three synthesis strategies | `single_writer` built. `joint` and `synthesizer` not started (stubs raise `NotImplementedError`). |
| GSM8K benchmark | Built, but abandoned as the main benchmark (near ceiling, memorized). |
| Finance benchmark | Decided (FinQA) but not built. |
| Baselines: direct, matched-budget CoT, self-consistency | Built. Two more added: cost-matched self-consistency and "two attempts + judge". |
| Trace every call; cache responses; seeds; YAML configs; run dirs with config, git hash and model | Built. |

---

## 3. Timeline (git history)

| Commit | When | What |
|---|---|---|
| `458b31b` | 10-05 20:23 | Spec, implementation plan (`docs/PLAN.md`), answers to the open questions |
| `1a90b87` | 10-05 20:30 | `llm.py`: SQLite response cache, retries, usage tracking, call tracing |
| `928b431` | 10-05 20:33 | Memory, ledger, post protocol parser, heuristic controller |
| `776f4d5` | 10-05 20:38 | Agents, prompts, single-writer synthesis, orchestrator |
| `0186afd` | 10-06 11:36 | GSM8K loader, dev subset, metrics, baselines, runner |
| `6f3841d` | 10-06 12:04 | Scratchpad fix: posting rules moved out of the system prompt |
| `848914e` | 10-06 12:18 | Procedural problem generator plus calibration script |
| `ded7ef9` | 10-06 12:26 | Calibration at default reasoning effort |
| `e92245a` | 10-06 17:25 | Switch to `reasoning_effort: none`; recalibrate; re-freeze sets |
| `583a62d` | 10-06 17:33 | Pricing in configs |
| `2f514ac` | 10-07 11:26 | Dialogue v2: independent openings, skepticism partner, prompt caching, answer guarantee |
| `e6644d2` | 10-07 11:51 | Dev-200 comparison plus two ablations; `compare_runs.py` |
| `5c91991` | 10-07 12:01 | Two attempts + judge baseline; cost-matched self-consistency |
| `d5d8a12` | 10-07 12:06 | Pre-registration committed before any test-set call |
| `d3dbe1c` | 10-07 12:31 | Test-set results |

---

## 4. System as built

### 4.1 Modules
- **`dialogic/llm.py`**
  - Async OpenAI wrapper with per-agent clients. B uses key slot B; everyone else uses slot A.
  - SQLite response cache keyed by (model, messages, max_tokens, temperature, seed, sample_idx,
    reasoning_effort if set). Cache hits are traced and counted toward token budgets but not billed.
  - Tenacity retries on 429, 5xx, timeouts, connection errors, and sporadic `invalid_prompt` flags.
  - One shared semaphore for concurrency.
  - `prompt_cache: explicit` sends cache breakpoint markers; otherwise they are stripped.
  - Tracks prompt, completion and reasoning tokens plus prompt-cache reads and writes, per (agent, space).
- **`dialogic/memory.py`**
  - `CoreMemory`: task, thread and ledger.
  - Private `Scratchpad`s holding `Note(turn, text, seen)`, where `seen` is the number of posts in
    the thread when the note was written.
  - Agents only ever receive an `AgentView`: core plus exactly their own notes.
  - Synthesis receives a `CoreView`, which has no scratchpad field and is not a supertype of `AgentView`.
- **`dialogic/protocol.py`** — every post ends with a trailer:
  `ANSWER` / `STANCE` (agree, disagree, unsure) / `CONSENSUS` (yes, no) / `FACT+` / `FACT_OK` /
  `FACT_DISPUTE`. The parser is lenient: missing fields get neutral defaults and set a
  `protocol_error` flag. `normalize_answer` and `extract_answer` are shared by every method's scoring.
- **Ledger** — a fact proposed by one agent becomes `agreed` only when the other agent confirms it.
  A dispute by either agent moves it back to `disputed`, and it then needs a fresh confirmation.
- **`dialogic/controller/`**
  - Interface: `TurnController.decide(ControllerState) -> TurnDecision(soft_limit, scratch_budget, stop, stop_prob, reason)`.
  - `ControllerState.features()` is the Phase 2 feature vector:
    - turn and turn fraction
    - core and scratchpad tokens, last post's tokens
    - whether answers agree, whether both agents have answered
    - turns since the last answer change
    - disagreements in the last 4 posts, last stance (one-hot)
    - ledger: agreed facts, change this turn, disputes
    - per agent: answer changes and consensus flag
  - `HeuristicController` stops on mutual consensus (same non-empty answer), on mutual consensus with
    no answer, or at `max_turns`.
  - The soft limit is sampled per (seed, problem, turn) from `soft_limit_choices`. That keeps it
    independent of async ordering and gives Phase 2 variation to learn from.
- **`dialogic/orchestrator.py`** — each turn runs:
  1. the controller decides,
  2. optional private work (the scratchpad call),
  3. the core post, capped at hard cap = soft limit × k,
  4. the ledger update.

  With `independent_openings`, round one runs in parallel and both posts are committed afterwards in
  speaker order. Who speaks first is seeded per problem. One failed problem is logged and does not
  stop the run.
- **`dialogic/synthesis.py`** — `single_writer`: Agent A writes `SOLUTION:` (numbered steps) and
  `ANSWER:` from the core only. Step count is the simplicity proxy.
- **`dialogic/trace.py`** — append-only JSONL files: `calls`, `prompts` (deduplicated by hash),
  `turns`, `decisions` (with features), `problems`, `errors`.
- **`dialogic/run.py`** — one YAML config gives one run directory containing the config, `meta.json`
  (git hash and dirty flag, model, seed, versions, resolved config), traces, `results.csv` and
  `summary.json`. It refuses a public benchmark's full split without `final_run: true`, and
  supports `--match <dialogue run>` for budget-matched baselines.
- **`evals/`**
  - `datasets.py`: common `Problem` type; loaders for `gsm8k`, `synthetic` and `jsonl`.
  - `gsm8k.py`: official jsonl with a pinned sha256.
  - `synthetic.py`: the procedural generator (section 6).
  - `metrics.py`: exact match, bootstrap CI, "who changed whose mind", cost with cache pricing.
  - `baselines.py`: direct, CoT, self-consistency, two attempts + judge.
- **`scripts/`**
  - `smoke_llm.py`, `smoke_dialogue.py`
  - `calibrate_synthetic.py`, `probe_models.py`, `freeze_synthetic.py`
  - `compare_runs.py`, `analyze_test400.py`
- **Tests**: 921 tests, all offline. They cover answer extraction, memory visibility (canary strings
  checked end to end), the controller interface, ledger rules, the protocol parser, cache key and
  replay, prompt-cache layout (the prefix only grows), generator correctness (three independent
  answer derivations), baselines, and the runner end to end with a scripted fake model.

### 4.2 Final prompt layout (cache-friendly)
For each agent, every call is:

1. **System:** `base_agent.txt` — identity, objective block, how the dialogue works.
2. **User, as content blocks, each a cache breakpoint:**
   - `PROBLEM: …`
   - `instructions.txt` — rules for both modes, including the trailer spec
   - the append-only log: shared posts plus the agent's own notes, in the order the agent
     saw or wrote them
3. **User, short and uncached:** current ledger state plus a mode line, either
   `turn_post.txt` ("MODE: POST. Turn t. Aim for about N tokens") or `turn_private.txt`.

The final writer gets the problem plus the shared posts only, with no breakpoints because it is a
single call that is never reused. Its instructions come from `final_writer.txt`.

### 4.3 Final experimental configuration
`configs/syn_test400_dialogue.yaml`, identical to `syn_dev200_dialogue`:

| Setting | Value |
|---|---|
| Model | `gpt-5.6-luna`, `reasoning_effort: none`, temperature: API default |
| Agents | A: `accuracy`; B: `skepticism` |
| Openings | `independent_openings: true`; first speaker seeded |
| Controller | heuristic, `max_turns: 8` posts |
| Turn lengths | soft limit sampled from {150, 300, 600}; hard cap = 2× soft limit |
| Private work | `scratch_budget: 200` per turn |
| Synthesis | `single_writer` by A, max 512 tokens |
| Caching and pricing | `prompt_cache: explicit`; $0.20 / $1.20 / $0.02 / $0.25 per million tokens (input / output / cache read / cache write) |

Baselines (`syn_test400_baselines.yaml`):

| Baseline | Setting |
|---|---|
| Direct answer | max 32 tokens |
| CoT | max tokens = matched budget B (B = the dialogue run's mean generated tokens) |
| Self-consistency | n = 7, temperature 0.7, per-sample cap B |
| Two attempts + judge | the first two self-consistency draws; judge (cap B) only when their answers differ |

---

## 5. Decision log

| # | Decision | Options considered | Choice and rationale | Evidence |
|---|---|---|---|---|
| D1 | Finance benchmark | FinQA, TAT-QA, ConvFinQA, FinanceBench | **FinQA**: numeric answers fit the existing extraction; TAT-QA has span answers; ConvFinQA is already multi-turn, which confounds the dialogue variable; FinanceBench needs an LLM judge. TAT-QA is the fallback. | `CLAUDE.md` |
| D2 | Controller feature set | Embedding disagreement vs protocol-derived | **Protocol-derived only**: no extra LLM calls (feature list in 4.1). Phase 1 samples the soft limit to create training variation. | `CLAUDE.md` |
| D3 | RL token penalty λ | Raw tokens vs normalized | reward = correct − λ · tokens / T_ref, with T_ref = mean CoT tokens on dev; default λ = 0.05; sweep {0.02, 0.05, 0.1, 0.2}; pick λ whose optimal stop is neither always turn 1 nor always max. | `CLAUDE.md` (not yet used) |
| D4 | Objective proxies | — | simplicity = solution steps and length; efficiency = turns and tokens; skepticism = challenge yield and false-alarm rate; generality = solve rate on a perturbed variant (deferred). | `CLAUDE.md` |
| D5 | What "matched tokens" means | Total vs generated tokens | **Generated tokens** (completion + reasoning, across core, scratchpad and synthesis), matched as a mean over the problem set, not per problem (per-problem matching would hand the baseline a difficulty oracle). Prompt tokens and cost reported, not matched. | `docs/PLAN.md` |
| D6 | Turn definition | Exchange vs post | **One post = one turn**; `max_turns` counts posts. | `CLAUDE.md` |
| D7 | Consensus rule | — | Both agents' latest posts say `CONSENSUS: yes` with the same normalized answer. Later (D17) also stop on mutual consensus with no answer. | — |
| D8 | Dev subset storage | RNG at load time vs committed ids | **Committed id lists and jsonl files**, sampled once; prefixes are random subsets. | `evals/subsets/` |
| D9 | GSM8K source | HF `datasets` vs raw GitHub file | **Raw jsonl from `openai/grade-school-math`** with a pinned sha256; avoids a heavy dependency. | `evals/gsm8k.py` |
| D10 | ANSWER extraction | First vs last number on the line | **First number on the last `ANSWER:` line**; fall back to the last number in the text. Changed after a test showed `ANSWER: 12 (from 3 boxes of 4)` scoring 4. | `dialogic/protocol.py` |
| D11 | Main benchmark | GSM8K, GSM-Symbolic, AIME/HMMT 2026, GSM-Infinite, own generator | **Own GSM-Infinite-style generator**: never memorized, exact gold answers, a difficulty dial, and error types the objectives can work on. GSM8K is near ceiling and memorized; contests are too small (~30 problems) and also near saturation for frontier models ([MathArena](https://matharena.ai/no_final_answer/)); GSM-Symbolic's generator is unreleased and its variants stay close to GSM8K. | Section 6 |
| D12 | Model | luna at none/low/medium, gpt-6-luna, gpt-5.4-mini, gpt-4.1-mini, gpt-4.1 | **`gpt-5.6-luna` at `reasoning_effort: none`**: all reasoning visible (hidden reasoning is 75–80% of tokens at medium), cheapest at $0.20/$1.20 per million tokens, fast (~5 s per call). gpt-4.1 was 15× more verbose; gpt-6-luna at none mostly declared problems unsolvable; gpt-5.4-mini costs 4× more and hit a false policy flag. | Section 7 |
| D13 | Difficulty band | 48/64 steps (calibrated at default effort) vs re-calibrate | User picked a ~83% / ~50% pair at 48/64. At effort none those levels are near 0%, so **re-calibrated to 10/16 steps** (0.87 / 0.47), keeping the shape the user chose. | Section 6.3 |
| D14 | Held-out test set | — | **Frozen at the same time as dev** (400 problems, seeds 2000–2001) to prevent tuning on it. | `scripts/freeze_synthetic.py` |
| D15 | CoT baseline prompt | "Think step by step" vs a structured WORKING section | **WORKING section, one line per quantity**: at effort none, luna answered `ANSWER: 88` with no working under the free-form prompt. | Section 9 |
| D16 | Problem wording | — | Added a **closed-world clause** (each person has only the listed items; "total items" = sum of listed quantities) and an **answer guarantee** (exactly one whole-number answer; a contradiction means an earlier step is wrong). Applied to every method. | Sections 9, 8.2 |
| D17 | Dialogue v2 design | — | (a) **independent openings**; (b) **skepticism** partner instead of simplicity; (c) stop on mutual no-answer consensus; (d) ignore blank optional trailer lines; plus (e) the cache layout. All chosen from the v1 failure analysis. | Section 8 |
| D18 | Prompt caching | Implicit, explicit, Responses API `previous_response_id`, compressing the thread | **Explicit breakpoints on an append-only block layout**. `previous_response_id` still bills all input and can't hold per-agent private state; compressing the thread changes the experiment. | Section 10 |
| D19 | Extra baselines | — | **Cost-matched self-consistency** (n = 7 from $0.00418 / $0.00058 per sample) and **two attempts + judge** (structural control: independent attempts plus reconciliation, without back-and-forth). | Section 8.5 |
| D20 | Confirmatory protocol | — | **Pre-registered** primary hypothesis, test, α, Holm-corrected secondaries, failure rule and frozen configs; analysis script written and dry-run on dev before the test run; test set run once. | `analysis/preregistration_test400.md` |

---

## 6. Problem generator

### 6.1 Design (`evals/synthetic.py`)
- A random graph of integer quantities, each a unique (owner, item) pair, e.g. "the number of pens Mia has".
- Leaves are stated values from 2 to 30.
- Derived quantities use:
  - unary operations with a constant: `+c`, `−c`, `×k`, and half / one third / one quarter / one fifth
    (only where it divides exactly);
  - binary operations on two quantities: `+`, `−`, `×` (`×` only when both values are ≤ 25).
- Every value is kept between 1 and 10,000.
- The core is a chain where each new quantity uses the previous one, sometimes with a second operand,
  so every derived quantity feeds the answer.
- Difficulty settings:
  - `n_ops`: derived quantities on the answer's path
  - `n_distractors`: extra quantities that never feed the answer
  - `n_reverse`: hidden leaves whose value must be found by inverting a relation from a stated
    downstream value
  - `p_total`: chance that an operand is "the total number of items X has", an implicit sum. Once used,
    that owner gets no further quantities, so the total stays well defined.
  - `shuffle`: statements in random order
- **Verification:** every problem is solved three ways, all of which must agree:
  1. evaluating the hidden graph;
  2. an independent constraint solver that reads only the structured statements (forward
     evaluation plus inversion);
  3. the same solver with all distractor statements removed.
- Standard recipe (`standard_knobs`): `n_distractors = n_ops // 2`, `n_reverse = 1` when `n_ops ≥ 8`,
  `p_total = 0.2`, shuffled.
- Wording (final): a closed-world clause plus the answer guarantee, then the statements, then the question.

### 6.2 Calibration at default reasoning effort
Single-agent CoT with a 32k budget, 30 problems per level, `gpt-5.6-luna` at API-default effort.
This used the earlier free-form CoT prompt and the earlier problem wording.

| Steps | Accuracy | 95% CI | Median generated tokens | Median reasoning tokens |
|---|---|---|---|---|
| 16 | 1.00 | [1.00, 1.00] | 1,226 | 984 |
| 24 | 0.97 | [0.90, 1.00] | 1,781 | 1,536 |
| 32 | 0.97 | [0.90, 1.00] | 2,414 | 2,048 |
| 40 | 0.90 | [0.77, 1.00] | 3,722 | 3,072 |
| 48 | 0.83 | [0.70, 0.97] | 4,995 | 4,268 |
| 64 | 0.50 | [0.33, 0.67] | 6,265 | 6,099 |

- No truncation.
- Tokens grow by roughly 100 per step.
- Of the 25 wrong answers, 14 were impossible:
  - 8 fractions or decimals (e.g. `3136501/450`)
  - 2 negatives or zero
  - 4 "can't be determined"
- One "indeterminate" case was checked by hand: the model inverted "Hana's marbles are a quarter of
  Viktor's pears" and lost the chain that fixes the pears.

### 6.3 Calibration at `reasoning_effort: none`
Structured WORKING CoT prompt, closed-world wording, 30 problems per level.

| Steps | 4 | 8 | 10 | 12 | 16 | 20 | 24 | 32 |
|---|---|---|---|---|---|---|---|---|
| Accuracy | 1.00 | 0.90 | 0.87 | 0.70 | 0.47 | 0.43 | 0.30 | 0.13 |
| Median generated tokens | 129 | 248 | 301 | 345 | 523 | 519 | 596 | 878 |

### 6.4 Frozen sets (`scripts/freeze_synthetic.py`)
- **Dev:** `synthetic_dev200.jsonl`, 100 problems at 10 steps (seed 0) and 100 at 16 steps (seed 1),
  shuffled together.
- **Test:** `synthetic_test400.jsonl`, 200 at 10 steps (seed 2000) and 200 at 16 steps (seed 2001).
- **Calibration** used seeds from 1000 up; the ranges never overlap, and dev and test share no problems.
- The sets were regenerated twice for wording changes (closed world, then the answer guarantee). The
  same seeds give the same graphs, so only the text changed.

---

## 7. Model selection

### 7.1 Probe: single-agent CoT on 40 dev problems at 48/64 steps
WORKING prompt, closed-world wording not yet added.

| Config | Accuracy, 48 steps (n=19) | Accuracy, 64 steps (n=21) | Visible tokens | Hidden reasoning tokens | Latency (s) |
|---|---|---|---|---|---|
| luna, effort `none` | 0.00 | 0.00 | ~500 | 0 | ~5 |
| luna, effort `low` | 0.21 | 0.05 | ~300 | ~1,850 | ~25 |
| luna, effort `medium` | 0.47 | 0.24 | ~1,200 | ~4,200 | 43–66 |
| gpt-6-luna, effort `none` | 0.00 | 0.05 | ~730 | 0 | ~5.5 |
| gpt-5.4-mini, effort `none` | 0.05 | 0.05 | ~1,300 | 0 | ~8 |
| gpt-4.1-mini | 0.21 | 0.05 | ~7,700 | 0 | ~63 |
| gpt-4.1 | 0.42 | 0.05 | ~8,300 | 0 | ~63 |

- Most "no answer" results at effort `none` were "cannot be determined": luna 13 of 40,
  gpt-6-luna 30 of 40.
- Several of those pointed at the ambiguous "total number of items" wording, which led to D16.
- gpt-5.4-mini had one call rejected with `invalid_prompt`.

### 7.2 Supported reasoning effort values
- `gpt-5.6-luna` accepts `none`, `low`, `medium`, `high` and `xhigh`, and rejects `minimal`.
- `gpt-4.1-mini` rejects the `reasoning_effort` parameter entirely.

### 7.3 Pricing used
Per million tokens:

| Model | Input | Output | Cache read | Cache write |
|---|---|---|---|---|
| `gpt-5.6-luna` | $0.20 | $1.20 | $0.02 (0.1×) | $0.25 (1.25×) |
| `gpt-5.4-mini` | $0.75 | $4.50 | | |
| `gpt-5.4-nano` | $0.20 | $1.25 | | |

Sources: [CloudZero](https://www.cloudzero.com/blog/openai-pricing/),
[TechJack](https://techjacksolutions.com/ai-tools/chatgpt/gpt-5-6-pricing/),
[OpenAI prompt caching guide](https://developers.openai.com/api/docs/guides/prompt-caching).

---

## 8. Experiments

### 8.1 GSM8K sanity check (one problem, live)
- GSM8K test problem #0 (Janet's ducks, gold 18) was solved correctly.
- B spoke first, both agents declared consensus on their first post, and the dialogue stopped after 2 turns.
- Tokens: 506 generated (core 249, scratchpad 196, synthesis 61) and 3,749 prompt.
- No protocol errors and no truncation.
- Problems observed:
  - scratchpads copied the upcoming post, trailer included (F4);
  - immediate consensus on an easy problem;
  - the simplicity objective was invisible;
  - the problem is likely memorized.
- These pushed the move to harder, generated problems (D11).

### 8.2 Dialogue v1 on 50 dev problems
Setup: accuracy + simplicity, sequential openings, effort none.

| Method | All | 10 steps (n=22) | 16 steps (n=28) | Generated tokens | Prompt tokens |
|---|---|---|---|---|---|
| Direct | 0.08 | 0.05 | 0.11 | 7 | 484 |
| CoT | 0.58 | 0.59 | 0.57 | 369 | 519 |
| Self-consistency (n=4, token-matched) | 0.70 | 0.86 | 0.57 | 1,453 | 2,075 |
| **Dialogue v1** | **0.72** | **0.91** | **0.57** | 1,358 | 13,313 |

- Dialogue vs CoT: +14 points, 95% CI [+0.02, +0.28], p = 0.09.
- Dialogue vs self-consistency: 4 problems right only with dialogue, 3 only with self-consistency;
  p = 1.0.
- Cost: dialogue $0.0043 per problem against $0.0022 for self-consistency.

Dynamics:
- 3.52 turns on average; 86% of dialogues stopped by consensus.
- Only 6 answer changes in total.
- 0.78 protocol errors per problem, mostly blank trailer lines.

Failure analysis (15 wrong):
- **7 never produced an answer.** A derived a false contradiction (it counted Mia's cups inside
  Mateo's total). B's private "independent check" restated A's derivation. Both then repeated
  `CONSENSUS: yes / ANSWER: none` until the turn limit, because the stop rule required an answer.
  The problem was checked to be consistent: Mateo's total is 4, Mia has 1 cup, the answer is 171.
- **7 agreed early on a wrong answer.** The second speaker adopted the first speaker's error (anchoring).
- **1 was made worse by dialogue.** Both agents had the right answer (387); B introduced 386 and A followed.

### 8.3 Dialogue v2 on 50 dev problems
Setup: independent openings, skepticism partner, answer guarantee, stop on no-answer consensus,
parser fix, cache layout.

| Method | All | 10 steps | 16 steps | Generated tokens | Cost per problem |
|---|---|---|---|---|---|
| Direct | 0.10 | 0.09 | 0.11 | 7 | – |
| CoT | 0.76 | 0.95 | 0.61 | 370 | $0.00056 |
| Self-consistency (n=5) | 0.76 | 0.91 | 0.64 | 1,967 | $0.00291 |
| **Dialogue v2** | **0.84** | **0.95** | **0.75** | 1,844 | $0.00412 |

- The answer guarantee raised CoT from 0.58 to 0.76. Compare methods within a table, not across tables.
- Dialogue vs self-consistency: +8 points, p = 0.39. Dialogue vs CoT: +8 points, p = 0.42.
- Openings: both right 29 problems (28 correct); one right 13 (12 correct); both wrong 8 (2 correct).
- 98% of dialogues stopped by consensus; 4.14 turns on average; protocol errors fell to 0.12 per problem.

### 8.4 Full dev set (200 problems) plus ablations

| Method | All | 10 steps | 16 steps | Generated tokens | Cost per problem |
|---|---|---|---|---|---|
| **Dialogue** (accuracy + skepticism, independent) | **0.915** | 0.98 | **0.85** | 1,881 | $0.00418 |
| Ablation: sequential openings | 0.855 | 0.95 | 0.76 | 1,376 | $0.00262 |
| Ablation: simplicity partner | 0.900 | 0.96 | 0.84 | 1,729 | $0.00387 |
| Self-consistency n=5 (token-matched) | 0.850 | 0.96 | 0.74 | 1,974 | $0.00291 |
| Self-consistency n=7 (cost-matched) | 0.860 | 0.95 | 0.77 | 2,789 | $0.00411 |
| Two attempts + judge | 0.845 | 0.96 | 0.73 | 928 | $0.00145 |
| CoT | 0.740 | 0.87 | 0.61 | 398 | $0.00059 |
| Direct | 0.080 | 0.08 | 0.08 | 7 | $0.00011 |

Paired comparisons with the dialogue (exact McNemar):

| Compared with | Difference | 95% CI | Dialogue-only | Other-only | p |
|---|---|---|---|---|---|
| Self-consistency n=5 | +6.5 | [+0.5, +12] | 24 | 11 | 0.041 |
| Self-consistency n=5, 16 steps | +11 | [+1, +21] | 20 | 9 | 0.061 |
| Self-consistency n=7 (cost-matched) | +5.5 | [−0.5, +11.5] | 23 | 12 | 0.090 |
| Two attempts + judge | +7.0 | [+1.5, +12.5] | 23 | 9 | 0.020 |
| Two attempts + judge, 16 steps | +12 | [+2, +22] | 19 | 7 | 0.029 |
| Sequential-openings ablation | +6.0 | [+0.5, +11.5] | 22 | 10 | 0.050 |
| Simplicity ablation | +1.5 | [−2.5, +5.5] | 10 | 7 | 0.63 |
| CoT | +17.5 | [+11, +24] | 42 | 7 | < 0.001 |

**Overfitting check:** the first 50 dev problems were used for iteration. On the other 150, never
inspected: dialogue 0.940, self-consistency (n=5) 0.887, CoT 0.747. Dialogue-only 15, SC-only 7,
p = 0.134.

### 8.5 Two attempts + judge on dev, in detail
- The two attempts disagreed on 73 of 200 problems, and the judge was right on 46 of those.
- Exactly one attempt right: 49 problems, judge correct 43 (88%). Dialogue with one opening right:
  50 of 53 (94%).
- Both attempts wrong (attempts that disagreed): 24 problems, judge correct 3 (12%). Dialogue with
  both openings wrong: 10 of 23 (43%).
- Attempts agreed on a wrong answer on 4 problems. The judge isn't called then, so all 4 stayed wrong.
  The dialogue got all 4 right.

### 8.6 Confirmatory test (400 problems, pre-registered)
- Frozen configs and analysis script committed in `d5d8a12` before the run.
- The run used `runs/20261007T160631Z_syn_test400_dialogue` and
  `runs/20261007T161733Z_syn_test400_baselines`.
- No failures, re-runs or deviations.

| Method | All | 10 steps | 16 steps | Generated tokens | Cost per problem |
|---|---|---|---|---|---|
| **Dialogue** | **0.915** | **0.965** | **0.865** | 1,948 | $0.00431 |
| Self-consistency n=7 (cost-matched) | 0.812 | 0.885 | 0.740 | 2,792 | $0.00411 |
| Two attempts + judge | 0.800 | 0.895 | 0.705 | 953 | $0.00148 |
| Self-consistency n=5 (first 5 of the 7 draws) | 0.782 | 0.870 | 0.695 | – | – |
| CoT | 0.650 | 0.765 | 0.535 | 396 | $0.00058 |
| Direct | 0.045 | 0.045 | 0.045 | 7 | $0.00011 |

- **Primary (H1):** dialogue vs self-consistency n=7: +10.2 points, 95% CI [+6.0, +14.5];
  60 vs 19 discordant; p < 0.0001. **Supported.**
- **Secondary (Holm-corrected):**

| | Comparison | Difference | 95% CI | Discordant | Holm p |
|---|---|---|---|---|---|
| S1 | vs two attempts + judge | +11.5 | [+7.5, +15.5] | 58 vs 12 | < 0.0001 |
| S2 | vs self-consistency n=7, 16 steps | +12.5 | [+5.5, +19.5] | 39 vs 14 | 0.0008 |
| S3 | vs self-consistency n=5 | +13.3 | [+9.0, +17.5] | 67 vs 14 | < 0.0001 |
| S5 | vs CoT | +26.5 | [+21.7, +31.2] | 114 vs 8 | < 0.0001 |

- **S4 (descriptive):** both openings wrong on 56 problems, dialogue recovered 26 (46%). Both judge
  attempts wrong on 84 problems (including attempts that agreed on a wrong answer), judge recovered
  20 (24%). Fisher p = 0.006, but the subsets differ by method.
- **Dialogue dynamics on test:**
  - 95% of dialogues stopped by consensus; 11 hit the turn limit; 8 stopped on mutual no-answer
    consensus; 4.27 turns on average.
  - Answer changes: A adopted B's answer 51 times, B adopted A's 26 times; plus 16 and 7 changes
    to an answer neither agent held.
  - 2.27 agreed ledger facts and 0.19 disputes per problem.
  - 0.22 protocol errors per problem; 1.75% of final answers missing.

---

## 9. Mechanism findings

1. **Independent openings are the active ingredient.**
   - Sequential openings cost 6 points on dev (p = 0.05).
   - When the second agent sees the first post, openings disagree on only 20 of 200 problems instead
     of 53, and both openings are wrong on 36 instead of 23. The second agent anchors on the first.
   - Caveat: the sequential ablation also used fewer tokens (1,376 vs 1,881), so budget is a partial
     confound.
2. **Disagreement gets resolved correctly.** One opening right gives a correct final answer 94–96%
   of the time, on dev and test.
3. **The dialogue recovers when both openings are wrong**, 43–46% of the time, where the one-shot judge
   manages 12–24%. Picking between two answers doesn't need conversation; finding an error that
   neither first attempt exposed apparently does.
4. **The partner's objective barely matters on this task.** Skepticism vs simplicity: 0.915 vs 0.900,
   p = 0.63. The structure (independence, then reconciliation) dominates the objective wording. The
   objective sweep in the original plan is therefore lower priority for this task family.
5. **Both directions of persuasion happen.** On test, B moved to A's answer 26 times and A to B's 51
   times. In v1 there were only 6 answer changes across 50 problems.
6. **Same-model agents share blind spots.** In v1, B's private "independent" check copied A's flawed
   derivation. Independent openings partly address this by keeping the first derivations separate.
7. **Telling the solver the answer exists and is a whole number** is a large, method-agnostic effect
   (CoT 0.58 to 0.76 on dev-50). With reasoning effort none, models otherwise treat a self-made
   contradiction as proof the problem is unsolvable.

---

## 10. Cost and prompt-caching study

- **The problem:** every dialogue turn re-sends the whole thread. In v1, dialogue read 13,313 prompt
  tokens per problem against 2,075 for self-consistency, and cost $0.0043 per problem against $0.0022.
- **Options rejected:**
  - Responses API `previous_response_id` still bills the full input each turn and can't hold
    per-agent private state.
  - Compressing or summarizing the thread changes the experiment.
- **Probes on `gpt-5.6-luna`:**
  - **Implicit caching (the GPT-5.6 default)** never hit, even at 1,466 tokens with a 5-second wait.
    The implicit breakpoint sits at the end of the last message, which changes on every call.
    `gpt-4.1-mini` cached 1,280 of 1,467 tokens on the same test.
  - **Explicit mode** (`prompt_cache_options.mode = explicit` plus a `prompt_cache_breakpoint` on
    content blocks) works:
    - Repeating the same prefix: 1,453 cached.
    - Appending text inside the same block: 0 cached. Matches happen only at breakpoint positions
      already seen.
    - One block per post, each with a breakpoint, on a growing thread: turn 1 read 1,450 of 1,995,
      turn 2 read 1,979 of 2,524, turn 3 read 2,508 of 3,053.
    - At least 21 breakpoints per request are accepted.
- **Estimate vs reality:**
  - Replaying v1's 402 calls under a thread-only cache layout predicted input cost falling 44%
    ($0.00266 to $0.00148 per problem).
  - Measuring v1's uncached tail found static instructions were the largest part (2,947 tokens per
    problem). So the instructions moved into the cached prefix, and each agent's notes were merged
    into its log.
  - Projected all-in cost about $0.0025 per problem; **actual about $0.0042–0.0043**. Two reasons:
    v2 generates more (about 1,900 vs 1,358 tokens), and each agent pays the 1.25× write premium for
    its problem-plus-instructions prefix.
  - Dev-200 dialogue: 18,056 prompt tokens per problem, of which 10,633 read from cache (59%) and
    4,606 written. Caching cut dialogue cost 29–30% compared with the same prompts uncached.
- **Final cost position:** dialogue about $0.0043 per problem against $0.0041 for 7-sample
  self-consistency (the cost-matched baseline), $0.0029 for 5 samples, $0.0015 for two attempts +
  judge and $0.0006 for CoT. Output tokens are now the larger part of the dialogue's bill.
- **Not done:** sharing one cache between both agents (same system prompt, objective moved into the
  tail) would save about another 8%. The Batch API would halve prices for final runs.
- **Total API spend** was small. Billed totals recorded across the GSM8K, dev and test runs come to
  roughly $8; calibrations and the model probe add a few dollars more, mostly the gpt-4.1 /
  gpt-4.1-mini probe at their higher prices, which is not exactly tallied. Spend was well under $15.

---

## 11. Friction log (chronological)

| # | Friction | Symptom | Resolution |
|---|---|---|---|
| F1 | `openai` 3.x uses `httpx2` | Tests importing `httpx` failed to collect | Tests import `httpx2` with a fallback to `httpx`; pinned `openai>=3.0`. The API surface (errors, `chat.completions`, `max_completion_tokens`) was unchanged. |
| F2 | `python-dotenv` from a stdin script | `find_dotenv()` raised `AssertionError` when the script came from stdin | Pass the explicit path: `load_dotenv(".env")`. |
| F3 | `.env` workflow | The user needed a place to paste the key | Created `.env` from `.env.example` (gitignored) and opened it in TextEdit; only checked whether fields were filled, never read the values. |
| F4 | Scratchpad copied the post | The system prompt said "always end with the trailer", so scratchpad calls produced near-copies of the post, trailer included, using about 40% of generated tokens | Posting rules moved out of the system prompt into the post-only prompt; scratchpad asks for terse independent checks (`6f3841d`). Later both sets of rules moved into a shared cached block, with a mode line saying which applies. |
| F5 | GSM8K too easy and memorized | Instant consensus; no visible role for objectives | Built the problem generator (D11). |
| F6 | Generator: `n_reverse=2` impossible | 280 test failures: reversal only used leaves feeding single-input relations, and the chain has at most one | Allow leaves feeding two-input relations; the solver rejects unsolvable picks. |
| F7 | Generator: items ran out at 64+ steps | Unique item names exhausted the pool | Only the (owner, item) pair must be unique; the number of people grows with problem size. |
| F8 | Reasoning cap stopped well below budget | At 64/96 steps luna stopped reasoning at about 9.1–9.3k tokens with a 32k budget, answering "indeterminate" or a fraction | Checked by hand that the problems were well posed; treated as genuine model failures. |
| F9 | Hidden reasoning vs per-post caps | At 64 steps luna needs about 6k reasoning tokens, but dialogue posts were capped at 600 including reasoning | Moved to effort none, which also re-scoped difficulty (D12, D13). |
| F10 | Effort `none` skips visible work | "Think step by step" gave `ANSWER: 88` (7 tokens) | Required a WORKING section, one line per quantity, in the CoT prompt; posts must show the calculation behind every number (D15). |
| F11 | "Total items" judged ambiguous | Models answered "cannot be determined", citing the "total number of items" wording | Closed-world clause added to every problem (D16). |
| F12 | Prompt format changes reasoning-model scores | At effort medium, the WORKING format scored 0.47 at 48 steps against 0.83 with the free-form prompt (the problems also changed slightly in between) | Logged as a fairness risk: baselines must use the strongest prompt we can find. Not fully resolved; effort none made it moot for the main line. |
| F13 | False contradiction becomes "no answer" | v1: both agents agreed the problem was unsolvable and looped to the turn limit | Answer guarantee in the wording; stop rule for mutual no-answer consensus. |
| F14 | Parser regex spanned lines | `\s*` after the colon matched newlines, so a blank `FACT+:` swallowed the next line (e.g. a fact of "FACT_OK: none") | Restricted to spaces and tabs; blank or "none" optional values ignored. Protocol errors fell from 0.78 to 0.12 per problem. |
| F15 | ANSWER line with explanation | `ANSWER: 12 (from 3 boxes of 4)` scored 4 | Take the first number on the ANSWER line (D10). |
| F16 | Implicit prompt caching never hit | 0 cached tokens on luna | Explicit breakpoints (D18). |
| F17 | Appending inside one block broke reuse | 0 cached when a post was appended to an existing block | One block per post. |
| F18 | Parallel openings broke the cache order | B's opening note sorted after A's opening post, so B's prefix changed and re-wrote about 1,000 tokens per call | Notes record `seen` (posts visible when written) and are ordered by it, which is also the true chronology. Tested. |
| F19 | Final writer paid the write premium | The writer's single call wrote about 1,650–2,230 tokens at 1.25× | No breakpoints on writer messages. |
| F20 | Sporadic `invalid_prompt` 400s | 3 of 50 problems failed on A's opening call (all 16-step); the same prompts passed when re-sent; also once with gpt-5.4-mini | Retried as a transient error. Dropping those problems would have biased accuracy upward. |
| F21 | Local response cache distorts billed cost | Runs replaying earlier calls report a low `cost_usd_billed` (dev-200 dialogue $0.63 vs about $0.84 from scratch) | `compare_runs.py` prices every call, cache hits included; summaries report both billed and no-prompt-cache cost. |
| F22 | Baseline label collision | Two runs both produced `self_consistency` | `compare_runs.py` suffixes repeated labels with the config name. |
| F23 | Fixed `sc_samples` still needed a CoT run | `run_baselines` asked for a CoT run before checking `sc_samples` | Reordered: a fixed n needs no reference. |
| F24 | Tests tied to old layouts | Each structural change broke tests (string vs block content, turn numbering, 200-vs-400 set size) | Updated each time; the fake model flattens block content. |
| F25 | Reasoning-model temperature | Unclear whether luna accepts temperature at effort none | Self-consistency at 0.7 worked; dialogue, CoT and judge use the API default (`temperature: null`). |
| F26 | Scratchpad budget in openings | With independent openings, the 200-token private budget was often cut off at the cap | Left as is; noted for tuning. |

---

## 12. Limitations and threats to validity

- **External validity:**
  - one model (`gpt-5.6-luna` at effort none);
  - one task family (generated arithmetic dependency graphs);
  - one difficulty band (10 and 16 steps);
  - English template text with a closed-world clause.

  Transfer to public benchmarks, other models, reasoning-enabled settings and finance tasks is untested.
- **The setting suits dialogue.** Errors in these problems are often checkable (fractions, negatives,
  contradictions), and the answer guarantee tells solvers a contradiction means a mistake. That helps
  every method, but a skeptical partner may exploit it more.
- **Budget matching:**
  - Generated tokens: dialogue 1,948 vs 2,792 for 7-sample self-consistency, so self-consistency had
    more.
  - Cost: $0.00431 vs $0.00411, so dialogue cost about 5% more.
  - The judge baseline used half the dialogue's tokens. It is a structural control, not a matched budget.
  - CoT never uses its budget (about 400 of about 1,900 allowed tokens).
- **Ablation confound:** the sequential-openings ablation used fewer tokens, so its 6-point gap mixes
  anchoring with budget.
- **The dialogue and baselines use different prompts.** The dialogue's openings use the agent prompts
  and default temperature; the baselines use the WORKING prompt at temperature 0.7. "Both first
  attempts wrong" subsets therefore differ by method.
- **Many dev comparisons were run.** The dev p-values are exploratory; only the pre-registered test
  results are confirmatory.
- **Baselines were lower on test than on dev** (CoT 0.650 vs 0.740; 7-sample self-consistency 0.812
  vs 0.860) while dialogue held at 0.915. Comparisons are paired, so this doesn't bias them; it may
  mean the test draws are harder.
- **Same model for both agents** means shared blind spots. The design intends this (same-model
  agents), but it limits how much dialogue can help.
- **The test set is now used up.** Any further method change needs a fresh held-out set and a new
  pre-registration (see the project memory note `test400-consumed`).

---

## 13. Open threads and suggested next steps

1. **Generalization:**
   - GSM-Symbolic P2 as an external benchmark
   - another model (`gpt-4.1`, `gpt-5.4-mini`, or luna at low effort)
   - more difficulty levels (e.g. 8–32 steps) to plot dialogue gain against difficulty
2. **Mechanism:**
   - a budget-matched sequential-openings ablation
   - a judge with a matched budget or more attempts
   - turning off private scratchpads
   - analysing which errors the skeptical partner catches
3. **Original roadmap:**
   - `joint` and `synthesizer` synthesis strategies
   - Phase 2 learned controller trained on the roughly 1,400 Phase 1 traces (features already logged
     per decision)
   - Phase 3 RL with the λ rule from D3
   - the objective-pairing sweep (low expected value on this task, per finding 9.4)
   - FinQA
4. **Cost:**
   - one shared cache for both agents (about 8%)
   - Batch API for final runs
   - check whether the first-opening private budget can drop without losing accuracy

---

## 14. Artifact index

| Artifact | Path |
|---|---|
| Spec and decisions | `CLAUDE.md` |
| Original plan | `docs/PLAN.md` |
| This document | `docs/FINDINGS.md` |
| Calibrations and model probe | `analysis/calibration/*.json` |
| Run summaries | `analysis/results/*_summary.json` |
| Dev-200 comparison table | `analysis/results/2026-10-07_syn_dev200_comparison.txt` |
| Pre-registration | `analysis/preregistration_test400.md` |
| Test report | `analysis/results/test400_report.md` |
| Frozen sets | `evals/subsets/synthetic_dev200.jsonl`, `synthetic_test400.jsonl`, `gsm8k_dev200.json` |
| Configs | `configs/syn_dev50_*`, `syn_dev200_*`, `syn_test400_*`, `gsm8k_dev50_*` |
| Full traces (gitignored) | `runs/<timestamp>_<config>/`; key runs: `20261007T153222Z_syn_dev200_dialogue`, `…153643Z_syn_dev200_baselines`, `…154220Z_syn_dev200_abl_no_indep`, `…154644Z_syn_dev200_abl_simplicity`, `…155829Z_syn_dev200_baselines_extra`, `20261007T160631Z_syn_test400_dialogue`, `…161733Z_syn_test400_baselines` |
| Prompts | `prompts/` (base_agent, instructions, turn_post, turn_private, final_writer, baseline_*, objectives/*) |

---

## 15. Addendum (2026-10-08): exploratory log analyses (PLAN_v2 WS1)

Exploratory only: these runs were already used. Full tables: `analysis/results/exploratory_v1.md`
(`scripts/explore_logs.py`); 60-case hand-labelling sample for the error classifier:
`analysis/results/error_validation_sample.md` (not yet labelled).

- **Recovery when both openings are wrong depends entirely on whether they disagree.**

  | Run | Same wrong answer | Recovered | Different (or missing) wrong answers | Recovered |
  |---|---|---|---|---|
  | Test (dialogue) | 8 | 0 | 48 | 26 (54%) |
  | Dev (dialogue) | 3 | 0 | 20 | 10 (50%) |
  | Dev, sequential openings | 14 | 0 | 22 | 8 (36%) |
  | Dev, simplicity partner | 3 | 0 | 22 | 9 (41%) |

  Across all four runs, **0 of 28** shared wrong answers were recovered. The mechanism is
  *disagreement triggers re-derivation*, not a skeptic finding errors both agents share.
- **Sequential openings create shared errors.** Same-wrong openings went from 3 to 14 on dev,
  B switched answers once instead of 16 times, and partners corrected almost nothing (e.g. 2 of 30
  implicit-total errors).
- **Switches nearly always move toward the correct answer:** 81 to 4 on test, 40 to 0 on dev,
  with 15 and 5 wrong-to-wrong.
- **Most common first error: implicit totals** (66 of 148 classified errors on test), which are also
  the least often corrected (35 never corrected). Next: arithmetic or unexplained (44), wrong operand
  (18), misread relation (15), backward step (4). "Misread given value" nearly vanished once the
  extractor stopped attributing right-hand-side results to operands.
- **Extractor friction:** the first version attributed `= 271 − 8 = 263` to every label on the
  right-hand side, inflating "misread given value" to 155. Fixed by accepting only clause subjects
  (no symbolic or word operator before the label) and requiring arithmetic-only final steps.
  Edge cases are pinned in `tests/test_explore_logs.py`.
