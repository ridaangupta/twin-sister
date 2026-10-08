# Pre-registration: visible-reasoning confirmatory run (test1200)

Committed before any `synthetic_test1200` problem is sent to a model. The set (1,200 problems,
seeds 3000–3001, 600 at 10 steps and 600 at 16 steps) was frozen on 2026-10-08 and has not been used
for any decision.

## Question and scope
Within the **visible-reasoning regime** (`gpt-5.6-luna`, reasoning effort `none`, all reasoning in
text), does the two-agent dialogue beat the strongest single-agent and ensemble alternatives at
**matched cost**?

A single call with hidden reasoning on is included as the practitioner's reference point. Dev data
already showed it ahead at a quarter of the dialogue's cost, so the dialogue is **predicted to lose**
that comparison. This reflects the decision, made after dev calibration, to scope the claim to
visible reasoning (`docs/FINDINGS.md` §16).

## Frozen setup
- **Dialogue:** `configs/syn_test1200_dialogue.yaml`, identical to `syn_test400_dialogue` and
  `syn_dev200_dialogue` apart from name and path. Prompts are pinned by `tests/test_frozen_dialogue.py`.
- **Baselines:** `configs/syn_test1200_baselines.yaml` and `configs/syn_test1200_self_refine.yaml`.
  Each was cost-matched on dev-200 to the dialogue's $0.00418 per problem, using seeded per-problem
  mixtures (`analysis/results/cost_matching.md`):

  | Baseline | Setting | Dev expected cost ratio |
  |---|---|---|
  | Self-consistency | 7 or 8 CoT samples, 8 with probability 0.123; temperature 0.7 | 1.000 |
  | k attempts + judge | k = 6 or 7, 7 with probability 0.060; judge only when the attempts disagree | 1.000 |
  | Self-refine | two independent drafts, then critique/revise; at least 3 or 5 posts before stopping, 5 with probability 0.278 | 1.000 |
  | Reasoning on | majority vote over 3 or 4 calls at effort medium, 4 with probability 0.478; free-form prompt | 1.000 |

  Also run: direct answer and single CoT, as reference points.
- **Budget:** fixed at 1,881 tokens (the dev dialogue's mean generated tokens) for the CoT budget and
  the sample and judge caps. It is not derived from the test run.
- **Cost:** API pricing in each config, including prompt-cache reads and writes; local-cache replays
  priced as if called.
- **Analysis:** `scripts/analyze_test1200.py`, committed with this file and dry-run on dev data only.

## Primary family: four comparisons, Holm-corrected, α = 0.05, exact two-sided McNemar

| | Comparison (all 1,200) | Predicted | Dev evidence (exploratory) |
|---|---|---|---|
| P1 | dialogue vs self-consistency | dialogue higher | +4.5 vs 8 samples, p = 0.18 |
| P2 | dialogue vs k attempts + judge | dialogue higher | +2.5 vs k = 6, n.s. |
| P3 | dialogue vs self-refine | dialogue higher | +3.0 to +5.0 vs nearby settings, n.s. |
| P4 | dialogue vs reasoning on | dialogue lower | −7.5 at effort medium, single call |

- **Supported:** Holm-adjusted p < 0.05 with the difference in the predicted direction.
- **Reversed:** Holm-adjusted p < 0.05 in the opposite direction.
- **No significant difference** otherwise.

Each comparison reports the difference and a paired bootstrap 95% CI (10,000 resamples, seed 0).

**Power** (`scripts/power.py`): 1,200 problems give about 80% power for a 4-point gap at 16%
discordance under Holm across 4. The dev gaps for P2 and P3 are smaller than that, so a null result
there is plausible and will be reported as such.

## Secondary family (Holm within the family)
- S1–S4: P1–P4 restricted to the 600 16-step problems.
- S5: dialogue vs single CoT.

## Descriptive (no confirmatory claims)
- Accuracy by level, generated tokens, realized cost per problem, and cost ratio to the dialogue.
  A realized ratio outside 0.95–1.05 is flagged as a cost-matching deviation; the comparison still
  stands as run.
- Both openings wrong, split into same vs different wrong answers, with recovery rates (the WS1
  hypothesis on fresh data). The pre-registered test of it belongs to the WS5 ablation set.

## Interpretation, committed in advance
- **P1–P3 all supported:** "In the visible-reasoning regime, dialogue beats cost-matched voting,
  judging and self-refinement."
- **Some not significant:** report exactly which, with CIs. Write "no detectable advantage at matched
  cost" for those, not "equivalent".
- **P4 supported, as predicted:** "Hidden reasoning dominates; the dialogue's advantage is specific to
  visible reasoning."
- **Any result** is reported with the dev-stage finding that a single reasoning-on call reached
  0.970–1.000 at 24–51% of the dialogue's cost.

## Rules
- **Failures:** the wrapper retries transient errors, including sporadic `invalid_prompt` flags. A
  problem that still fails is re-run once; the local response cache replays completed calls.
  Anything still failing is scored incorrect and reported.
- **One run:** the test set is run once. No prompt, config or code change affecting results after
  this commit. Any deviation is reported in `analysis/results/test1200_report.md`.
