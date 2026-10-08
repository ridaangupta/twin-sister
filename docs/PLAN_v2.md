# Plan v2: making the claim robust, then testing whether it generalizes

Status: proposed, 2026-10-08. Builds on `docs/FINDINGS.md` and the pre-registered result in
`analysis/results/test400_report.md`: dialogue 0.915 vs cost-matched self-consistency 0.812.

**Goal:** before publishing, show that the dialogue's advantage survives the strongest baselines a
skeptical reviewer would ask for, explain where it comes from, and test whether it holds beyond one
model and one task family.

**Rule carried over:** every confirmatory claim gets its own fresh held-out set, frozen and
pre-registered (claims, tests, analysis script) before any model sees it. All tuning happens on the
dev set. `synthetic_test400` is used up.

---

## 0. Order of work and decision gates

| Phase | Workstream | Needs | Gate before moving on |
|---|---|---|---|
| 1 | WS1 Exploratory log analyses | Existing runs only | Write-up labelled exploratory; may sharpen the hypotheses for later phases |
| 1 | WS2 Shared infrastructure | – | Tests pass; cost-matching tool reproduces dev costs within 1% |
| 2 | WS3 Stronger baselines, tuned on dev | WS2 | Every baseline within ±2% of the dialogue's dev cost; tokens reported |
| 2 | WS7 Related work (drafting) | – | Citations verified against the papers themselves |
| 3 | WS4 Confirmatory test v2 (1,200 problems) | WS3, pre-registration | Pre-registration committed before the run |
| 4 | WS5 Mechanism ablations (separate 1,200-problem set) | WS2 | Pre-registration committed |
| 4 | WS6 Generalization: difficulty sweep, GSM-Symbolic P2, second model | WS2, WS3 | One pre-registration per set |
| 5 | Write-up | All | – |

**Dev-stage decision point.** If any stronger baseline matches or beats the dialogue on dev (most
likely reasoning-on or self-refine), the confirmatory run still goes ahead as pre-registered, and the
paper's framing changes to report it honestly. We do not retune the dialogue to win: its config is
frozen as `syn_test400_dialogue` for every comparison in this plan.

---

## WS1. Exploratory analysis of existing logs (no new API calls)

**Data:** `runs/20261007T160631Z_syn_test400_dialogue` and `…161733Z_syn_test400_baselines` (test),
plus the dev-200 runs.

**Output:** `scripts/explore_logs.py` writes `analysis/results/exploratory_v1.md`. Every table in it
is labelled exploratory: these sets have already been used, so these results raise hypotheses for
WS4–WS6 but can't confirm them.

### 1a. "Both openings wrong", split by kind of wrongness
- Split the 56 test problems into openings that gave the **same** wrong answer and openings that gave
  **different** wrong answers (or no answer). Report recovery for each.
- Repeat on dev-200 and on the sequential-openings ablation.
- Preliminary result, from a quick check while planning:
  - same wrong answer: 8 problems, **0 recovered**
  - different or missing answers: 48 problems, **26 recovered (54%)**

  If this holds, the mechanism is "disagreement triggers re-derivation", not "the skeptic finds hidden
  shared errors". The write-up needs to say so, and WS5 gets a matching hypothesis.

### 1b. Direction of answer switches
- For every answer change, classify it: wrong to correct, correct to wrong, or wrong to a different
  wrong answer. Split by agent, by turn and by difficulty.
- Preliminary result (test): **81** switches toward the correct answer, **4** away from it,
  **15** wrong to wrong.
- Also report each agent's "persuasion accuracy": when it holds out against a switch, how often it
  turns out to be right.

### 1c. Classifying the errors that get caught
Ground truth is available exactly: each problem regenerates from `meta.seed` via
`evals.synthetic.generate`, recovering every hidden quantity's true value, its operation, and
whether it's a distractor, a hidden (backward) leaf or an implicit total.

1. **Extract claims.** Parse each post for statements binding a known label ("lemons Alma", "the
   number of lemons Alma has") to a number, including inline LaTeX `\(=…=v\)` and `FACT+` lines.
   Labels are matched against the regenerated graph's (owner, item) pairs.
2. **First error per agent.** The earliest claim whose value differs from the truth.
3. **Classify it, deterministically:**
   - **Arithmetic:** the agent's own stated operands are correct and the relation is right, but the
     result is wrong.
   - **Misread relation:** the operands are correct but the operation, direction or constant is
     wrong (e.g. ×4 instead of ÷4, "more" read as "less").
   - **Distractor:** a distractor quantity was used as an operand.
   - **Backward step:** the wrong value is the hidden leaf, or depends on it first.
   - **Implicit total:** a total summed over the wrong set of items.
   - **Propagated:** wrong only because an earlier operand was wrong.
   - **Unclassified:** can't be parsed.
4. **What "caught" means.** The other agent's next post disputes the claim (a `FACT_DISPUTE`, or a
   restated correct value for that label) and the error doesn't survive into the final answer.
5. **Report:** an error-type × caught / not-caught table, broken down by objective (skepticism vs the
   simplicity ablation) and by opening vs later turn.
6. **Validation:** hand-label a random 60 classified errors. Report agreement, and an "unclassified"
   rate target under 20%. If extraction falls short, fall back to an LLM classifier from a different
   model family, also validated on the same 60.

---

## WS2. Shared infrastructure

| Change | Where | Why |
|---|---|---|
| Per-call `reasoning_effort` override on `LLM.complete` (in the cache key; traced) | `dialogic/llm.py` | The reasoning-on baseline mixes effort levels within one run |
| **Mixture policies**: a seeded per-problem choice between two settings with probability `p` (e.g. 7 or 8 samples; effort `low` or `medium`) | `evals/baselines.py` | Discrete knobs can't hit a cost exactly; a mixture matches the *mean* cost exactly |
| `scripts/match_cost.py`: reads dev runs, computes mean cost per problem per setting, solves for `k` / `p` / turn limits so each baseline lands within ±2% of the dialogue's dev cost, and writes the configs | new | Makes cost matching reproducible rather than hand-tuned |
| `scripts/power.py`: McNemar and TOST sample sizes from observed discordance rates (the calculation in §WS4) | new | Pre-registrations cite it |
| `analysis/prereg_template.md` + a generalized `scripts/analyze_prereg.py` (claims declared in YAML: comparisons, subsets, α, multiplicity family) | new | One analysis engine for WS4–WS6; no hand-edited scripts per set |
| Cluster-robust bootstrap and permutation test (by template) | `analyze_prereg.py` | GSM-Symbolic instances from the same template are correlated |
| Freeze new sets with disjoint seed ranges (table below) | `scripts/freeze_synthetic.py` | Fresh held-out data for each claim |
| `compare_runs.py`: also report cost ratio vs the dialogue and reasoning tokens | `scripts/` | Cost matching visible in every table |

**Cost-matching definition** (fixed in every pre-registration):
- Mean API cost per problem, priced from the run's config, including prompt-cache reads and writes,
  over the full set.
- Local response-cache replays are priced as if called.
- Matched on dev to within ±2%. On the test set, the realized cost ratio is reported. A drift beyond
  ±5% is flagged as a deviation, but the result still stands as pre-registered.
- Tokens are always reported alongside cost: generated, hidden reasoning, prompt, cached.

**Seed ranges** (all disjoint from dev 0–1, calibration 1000+, test400 2000–2001):

| Set | Seeds | Composition |
|---|---|---|
| `synthetic_test1200` (WS4) | 3000–3001 | 600 × 10 steps + 600 × 16 steps |
| `synthetic_ablation1200` (WS5) | 4000–4001 | 600 × 10 + 600 × 16 |
| `synthetic_sweep` dev / test (WS6a) | 5000+ / 5100+ | per level 8, 12, 16, 20, 24, 32: 50 dev, 200 test |
| `synthetic_model2` dev / test (WS6c) | 6000+ / 6100+ | Levels re-calibrated for model 2 |

---

## WS3. Stronger baselines, tuned to the dialogue's cost on dev

The target is the dialogue's dev-200 cost, **$0.00418 per problem** (1,881 generated tokens).
Each baseline is built, run on dev-200, and cost-matched with `match_cost.py`.

### 3a. Single-agent self-refine
Isolates "two agents" from "iterative critique".

- **Design.** One agent, Agent A with the accuracy objective, run through the same orchestrator
  machinery: the same post format, ledger, private budget, soft-limit sampling and turn cap.
  - Turn 0: a draft, with private work first, as in an opening.
  - Then alternating *critique* turns and *revise* turns: "review your previous post as a skeptical
    checker", then "revise in light of your critique".
  - It stops when a critique turn says `CONSENSUS: yes` with the same answer as the draft it reviewed,
    or at the turn cap.
- **The two variants that matter:**
  1. *Self-refine with skeptic prompt:* critique turns use the skepticism objective, so the only
     difference from the dialogue is that one agent sees all of its own work.
  2. *Self-refine with independent redraft:* an extra turn 1 that re-solves the problem without seeing
     turn 0, then reconciles. This is the single-agent analogue of independent openings. It tells us
     whether "two agents" matters at all beyond "two independent drafts".
- **Implementation:** `method: self_refine` in `dialogic/run.py`, built from `Memory`, `Agent` and
  the controller, with one agent ID and mode-specific tails `turn_critique.txt` / `turn_revise.txt`.
  Traces use the dialogue's format, so WS1's analyses work on it unchanged.
- **Cost matching:** tune `max_turns` and the soft-limit set on dev until the mean cost is within ±2%.
  The private budget stays the same as the dialogue's.

### 3b. Single call with reasoning on
The baseline a practitioner would actually use.

- `gpt-5.6-luna`, one call, hidden reasoning at effort `low`, `medium` or `high`, with the
  **free-form** step-by-step prompt. Calibration showed the structured WORKING format hurts at
  reasoning effort `medium` (0.47 vs 0.83), and this baseline must be at its strongest.
- **Cost matching:** effort is discrete, so measure each level's dev cost, then use a seeded mixture
  of the two levels that bracket $0.00418 so the mean matches within ±2%.
  - If even `high` costs less than the dialogue, add self-consistency over reasoning-on calls
    (n samples at one level) to reach matched cost.
  - If `low` already costs more, report that and use `low` alone, with the cost gap stated.
- Hidden reasoning tokens are reported separately. "Matched tokens" for this baseline includes them.
- **Prompt check on dev:** try 2–3 prompt variants (free-form, free-form + answer guarantee, WORKING)
  and keep the best for the confirmatory run. This is fair, since the dialogue's prompts were also
  developed on dev.

### 3c. Judge at equal budget
- `k` independent CoT attempts (the self-consistency draws, temperature 0.7) plus **one judge call
  that sees all k**. The judge is called whenever any answers disagree, and its budget is the
  dialogue's mean generated tokens minus the attempts' tokens.
- **Cost matching:** pick `k` (about 4 expected), then a k / k+1 mixture to land within ±2%.
- Generalizes `two_plus_judge` to `k_plus_judge`, and reuses the self-consistency draws through the
  response cache.

### 3d. Self-consistency at exactly equal cost
- Draw 8 samples per problem. Score a seeded per-problem mixture of the majority over the first 7 and
  over all 8, with `p` chosen so the mean cost matches within ±2%.
- One run gives n = 5, 7, 8 and the mixture post hoc, with no extra calls beyond the 8th sample.

### 3e. Deliverable
A dev table: accuracy, cost ratio to the dialogue (target 0.98–1.02), generated, reasoning and prompt
tokens, and the configs written by `match_cost.py`. **Gate:** all four baselines within ±2% on dev.

---

## WS4. Confirmatory test v2

### Sizing (from `scripts/power.py`, using observed discordance)
Observed total discordance between the dialogue and a baseline: 0.16–0.20 (dev SC-7 0.175, test
SC-7 0.198, test judge 0.175). Against stronger baselines we expect smaller gaps. With 4 primary
comparisons under Holm correction (worst case α = 0.0125) at 16% discordance:

| True gap | Problems for 80% power | Problems for 90% power |
|---|---|---|
| 7 pts | 362 | 462 |
| 5 pts | 711 | 910 |
| 4 pts | 1,113 | 1,424 |
| 3 pts | 1,980 | 2,535 |

**Choice: 1,200 problems** (600 at 10 steps, 600 at 16 steps). That's 80% power for a 4-point gap and
over 90% for 5 points, at about $30 for all methods. Going to 2,000 problems for 3 points roughly
doubles cost; revisit only if dev gaps come in under 4 points.

### Pre-registration (`analysis/preregistration_test1200.md`)
- **Primary family** (Holm across 4, α = 0.05 overall): dialogue vs each of
  1. self-refine (the stronger of the two 3a variants, chosen on dev)
  2. reasoning-on
  3. judge at equal budget
  4. self-consistency at exact cost

  Test: exact McNemar, two-sided, with the paired bootstrap 95% CI of the difference.
- **Secondary family:** the same comparisons on 16-step problems only, plus CoT. Holm-corrected.
- **Descriptive:** the WS1 analyses re-run on these fresh logs (same vs different wrong openings,
  switch direction, error classes), now with fixed definitions.
- Rules for failures, costs and deviations as in the first pre-registration, plus the cost-drift rule
  from WS2.
- Frozen configs: `syn_test1200_dialogue.yaml` (identical to `syn_test400_dialogue` apart from
  name and path) and `syn_test1200_baselines.yaml` (written by `match_cost.py`).

---

## WS5. Mechanism ablations on their own held-out set

`synthetic_ablation1200` (seeds 4000–4001). Each ablation is compared with the frozen dialogue run on
the same set. One pre-registration covers all three, Holm across them.

| Ablation | Change | Matching | Claim and test |
|---|---|---|---|
| 5a Sequential openings, budget-matched | `independent_openings: false`; raise `max_turns` / soft limits until the dev cost is within ±2% of the dialogue's | ±2% cost | Independent openings beat sequential (McNemar). Also report the openings' disagreement rate and the both-wrong rate. |
| 5b Objective swap | B: simplicity instead of skepticism | Same config | **Equivalence**: two one-sided tests with a ±3-point margin, 90% power. That needs about 810–1,140 problems at the observed 8.5–12% discordance, so 1,200 is enough. Supported: "no difference larger than 3 points"; otherwise report the CI. |
| 5c Private scratchpads off | `scratch_budget: 0`, with the turn budget raised to match cost | ±2% cost | Scratchpads help or don't (two-sided McNemar) |
| 5d (from WS1, if confirmed) Disagreement mechanism | No new run: pre-register "recovery when openings give different wrong answers > recovery when they give the same wrong answer" on the 5a–5c logs plus the dialogue run | – | Fisher exact |

Cost: about 4 dialogue-sized runs × 1,200 × $0.0043, roughly **$21**, plus dev tuning for 5a and 5c.

---

## WS6. Generalization

Each part has its own frozen set and pre-registration. The baselines are SC at exact cost and
whichever WS3 baseline is strongest on dev, so each set gets two comparisons, with Holm within the set.

### 6a. Difficulty sweep (8–32 steps)
- Levels 8, 12, 16, 20, 24 and 32 steps, 200 test problems each (1,200), plus 50 dev problems each
  for a truncation check.
- **Check first on dev:** at 24–32 steps, posts capped at 600–1,200 tokens may be cut off. If the
  truncation rate goes over 10%, pre-register a scaled config (soft limits proportional to `n_ops`)
  as the sweep's dialogue, stated as a deviation from the frozen config.
- **Pre-registered claims:**
  1. The dialogue's gain over the baseline increases with steps. Test: logistic regression of
     correctness on method × `n_ops` (problem as random effect, or a cluster bootstrap); one-sided
     test on the interaction.
  2. Per-level gains are reported with CIs (descriptive).
- **Output:** a chart of accuracy vs steps for each method, and of gain vs steps with CI bands.
- Cost: about $15–20, since longer problems cost more.

### 6b. Public benchmark: GSM-Symbolic P2
- **Data:** the [apple/ml-gsm-symbolic](https://github.com/apple/ml-gsm-symbolic) generated
  instances (50 per template). Check the license and the exact P2 counts on download.
  Add a loader in `evals/gsm_symbolic.py` with a pinned sha256.
- **Split by template,** not by instance: half the templates for dev, half for test, so no test
  template has been seen. Analysis is cluster-robust by template.
- **Headroom check on dev first.** If single-agent CoT is over 90%, P2 can't show a gain. In that case
  report it as an external check of "no harm on easier data" rather than a gain test, and say so in
  the pre-registration.
- **Wording:** P2 has no closed-world or answer-guarantee preamble. Pre-register a single wording,
  either the benchmark's own text or the same preamble prepended for every method, decided on dev.
- Cost: about $20–25 for roughly 1,000 test instances × the dialogue plus 2 baselines.

### 6c. Second model
- **Recommended: `gpt-5.4-mini` at reasoning effort `none`.** The same knobs and prompts transfer,
  it's a different size and generation, and it costs 3.75× per token.
  - Alternative: `gpt-4.1-mini`, a true non-reasoning model from an older family. It's very verbose
    (about 7k tokens per CoT), so the soft limits would need re-tuning: a bigger deviation from the
    frozen config.
- **Re-calibrate difficulty** for the second model so its single-agent CoT sits near the same ~87% /
  ~47% band, using `calibrate_synthetic.py --model`. Freeze `synthetic_model2` at those levels.
- **Watch `invalid_prompt` flags**, already seen once on `gpt-5.4-mini`. The retry handles them;
  report the rate.
- Cost: about $40 at 1,200 problems × dialogue + 2 baselines at 3.75× price.

---

## WS7. Related work and positioning

**Draft:** `docs/related_work.md`, later the paper's related-work section. Verify every citation
against the paper itself (title, authors, venue, the claim attributed) before it's used. None below
has been checked yet.

- **Multi-agent debate:**
  - Du et al. 2023, *Improving Factuality and Reasoning in Language Models through Multiagent Debate*
  - Liang et al. 2023, *Encouraging Divergent Thinking in LLMs through Multi-Agent Debate* (MAD)
  - Chan et al. 2023, *ChatEval*
- **Compute-matched critiques** (debate doesn't reliably beat cheaper strategies):
  - Smit et al. 2024, *Should we be going MAD? A Look at Multi-Agent Debate Strategies for LLMs*
  - Wang et al. 2024, *Rethinking the Bounds of LLM Reasoning: Are Multi-Agent Discussions the Key?*
  - search for 2025–2026 follow-ups
- **Single-agent alternatives:**
  - Wang et al. 2023, *Self-Consistency*
  - Madaan et al. 2023, *Self-Refine*
  - Huang et al. 2024, *Large Language Models Cannot Self-Correct Reasoning Yet*
- **Generated reasoning benchmarks:** GSM-Symbolic, GSM-Infinite, BeyondBench.

**Positioning.** Present the result as evidence on the open question of whether debate beats
compute-matched single-agent methods, under precisely stated conditions:
- the same model on both sides, reasoning effort none (all reasoning visible)
- independent openings
- generated multi-step arithmetic in a 47–87% single-agent accuracy band
- matched on API cost with prompt caching

The emphasis should be what is new: (i) cost matching that includes caching; (ii) pre-registration on
fresh data; (iii) the mechanism evidence that gains come from disagreement between independent
openings.

---

## Budget and timeline (estimates)

| Item | API cost | Effort |
|---|---|---|
| WS1 exploratory analyses | $0 | 1–2 days (the error classifier is most of it) |
| WS2 infrastructure | under $1 (smoke runs) | 1–2 days |
| WS3 baselines on dev, including cost tuning | about $5–8 | 2–3 days |
| WS4 test v2 (1,200 problems) | about $30 | half a day to run and analyse |
| WS5 ablations (1,200 problems) | about $21 + $3 dev | 1 day |
| WS6a sweep | about $15–20 | 1 day |
| WS6b GSM-Symbolic P2 | about $20–25 | 1–2 days (loader, split, headroom check) |
| WS6c second model | about $40 + $5 calibration | 1 day |
| WS7 related work | $0 | 1–2 days |
| **Total** | **about $160–180** | **about 2 weeks** |

The Batch API halves the cost of the confirmatory runs (WS4–WS6) if latency doesn't matter. That
brings the total to about $100.

---

## Open decisions (recommendations in bold)

1. **Test v2 size:** **1,200** (80% power for a 4-point gap), or 2,000 for 3 points.
2. **Primary family:** **all four stronger baselines, with Holm correction**, or just the single
   strongest one on dev (more power, but chosen after looking).
3. **Second model:** **`gpt-5.4-mini` at effort `none`**, or `gpt-4.1-mini`.
4. **Sweep at 24–32 steps:** keep the frozen dialogue config and report truncation, or **pre-register
   a length-scaled config if dev truncation exceeds 10%**.
5. **Reasoning-on budget:** **a mixture of effort levels to match cost**, or a single effort level
   with the cost gap reported.

## Risks

- **A stronger baseline may beat the dialogue.** Reasoning-on or self-refine winning is a real
  possibility. The plan treats that as a publishable finding, not something to tune away.
- **Cost matching on dev may not carry over to test** (the per-problem cost mix shifts). Handled by
  the drift rule: report it, and flag it if over ±5%.
- **The error classifier may be too coarse.** Validated against 60 hand labels, with an LLM fallback.
- **GSM-Symbolic P2 may be at ceiling for `gpt-5.4-luna`-class models.** Pre-registered fallback
  framing.
- **API changes** (pricing, caching, `invalid_prompt` behaviour) would affect cost matching. Record
  pricing in every run config, as now.
