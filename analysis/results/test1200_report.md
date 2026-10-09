# Visible-reasoning confirmatory results (pre-registered: analysis/preregistration_test1200.md)

Runs: `20261008T203731Z_syn_test1200_dialogue`, `20261008T193422Z_syn_test1200_baselines`, `20261009T003300Z_syn_test1200_self_refine`  
Problems: 1200 (600 at 10 steps, 600 at 16 steps). Missing (scored incorrect): {'dialogue': 0, 'direct': 0, 'cot': 0, 'self_consistency': 0, 'k_plus_judge': 0, 'reasoning': 0, 'self_refine_redraft': 0}

## Accuracy, tokens and realized cost

| method | all | 10 steps | 16 steps | generated tokens/problem | $/problem | cost ratio to dialogue |
|---|---|---|---|---|---|---|
| dialogue | 0.928 | 0.970 | 0.887 | 1874 | 0.00470 | 1.000 |
| self_consistency | 0.812 | 0.888 | 0.737 | 2822 | 0.00416 | 0.885 (drift) |
| k_plus_judge | 0.854 | 0.922 | 0.787 | 2660 | 0.00424 | 0.902 (drift) |
| self_refine_redraft | 0.897 | 0.937 | 0.858 | 1891 | 0.00450 | 0.957 |
| reasoning | 0.992 | 0.995 | 0.988 | 3143 | 0.00413 | 0.878 (drift) |
| cot | 0.693 | 0.817 | 0.568 | 399 | 0.00059 | 0.125 |
| direct | 0.047 | 0.055 | 0.038 | 7 | 0.00011 | 0.023 |

## Primary family: dialogue vs each cost-matched baseline, all 1,200 (Holm, α = 0.05, two-sided)

| comparison | predicted | dialogue | other | diff | 95% CI | dlg-only | other-only | p | Holm p | verdict |
|---|---|---|---|---|---|---|---|---|---|---|
| dialogue vs self_consistency | dialogue higher | 0.928 | 0.812 | +0.116 | [+0.092, +0.139] | 173 | 34 | 1.282e-23 | 5.129e-23 | **SUPPORTED (dialogue higher)** |
| dialogue vs k_plus_judge | dialogue higher | 0.928 | 0.854 | +0.074 | [+0.052, +0.096] | 131 | 42 | 7.552e-12 | 1.51e-11 | **SUPPORTED (dialogue higher)** |
| dialogue vs self_refine | dialogue higher | 0.928 | 0.897 | +0.031 | [+0.012, +0.051] | 91 | 54 | 0.002668 | 0.002668 | **SUPPORTED (dialogue higher)** |
| dialogue vs reasoning | dialogue lower | 0.928 | 0.992 | -0.063 | [-0.078, -0.048] | 5 | 81 | 9.579e-19 | 2.874e-18 | **SUPPORTED (dialogue lower, as predicted)** |

## Secondary family (Holm within the family)

| comparison | n | dialogue | other | diff | 95% CI | p | Holm p |
|---|---|---|---|---|---|---|---|
| dialogue vs self_consistency, 16 steps | 600 | 0.887 | 0.737 | +0.150 | [+0.113, +0.187] | 1.819e-15 | 5.456e-15 |
| dialogue vs k_plus_judge, 16 steps | 600 | 0.887 | 0.787 | +0.100 | [+0.065, +0.137] | 6.528e-08 | 1.306e-07 |
| dialogue vs self_refine, 16 steps | 600 | 0.887 | 0.858 | +0.028 | [-0.003, +0.062] | 0.1074 | 0.1074 |
| dialogue vs reasoning, 16 steps | 600 | 0.887 | 0.988 | -0.102 | [-0.128, -0.077] | 6.801e-16 | 2.72e-15 |
| dialogue vs cot, all | 1200 | 0.928 | 0.693 | +0.236 | [+0.210, +0.262] | 4.315e-66 | 2.157e-65 |

## Descriptive: both openings wrong, same vs different answers (WS1 hypothesis on fresh data)

- same wrong answer: 16 problems, recovered 2 (12%)
- different wrong answers (or none): 115 problems, recovered 56 (49%)
- Fisher exact p = 0.006689 (descriptive; the WS5 ablation set carries the pre-registered test)

## Deviations and notes (added after the run; the pre-registered analysis above is unchanged)

1. **Failures and re-runs, as the pre-registered rule specifies.**
   - The first dialogue run hit a ~30-minute API outage (`APIConnectionError`, 909 problems) and was re-run
     once: `20261008T203731Z_syn_test1200_dialogue`, 1,200 of 1,200, no errors.
   - Self-refine stopped when the API account ran out of credits (`429`, 347 problems). After a top-up it
     was re-run once: `20261009T003300Z_syn_test1200_self_refine`, 1,200 of 1,200, no errors.
   - Both re-runs replayed completed calls from the local response cache. No problem is scored as
     missing.
   - The jobs were also suspended for about 80 minutes at the user's request, and resumed.
2. **Cost-matching drift (flagged above).** The dialogue cost $0.00470 per problem on test against $0.00418
   on dev, which puts self-consistency, the judge and reasoning-on at 0.88–0.90 of its cost.
   - **The cause is prompt caching, not the method.** Generated tokens matched dev (1,874 vs 1,881), but
     the cache-read share of prompt tokens fell from 58.9% (dev) to 46.1%, and the write share rose from
     25.5% to 38.3%. Calls replayed from the outage run carry that run's degraded caching (40% reads), and
     dialogues resumed hours later found their 30-minute prompt cache expired, so they wrote it again.
   - **Sensitivity check.** Re-priced at the dev cache mix, the test dialogue costs $0.00417 per problem
     (planned $0.00418). Cost ratios to it are then: self-consistency 0.997, judge 1.016,
     self-refine 1.079, reasoning-on 0.990.
   - **Direction.** The baselines were not disadvantaged by the method. On generated tokens,
     self-consistency, the judge and reasoning-on received 51%, 42% and 68% more than the dialogue
     (2,822, 2,660 and 3,143 against 1,874).
3. **Scope.** These results hold for visible reasoning (`reasoning_effort: none`). The pre-registered
   reasoning-on comparison (P4) confirms that hidden reasoning beats the dialogue: 0.992 vs 0.928,
   81 vs 5 discordant problems.
