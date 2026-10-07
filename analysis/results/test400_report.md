# Test-set results (pre-registered: analysis/preregistration_test400.md)

Dialogue run: `runs/20261007T160631Z_syn_test400_dialogue`  
Baselines run: `runs/20261007T161733Z_syn_test400_baselines`  
Problems: 400 (200 at 10 steps, 200 at 16 steps). Missing (scored incorrect): {'dialogue': 0, 'self_consistency': 0, 'two_plus_judge': 0, 'cot': 0}

## Accuracy

| method | all | 10 steps | 16 steps | generated tokens/problem |
|---|---|---|---|---|
| dialogue | 0.915 | 0.965 | 0.865 | 1948 |
| self-consistency n=7 (cost-matched) | 0.812 | 0.885 | 0.740 | 2792 |
| self-consistency n=5 (token-matched) | 0.782 | 0.870 | 0.695 | (first 5 of the n=7 draws) |
| two attempts + judge | 0.800 | 0.895 | 0.705 | 953 |
| chain of thought | 0.650 | 0.765 | 0.535 | 396 |
| direct answer | 0.045 | 0.045 | 0.045 | 7 |

## Primary: dialogue vs cost-matched self-consistency (n=7), all 400

- dialogue 0.915 vs SC 0.812; difference +0.102, 95% CI [+0.060, +0.145]
- discordant: dialogue-only 60, SC-only 19; exact McNemar p = 0.0000
- **H1 (dialogue > SC at α = 0.05, two-sided): SUPPORTED**

## Secondary (Holm-adjusted across S1, S2, S3, S5)

| comparison | n | dialogue | other | diff | 95% CI | dlg-only | other-only | p | Holm p |
|---|---|---|---|---|---|---|---|---|---|
| S1 dialogue vs two_plus_judge (all 400) | 400 | 0.915 | 0.800 | +0.115 | [+0.075, +0.155] | 58 | 12 | 0.0000 | 0.0000 |
| S2 dialogue vs SC n=7 (16-step, 200) | 200 | 0.865 | 0.740 | +0.125 | [+0.055, +0.195] | 39 | 14 | 0.0008 | 0.0008 |
| S3 dialogue vs SC n=5 equal tokens (all 400) | 400 | 0.915 | 0.782 | +0.133 | [+0.090, +0.175] | 67 | 14 | 0.0000 | 0.0000 |
| S5 dialogue vs CoT (all 400) | 400 | 0.915 | 0.650 | +0.265 | [+0.217, +0.312] | 114 | 8 | 0.0000 | 0.0000 |

## S4 (descriptive): recovery when both first attempts are wrong

- dialogue: both opening posts wrong on 56 problems; final answer correct on 26 (46%)
- two attempts + judge: both attempts wrong on 84; judge correct on 20 (24%)
- Fisher exact p = 0.0062 (different problem subsets per method; descriptive only)

## Notes (added after the run; no change to the pre-registered analysis)

- Run once, no failures, no re-runs, no deviations from the pre-registration.
- Cost per problem with prompt caching: dialogue $0.00431, self-consistency n=7 $0.00411,
  two attempts + judge $0.00148, CoT $0.00058.
- Dialogue outcome by opening posts: both right 249/249 correct, one right 91/95, neither right 26/56.
- The baselines scored lower here than on the dev set (CoT 0.650 vs 0.740, SC n=7 0.812 vs 0.860)
  while the dialogue held at 0.915. All comparisons are paired on the same 400 problems.
