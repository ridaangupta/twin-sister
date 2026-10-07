# Pre-registration: confirmatory test-set run

Committed before any test-set problem is sent to a model. The test set
(`evals/subsets/synthetic_test400.jsonl`) has not been used for any development decision.

## Question
Does a two-agent dialogue between same-model agents beat single-agent reasoning at matched cost?

## Frozen setup
- Model: `gpt-5.6-luna`, `reasoning_effort: none`, temperature: API default for dialogue,
  CoT and judge calls; 0.7 for self-consistency samples.
- Problems: 400 generated problems (200 at 10 steps, 200 at 16 steps), seeds 2000–2001, disjoint
  from calibration (1000+) and dev (0–1) seeds.
- Dialogue: `configs/syn_test400_dialogue.yaml`, which is `syn_dev200_dialogue` with only the name,
  dataset path and `final_run` changed. Accuracy + skepticism objectives, independent opening posts,
  heuristic controller (max 8 posts, soft limit sampled from 150/300/600, private budget 200,
  hard cap 2× soft limit), single-writer synthesis by Agent A.
- Baselines: `configs/syn_test400_baselines.yaml`, run with `--match` on the dialogue run:
  direct, CoT, self-consistency with n = 7, and two attempts + judge.
  n = 7 was fixed on the dev set to match the dialogue's cost
  ($0.00418 per problem ÷ $0.00058 per sample = 7.2).
- Prompts, code and configs as of the commit that adds this file. Analysis:
  `scripts/analyze_test400.py`, also committed here and dry-run on dev data only.

## Primary hypothesis
**H1:** dialogue accuracy differs from cost-matched self-consistency (n = 7) on all 400 test
problems, with dialogue higher.
- Test: exact two-sided McNemar test on paired per-problem correctness, α = 0.05.
- Supported only if p < 0.05 and the accuracy difference is positive.
- Also reported: the difference with a paired bootstrap 95% CI (10,000 resamples, seed 0).

## Secondary comparisons (Holm-adjusted together, α = 0.05)
- **S1:** dialogue vs two attempts + judge, all 400.
- **S2:** dialogue vs self-consistency n = 7, 16-step problems only (200).
- **S3:** dialogue vs token-matched self-consistency (n = 5: majority of the first five of the seven
  draws, ties to the earliest draw), all 400.
- **S5:** dialogue vs chain of thought, all 400.

## Descriptive (not tested for significance claims)
- **S4:** when both first attempts are wrong, how often the final answer is right. For dialogue,
  "first attempts" means the two opening posts. For the judge baseline, it means the two attempts.
  The subsets differ by method, so the Fisher exact p is reported but not used for claims.
- Accuracy by difficulty level, tokens and cost per method.

## Rules fixed in advance
- **Failures:** the LLM wrapper retries transient errors, including sporadic `invalid_prompt`
  policy flags. A problem that still fails is re-run once; the local response cache makes completed
  calls replay identically. Anything still failing is scored as incorrect for that method and
  reported.
- **One run:** the test set is run once. No prompt, config or code change after this commit may
  affect the results. Any deviation will be reported in the results file.
- **What the dev set already showed:** dialogue 0.915 vs cost-matched self-consistency 0.860
  (p = 0.09), vs two attempts + judge 0.845 (p = 0.02). The test set has twice the problems.
