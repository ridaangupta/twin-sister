# Dialogic Reasoning: final report

2026-10-09 · Markdown copy of the [research report](https://claude.ai/artifact/UfTK6FAnYTNi3Ua1vPwGKY). Full detail
(decision log, friction log, every run) is in [`FINDINGS.md`](FINDINGS.md).

Two copies of one model that solve a problem independently and then argue beat every cost-matched single-model
method we tested, but only when the reasoning has to be visible. With hidden reasoning switched on, a single model
reasoning internally wins clearly at the same cost. Both results come from pre-registered tests on 1,200 problems
no model had seen.

## Question and setup

We asked whether a turn-based dialogue between two instances of the same model reasons better than one instance at
the same API cost, and what drives any difference.

- **Model:** `gpt-5.6-luna`. The main setting uses reasoning effort `none`, so every reasoning step is visible
  text. Hidden reasoning was added as a comparison once it turned out to matter.
- **Agents:** identical except for one objective paragraph: Agent A is responsible for accuracy, Agent B for
  finding flaws.
  - Both write to one shared thread and a ledger of facts. A fact counts as agreed only when the other agent
    confirms it.
  - Each agent also has a private scratchpad the other can never read.
- **Problems:** generated chains of 10 or 16 dependent quantities, with distractors, a value to work out
  backwards, and implicit totals.
  - They can't have been memorized, and an independent solver re-derives every answer.
  - A single agent reasoning step by step scores about 87% at 10 steps and 47% at 16.
- **Practice:** all tuning happened on 200 dev problems. Each claim was then confirmed once, on a fresh frozen
  set, with the hypotheses, tests and analysis script committed beforehand.
- **Spend:** about $40 of API calls in total.

## Method

```
Problem ──► Agent A (accuracy) ─┐   independent opening posts:
        └─► Agent B (skepticism)┘   neither sees the other's
                    │
                    ▼
     Shared thread + facts ledger  ◄── posts alternate; every value shown with its working
                    │
         both agents agree on one answer? ── no ──► next post (up to 8)
                    │ yes
                    ▼
     Agent A writes the final answer from the shared thread only
```

## Results

All four pre-registered comparisons came out as predicted on 1,200 fresh problems, with every baseline matched to
the dialogue's cost per problem (Holm-corrected exact McNemar, p ≤ 0.003).
([pre-registration](../analysis/preregistration_test1200.md) · [report](../analysis/results/test1200_report.md))

| Method | Accuracy | 10 steps | 16 steps | Generated tokens per problem | Dialogue minus method, pts (95% CI) |
|---|---|---|---|---|---|
| Reasoning on: vote over 3–4 calls | 0.992 | 0.995 | 0.988 | 3,143 | −6.3 [−7.8, −4.8] |
| **Dialogue (visible reasoning)** | **0.928** | **0.970** | **0.887** | 1,874 | – |
| Self-refine from two independent drafts | 0.897 | 0.937 | 0.858 | 1,891 | +3.1 [+1.2, +5.1] |
| k attempts + judge (k = 6–7) | 0.854 | 0.922 | 0.787 | 2,660 | +7.4 [+5.2, +9.6] |
| Self-consistency (7–8 votes) | 0.812 | 0.888 | 0.737 | 2,822 | +11.6 [+9.2, +13.9] |
| Single chain of thought | 0.693 | 0.817 | 0.568 | 399 | +23.6 (reference) |
| Direct answer | 0.047 | 0.055 | 0.038 | 7 | reference |

- **Visible reasoning:** the dialogue beats voting, judging and self-refinement at equal cost. Its lead grows on
  the harder 16-step problems (+15.0 vs self-consistency, +10.0 vs the judge), but not against self-refine (+2.8,
  not significant).
- **Hidden reasoning:** it wins outright. A vote over reasoning-on calls beats the dialogue on 81 problems and
  loses on 5. Even a single reasoning-on call at effort low scored 0.970 on dev, at 24% of the dialogue's cost.
- **Replication:** an earlier pre-registered test on 400 problems gave the same result against self-consistency:
  0.915 vs 0.812 (+10.2, p < 0.0001) ([report](../analysis/results/test400_report.md)).
- **Cost note:** the dialogue's realized test cost ran 12% over plan, because an API outage and a long pause
  degraded prompt caching. At the planned cache rate the baselines sat at 0.99–1.08× its cost, and they generated
  42–68% more tokens.

## Why it works

The advantage comes from structure: two independent first attempts, then an argument that settles their
disagreement.

| Opening posts (test, 1,200 problems) | Problems | Final answer correct |
|---|---|---|
| Both right | 783 | 783 (100%) |
| One right, one wrong | 286 | 273 (95%) |
| Both wrong, different answers | 115 | 56 (49%) |
| Both wrong, same answer | 16 | 2 (12%) |

- **Independence is the active ingredient.** When the second agent could read the first agent's opening, accuracy
  fell 6 points on dev, and shared wrong answers rose from 3 to 14 of 200. The second agent anchored on the first.
- **Disagreement triggers re-derivation.** Recovery is high when two wrong answers differ, and near zero when they
  match. Two copies of one model rarely find an error they both made the same way.
- **Updates move toward the truth.** 244 answer switches went to the correct answer and 16 away from it. That is
  the opposite of the "debate is a martingale" result reported elsewhere (Choi et al., NeurIPS 2025). Requiring
  every number to come with its working seems to make challenges checkable.
- **The partner's objective barely matters.** Skepticism and simplicity differed by 1.5 points on dev, which is
  not significant.
- **Most common first error:** misjudged implicit totals ("the total number of items X has"), followed by
  arithmetic slips. Totals are also the error least often corrected
  ([exploratory](../analysis/results/exploratory_v1.md)).

## What did not work

- **Hidden reasoning dominates.** A single reasoning-on call scored 0.970–1.000 on dev at 24–51% of the
  dialogue's cost ([cost matching](../analysis/results/cost_matching.md)). The dialogue's advantage exists only
  when reasoning has to be visible.
- **Two agents without independence add little.** Sequential openings lost 6 points. Self-refine starting from two
  independent drafts came within 3 points of the dialogue, so most of the gain comes from independent drafts, not
  from having a second agent.
- **Public benchmarks lacked headroom.** GSM8K was near ceiling and likely memorized. On GSM-Symbolic P2,
  single-agent step-by-step already scored 0.915 (dev sample), so it can only be a "no harm" check:
  dialogue 0.970, reasoning-on 0.970.
- **Early dialogue versions failed in instructive ways:** scratchpads copied the post, agents agreed a solvable
  problem was unsolvable, and the second speaker copied the first.

## Limitations

- **Untested:** other models, public benchmarks with headroom, longer problems, and domains such as finance.
- **The task suits a skeptic.** The problems have checkable structure (whole numbers, explicit relations).
- **Shared blind spots.** Same-model agents almost never fixed a wrong answer they reached independently in the
  same way.
- **Cost drift.** Cost matching held on dev, but the test run's realized cost drifted for infrastructure reasons;
  the report quantifies this.
- **Exploratory analyses** describe the logs; they do not prove a mechanism.
- **Use cases untested.** None of the use cases below has been tried in practice.

## Where this is useful

Dialogue earns its cost when reasoning has to stay in the open and errors can be checked. Where hidden reasoning
is allowed, try that first.

| Situation | Why dialogue fits | Caveat |
|---|---|---|
| Audited or regulated calculations (finance, compliance, engineering checks) | Every step and every disagreement is in the trace for review | A hidden-reasoning model is cheaper if its output alone is acceptable |
| Models or deployments without hidden reasoning (small or open models, cost-limited tiers) | Independent attempts plus argument beat voting at equal cost | Shown here on one model only |
| Agent pipelines before irreversible actions | Disagreement between independent plans flags risk, and arguing it out often finds the fix | Shared mistakes slip through; adds about 4 sequential turns of latency |
| Data and label quality checks | Independent graders plus discussion settle disagreements better than a vote | Gains shrink as single-pass accuracy nears 100% |

**A practical signal from the logs:** when two independent attempts agree, the answer was right 98% of the time.
When they disagree, a short argument recovers most cases where one was right, and about half where both were
wrong.

## Next steps (not pursued)

The project closes here. These were planned, prepared where noted, and left for future work
([plan](PLAN_v2.md)):

1. **Mechanism ablations** on a dedicated 1,200-problem set: sequential openings at a matched budget, an
   equivalence test on the objective swap, and private scratchpads switched off. Configs and the frozen set are
   ready.
2. **A difficulty sweep** from 8 to 32 steps, to chart how the gain scales with problem length. The sets are
   frozen.
3. **A second model** with re-calibrated difficulty, and GSM-Symbolic P2 as a public "no harm" check. The loader
   and the template-level split are ready.
4. **Dialogue between reasoning-on agents** on harder problems (48–64 steps), to test whether dialogue adds
   anything on top of hidden reasoning. This is the most practically relevant open question.
5. **The original roadmap:** the other answer-synthesis strategies, a learned turn controller trained on the
   roughly 3,000 logged dialogues, and finance tasks (FinQA).

## Sources

See [`related_work.md`](related_work.md) for verified citations: multi-agent debate (Du et al., Liang et al.,
Chan et al.), compute-matched critiques (Smit et al., Wang et al., Zhang et al., Choi et al., Hu et al.), and
single-agent methods (self-consistency, Self-Refine, Huang et al.).
