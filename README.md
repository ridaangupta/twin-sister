# Dialogic Reasoning (twin-sister)

**Does a turn-based dialogue between two copies of the same model reason better than one model given the
same budget?** This repo is a research harness for testing that: a two-agent dialogue system with
shared and private memory, procedurally generated problems that can't have been memorized, cost-matched
baselines, full call-level traces, and pre-registered confirmatory tests.

> **Status: closed (2026-10-09).** The research question is answered within its scope; remaining work is listed
> as next steps in the final report.

- **Final research report:** [Dialogic Reasoning: final report](https://claude.ai/artifact/UfTK6FAnYTNi3Ua1vPwGKY)
  · markdown copy in the repo: [`docs/FINAL_REPORT.md`](docs/FINAL_REPORT.md)
- **Full findings, decision log and friction log:** [`docs/FINDINGS.md`](docs/FINDINGS.md)
- **Plans:** [`docs/PLAN.md`](docs/PLAN.md) (v1, built) · [`docs/PLAN_v2.md`](docs/PLAN_v2.md) (v2, partly run) ·
  related work: [`docs/related_work.md`](docs/related_work.md)

## Findings (final)

| Finding | Evidence | Status |
|---|---|---|
| With hidden reasoning **off** (all reasoning visible), the dialogue beat cost-matched self-consistency: **0.915 vs 0.812** (+10.2 pts, 95% CI [+6.0, +14.5], p < 0.0001) on 400 held-out problems | [`analysis/preregistration_test400.md`](analysis/preregistration_test400.md) → [`analysis/results/test400_report.md`](analysis/results/test400_report.md) | Pre-registered, confirmed |
| A **single call with hidden reasoning on** beats the dialogue at about a quarter of its cost (0.970–1.000 vs 0.915 on dev) | [`analysis/results/cost_matching.md`](analysis/results/cost_matching.md), [`docs/FINDINGS.md`](docs/FINDINGS.md) §16 | Dev-stage; the claim is now scoped to visible reasoning |
| Against **all** cost-matched baselines on 1,200 fresh problems: dialogue 0.928 beats self-consistency 0.812 (+11.6), k attempts + judge 0.854 (+7.4) and self-refine 0.897 (+3.1); a reasoning-on vote beats the dialogue, 0.992 (−6.3), as predicted | [`analysis/preregistration_test1200.md`](analysis/preregistration_test1200.md) → [`analysis/results/test1200_report.md`](analysis/results/test1200_report.md) | Pre-registered, confirmed (cost drift noted in the report) |
| The gain comes from **disagreement between independent opening posts**: shared wrong answers were never recovered (0 of 28); different wrong answers were recovered 36–54% of the time; answer switches moved toward the correct answer 81 times and away 4 times | [`analysis/results/exploratory_v1.md`](analysis/results/exploratory_v1.md) | Exploratory |

**In one sentence:** when a model must reason in visible text, two agents that solve independently and then
argue beat voting, judging and self-refinement at equal cost; when hidden reasoning is available, a single model
reasoning internally is better and cheaper on these problems.

**Not pursued** (see the final report's *Next steps*): mechanism ablations on a dedicated set, a difficulty sweep
from 8 to 32 steps, a second model, GSM-Symbolic P2 as a no-harm check, dialogue between reasoning-on agents,
and the learned turn controller. Configs, frozen sets and loaders for these are in the repo.

## How it works

```
Problem ──► Agent A (accuracy) ─┐   independent opening posts:
        └─► Agent B (skepticism)┘   neither sees the other's
                    │
                    ▼
     Shared thread + facts ledger  ◄── posts alternate; every value shown with its working
                    │                   (each agent also has a private scratchpad)
         both agents agree on one answer? ── no ──► next post (up to 8)
                    │ yes
                    ▼
     Agent A writes the final answer from the shared thread only
```

- **Same model, same prompt template:** agents differ only in an objective paragraph (`prompts/objectives/`).
- **Memory:** a shared thread, a facts ledger (a fact is agreed only when the *other* agent confirms it), and
  private scratchpads that the other agent can never read (enforced in code and tests).
- **Turn controller:** Phase 1 heuristic (`dialogic/controller/`); its per-turn features are logged for a
  learned Phase 2 controller.
- **Cost:** prompts are laid out as an append-only prefix with explicit prompt-cache breakpoints, so
  re-sending the thread is billed mostly at cache-read rates.

## Problems and baselines

- **Generated problems** (`evals/synthetic.py`): random graphs of integer quantities rendered as English, with
  distractors, values to be worked out backwards, and implicit totals. Every answer is re-derived by an
  independent solver. Difficulty is a dial; frozen sets live in `evals/subsets/`.
- **Public benchmarks:** GSM8K (`evals/gsm8k.py`) and GSM-Symbolic P2 (`evals/gsm_symbolic.py`, downloaded at
  load time; not redistributed, see *Data licences*).
- **Baselines** (`evals/baselines.py`, `dialogic/self_refine.py`):
  - direct answer
  - chain of thought
  - self-consistency
  - k attempts + judge
  - self-refine (optionally starting from two independent drafts)
  - reasoning-on (single call or a vote)

  All are cost-matched to the dialogue with seeded per-problem mixtures (`evals/mixture.py`,
  `scripts/match_cost.py`).

## Quick start

```bash
uv sync                        # Python 3.11+, installs openai, pyyaml, tenacity, python-dotenv
cp .env.example .env           # set OPENAI_API_KEY (or OPENAI_API_KEY_A / _B) and MODEL
uv run pytest -q               # offline test suite (no API calls)

uv run python scripts/smoke_dialogue.py                                        # one live dialogue
uv run python -m dialogic.run configs/syn_dev50_dialogue.yaml                  # 50-problem dev run
uv run python -m dialogic.run configs/syn_dev50_baselines.yaml --match runs/<dialogue run>
uv run python scripts/compare_runs.py runs/<dialogue run> runs/<baselines run>
```

Each run writes `runs/<timestamp>_<config>/`: the config, `meta.json` (git hash, model), JSONL traces of every
call, turn and controller decision, `results.csv` and `summary.json`. `runs/` is gitignored. Experiments
used `gpt-5.6-luna` at `reasoning_effort: none`; a 50-problem dev comparison costs well under $1.

## Repository layout

```
dialogic/            orchestrator, agents, memory + ledger, post protocol, controller, synthesis,
                     LLM wrapper (cache, retries, prompt caching, usage), self-refine, runner
evals/               problem generator, dataset loaders, baselines, metrics, mixtures
prompts/             every prompt as a text file (never inline)
configs/             one YAML per experiment (calib/ and ablation/ for dev calibration)
scripts/             calibration, freezing sets, cost matching, power analysis, comparison and
                     pre-registered analysis scripts, log exploration
analysis/            pre-registrations, calibrations, result summaries and reports
docs/                findings, plans, related work
tests/               offline tests, including a snapshot that freezes the dialogue's prompts
```

## Research practice

- All tuning happens on dev sets. Each confirmatory claim gets a fresh frozen set, with the hypotheses, tests
  and analysis script **committed before** the run (`analysis/preregistration_*.md`).
- Every API call is traced; responses are cached by (model, messages, params), so reruns are free and
  identical.
- Sample sizes come from `scripts/power.py`, using observed discordance rates.
- Test sets are used once. `synthetic_test400` is spent.

## Data licences

- **GSM8K:** MIT, fetched from [openai/grade-school-math](https://github.com/openai/grade-school-math).
- **GSM-Symbolic:** [apple-aiml-research/ml-gsm-symbolic](https://github.com/apple-aiml-research/ml-gsm-symbolic)
  generated data, CC BY-NC-ND 4.0. Downloaded at load time and verified by checksum, never committed. Only
  the template-level dev/test split is in this repo.
- **Generated problems** in `evals/subsets/`: produced by this repo's generator.
