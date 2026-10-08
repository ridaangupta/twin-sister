# Related work and positioning (PLAN_v2 WS7, draft)

Status 2026-10-08. Each entry was checked against the venue page, arXiv or proceedings this session
(links given), except where marked *from memory*. Check those before submission.

## Multi-agent debate

- **Du et al., *Improving Factuality and Reasoning in Language Models through Multiagent Debate*,
  ICML 2024** ([PMLR](https://proceedings.mlr.press/v235/du24e.html), [arXiv 2305.14325](https://arxiv.org/abs/2305.14325)).
  Several instances propose answers and debate over rounds toward a common answer. Reports gains on
  arithmetic, GSM8K and strategic reasoning, and on factuality. The closest ancestor of our setup,
  but without cost-matched baselines.
- **Liang et al., *Encouraging Divergent Thinking in Large Language Models through Multi-Agent Debate*
  (MAD), EMNLP 2024** ([ACL Anthology](https://aclanthology.org/2024.emnlp-main.992/)). Agents argue
  "tit for tat" and a judge manages the debate, to counter a single model's "degeneration of thought".
- **Chan et al., *ChatEval*, ICLR 2024**
  ([proceedings](https://proceedings.iclr.cc/paper_files/paper/2024/hash/25cc3adf8c85f7c70989cb8a97a691a7-Abstract-Conference.html)).
  Multi-agent debate as an evaluator ("referee team") of text quality.

## Critiques: does debate beat cheaper strategies at matched compute?

- **Smit et al., *Should we be going MAD? A Look at Multi-Agent Debate Strategies for LLMs*, ICML 2024**
  ([PMLR](https://proceedings.mlr.press/v235/smit24a.html)). Benchmarks debate protocols against
  prompting strategies on cost, time and accuracy. Debate "does not reliably outperform"
  self-consistency or ensembling over reasoning paths, but some protocols do better after
  hyperparameter tuning: debate is sensitive and hard to optimize.
- **Wang et al., *Rethinking the Bounds of LLM Reasoning: Are Multi-Agent Discussions the Key?*,
  ACL 2024** ([ACL Anthology](https://aclanthology.org/2024.acl-long.331/)). Re-evaluates the claim
  that multi-agent discussion improves reasoning, and finds a single agent with strong prompts largely
  matches it. *The exact conditions under which discussion still helps are from memory: check them
  in the paper.*
- **Zhang et al., *Stop Overvaluing Multi-Agent Debate — We Must Rethink Evaluation and Embrace Model
  Heterogeneity*, arXiv 2502.08788 (2025)** ([arXiv](https://arxiv.org/abs/2502.08788)). Five debate
  methods, nine benchmarks, four models: debate "often fail[s] to outperform simple single-agent
  baselines such as Chain-of-Thought and Self-Consistency, even when consuming significantly more
  inference-time computation". Argues for heterogeneous agents.
- **Choi et al., *Debate or Vote: Which Yields Better Decisions in Multi-Agent Large Language Models?*,
  NeurIPS 2025** ([proceedings](https://proceedings.neurips.cc/paper_files/paper/2025/file/934252acd87f254d5d4672fbde283bd2-Paper-Conference.pdf),
  [arXiv 2508.17536](https://arxiv.org/abs/2508.17536)). Across seven benchmarks, majority voting
  alone accounts for most of the gains attributed to debate. Theoretically, debate induces a
  *martingale* over agents' beliefs, so it does not by itself improve expected correctness.
- **Hu, Shen & Lakshmipathi, *Statistical Scouting Finds Debate-Safe but Not Debate-Useful Cases*,
  arXiv 2605.09618 (2026)** ([arXiv](https://arxiv.org/abs/2605.09618)). Equal budgets (960 tokens per
  example), Llama 3.1 8B and Ministral 8B on MuSiQue and GSM8K. Vote entropy predicts where debate is
  *safe*, not where it *helps*: 66% of debate's wins came where voting was unanimous but wrong.
- To find: further 2025–2026 matched-budget studies (search results mention a matched
  reasoning-token comparison on multi-hop QA, arXiv 2604.02460, not yet opened).

## Single-agent alternatives

- **Wang et al., *Self-Consistency Improves Chain of Thought Reasoning in Language Models*, ICLR 2023**
  (*from memory*). Majority vote over sampled chains of thought: our main baseline.
- **Madaan et al., *Self-Refine: Iterative Refinement with Self-Feedback*, NeurIPS 2023**
  ([proceedings](https://proceedings.neurips.cc/paper_files/paper/2023/hash/91edff07232fb1b55a505a9e9f6c0ff3-Abstract-Conference.html)).
  Generate, self-critique, refine. Our self-refine baseline (WS3a) follows this loop, with the
  dialogue's budget and turn structure.
- **Huang et al., *Large Language Models Cannot Self-Correct Reasoning Yet*, ICLR 2024**
  ([ICLR](https://iclr.cc/virtual/2024/poster/18956), [arXiv 2310.01798](https://arxiv.org/pdf/2310.01798)).
  Without external feedback, self-correction doesn't improve reasoning and can degrade it; earlier
  gains relied on oracle labels.

## Generated reasoning benchmarks

- **GSM-Symbolic** (Mirzadeh et al., ICLR 2025; [repo](https://github.com/apple/ml-gsm-symbolic)):
  templated GSM8K variants; P1 and P2 add clauses. Our planned external benchmark (WS6b).
- **GSM-Infinite** ([site](https://infini-ai-lab.github.io/gsm_infinite/),
  [arXiv 2502.05252](https://arxiv.org/abs/2502.05252)): computational-graph generation with
  controllable operations and distractors. Our generator follows this design.
- **BeyondBench** ([arXiv 2509.24210](https://arxiv.org/pdf/2509.24210)): algorithmic, contamination-free
  problem generation.

---

## Positioning (draft argument)

**The open question.** Since 2023, debate papers have reported gains, and compute-matched evaluations
have mostly not reproduced them: majority voting explains most of the gain (Choi et al.), and debate
rarely beats CoT or self-consistency at equal compute (Smit et al.; Zhang et al.). Choi et al. give a
theoretical reason: debate is a martingale over beliefs.

**Our evidence.** Under precisely stated conditions, a two-agent dialogue beat cost-matched
self-consistency by 10.2 points on 400 pre-registered held-out problems. The conditions:
- same model on both sides (`gpt-5.6-luna`), all reasoning visible (reasoning effort none)
- independent opening posts, an accuracy agent paired with a skeptic
- generated multi-step arithmetic in a 47–87% single-agent accuracy band
- matched on API cost including prompt caching

**How this squares with the critiques** (exploratory, from WS1, to be confirmed in WS4/WS5):
1. **Switches aren't a martingale here.** Answer changes moved toward the correct answer 81 times and
   away 4 times (test set). Belief updates were strongly biased toward truth. A plausible reason:
   every claim must show its arithmetic, and the problems have checkable structure, so a challenge
   can be verified rather than merely asserted.
2. **Independence matters, and it is exactly what voting already captures.** Dialogue's advantage
   over voting comes from what happens *after* disagreement: when the openings disagree with both
   wrong, the dialogue recovers 54%, and a one-shot judge recovers 24%.
3. **Opposite of Hu et al.** Debate never rescued a *shared* wrong answer (0 of 28 problems across
   four runs). Their debate wins came mostly from unanimous-but-wrong votes. Likely reasons: their
   smaller open models, a different task mix, and a different protocol. Worth stating as a contrast,
   not explaining away.

**Contributions to stress:**
- cost matching that includes prompt caching
- pre-registration on fresh generated data
- mechanism evidence on *when* dialogue helps (disagreement between independent attempts) and when it
  cannot (shared errors)
- an honest scope: one model family, one task family

The WS3 baselines (self-refine, reasoning-on, judge at equal budget, self-consistency at exact cost)
are designed to meet the strongest form of each critique.
