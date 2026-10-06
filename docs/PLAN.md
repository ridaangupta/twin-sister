# Plan: minimal dialogue loop + baselines (build steps 1–4)

Goal: the smallest system that can run a two-agent dialogue and the three
baselines on a GSM8K dev subset, with every API call traced, so we can inspect
traces by hand before scaling (build step 4). Everything here sits behind the
interfaces that later phases plug into, so the orchestrator does not change.

In scope: `llm.py`, `memory.py`, `protocol.py`, `agents.py`, `controller/base.py`
+ `heuristic.py`, `orchestrator.py`, `trace.py`, `synthesis.py` (`single_writer`
only), GSM8K loader, extraction, baselines, the runner, and tests.

Out of scope for now: `joint` and `synthesizer` synthesis, learned controller,
RL env, finance tasks, objective sweep, plots.

---

## 1. Module plan

Two modules are added to the layout in CLAUDE.md: `dialogic/protocol.py`
(parses agent output) and `dialogic/trace.py` (run dir + JSONL writers).
The runner is `dialogic/run.py`.

### `dialogic/llm.py`

```python
@dataclass(frozen=True)
class CallContext:            # who/where, passed explicitly on every call
    problem_id: str
    method: str               # dialogue | direct | cot | self_consistency
    turn: int | None
    agent: str                # "A" | "B" | "writer" | "baseline"
    space: str                # "core" | "scratchpad" | "synthesis" | "baseline"
    sample_idx: int = 0       # distinguishes self-consistency samples in the cache

@dataclass
class Completion:
    text: str
    prompt_tokens: int
    completion_tokens: int    # includes reasoning tokens if the model reports them
    reasoning_tokens: int
    latency_s: float
    cached: bool

class LLM:
    def __init__(self, cfg, tracer, cache_path): ...
    async def complete(self, ctx: CallContext, messages, *, max_tokens, temperature) -> Completion
    usage: UsageTracker       # per agent label, per space
```

- Clients: one `AsyncOpenAI` per agent key. `A` uses `OPENAI_API_KEY_A`, `B` uses
  `OPENAI_API_KEY_B`, and if those aren't set both use `OPENAI_API_KEY`. The
  baselines, writer and synthesizer use `OPENAI_API_KEY_A` or `OPENAI_API_KEY`.
- Cache: SQLite at `runs/.cache.sqlite`, key = sha256 of
  `(model, messages, max_tokens, temperature, seed, sample_idx)`. A cache hit
  is still traced, with `cached=true`, and still counts toward token accounting:
  a hit costs no money but still counts toward the budget.
- Retries: exponential backoff on 429/5xx/timeouts (tenacity), max 6 attempts.
- Concurrency: one `asyncio.Semaphore(cfg.concurrency)` shared by all calls.
- Pass `seed` from config to the API. Record `system_fingerprint` in the trace.
- Every call writes one row through `tracer.call(...)` (schema in §3).

### `dialogic/memory.py`

```python
@dataclass(frozen=True)
class Post:          turn, agent, text, answer, stance, consensus, ledger_ops, tokens
@dataclass
class LedgerEntry:   id, text, proposed_by, confirmed_by: set[str], turn_added, status  # pending|agreed|disputed

class Ledger:        apply(ops, agent, turn) -> LedgerDelta; agreed(); pending()
class CoreMemory:    task, thread: list[Post], ledger: Ledger
class Scratchpad:    owner, notes: list[str]

@dataclass(frozen=True)
class AgentView:     task, thread, ledger_snapshot, own_scratchpad: tuple[str, ...]
@dataclass(frozen=True)
class CoreView:      task, thread, ledger_snapshot          # no scratchpad field at all

class Memory:
    def __init__(self, task, agent_ids)
    def view_for(self, agent_id) -> AgentView     # core + that agent's pad only
    def core_view(self) -> CoreView                # for synthesis/extraction
    def write_scratch(self, agent_id, note)        # can only write to own pad
    def post(self, post: Post) -> LedgerDelta
```

How visibility is enforced: scratchpads are private (`_pads`). An agent never
gets `Memory`. It only gets an `AgentView`, and that view is built from
exactly one pad. `CoreView` has no scratchpad field, so a synthesizer can't
read a pad even by mistake.

Ledger rules (v1):
- `FACT+: <text>` proposes a fact. It starts as `pending`.
- `FACT_OK: F3` from the *other* agent moves it to `agreed`. Confirming your
  own fact does nothing.
- `FACT_DISPUTE: F3` from either agent moves it back to `disputed`. It needs
  a fresh `FACT_OK` to return to `agreed`.
- The prompt shows agreed facts under "Agreed facts" and pending or disputed
  facts under "Open claims".

### `dialogic/protocol.py`

Every core post ends with a trailer, and the parser reads the trailer only:

```
ANSWER: <number | none>
STANCE: agree | disagree | unsure        # toward the other agent's last post
CONSENSUS: yes | no                      # "I accept the current shared answer as final"
FACT+: <one-line fact>                   # 0..n
FACT_OK: F<id>                           # 0..n
FACT_DISPUTE: F<id>                      # 0..n
```

`parse_post(text) -> ParsedPost`. Malformed trailers are handled
leniently: a missing field becomes `None`/`unsure`/`no`, and the post is
flagged with `protocol_error=true` in the trace. The trailer is how we get
disagreement, consensus and ledger signals with no extra LLM calls.

### `dialogic/agents.py`

```python
class Agent:
    def __init__(self, agent_id, objective_name, llm, prompts)
    async def think(self, view: AgentView, budget: int, ctx) -> Completion    # scratchpad
    async def speak(self, view: AgentView, soft_limit: int, hard_cap: int, ctx) -> Post
```

- The prompt is `prompts/base_agent.txt` with these slots filled: `{objective}`
  (the text of `prompts/objectives/<name>.txt`), `{task}`, `{agreed_facts}`,
  `{open_claims}`, `{thread}`, `{scratchpad}`, `{target_tokens}`, `{agent_id}`,
  `{other_id}`.
- `think` uses `prompts/scratchpad.txt` and `max_tokens=budget`. The output
  is appended to the agent's own pad. Budget 0 skips the call.
- `speak` uses `max_tokens=hard_cap` (= `soft_limit * k`). The prompt says
  "aim for about {target_tokens} tokens". If the reply is truncated at the
  cap, the trailer may be lost, so the post is logged with
  `truncated=true` and `protocol_error=true`.
- Agents differ only in `{objective}`. The test in §5 checks that the two
  rendered prompts differ only inside the objective block.

### `dialogic/controller/base.py` + `heuristic.py`

```python
@dataclass(frozen=True)
class ControllerState:
    turn: int; max_turns: int
    core_tokens: int; scratch_tokens: int; last_post_tokens: int
    answers: dict[str, str | None]      # latest ANSWER per agent
    stances: list[str]                  # per post, in order
    consensus: dict[str, bool]          # latest CONSENSUS per agent
    answer_changes: dict[str, int]
    ledger_agreed: int; ledger_delta: int; ledger_disputes: int

@dataclass(frozen=True)
class TurnDecision:
    soft_limit: int; scratch_budget: int; stop: bool; stop_prob: float; reason: str

class TurnController(ABC):
    @abstractmethod
    def decide(self, state: ControllerState) -> TurnDecision
```

`HeuristicController(cfg, rng)` works like this:
- It stops when `turn >= max_turns`, or when both agents' latest posts have
  `CONSENSUS: yes` and the same normalized `ANSWER`. In that case
  `reason="consensus"`, otherwise `reason="max_turns"`.
- `soft_limit` is sampled from `soft_limit_choices` (seeded) if that is set,
  and is otherwise the fixed `soft_limit`. The sampling is on purpose: Phase
  1 traces need variation in turn length, or Phase 2 has no signal for the
  soft-limit head.
- `scratch_budget` is fixed from config.

The `ControllerState` fields are the Phase 2 feature set (see CLAUDE.md
decisions). Each turn's state and decision are logged.

### `dialogic/orchestrator.py`

```python
async def run_dialogue(problem, agents, controller, synthesizer, llm, tracer, cfg) -> ProblemResult:
    mem = Memory(problem.question, ["A", "B"])
    order = first_speaker(problem.id, cfg)          # seeded per problem; logged
    state = ControllerState.initial(cfg)
    for turn in itertools.count():
        d = controller.decide(state); tracer.decision(problem.id, turn, state, d)
        if d.stop: break
        agent = agents[order[turn % 2]]
        if d.scratch_budget:
            note = await agent.think(mem.view_for(agent.id), d.scratch_budget, ctx(..., space="scratchpad"))
            mem.write_scratch(agent.id, note.text)
        post = await agent.speak(mem.view_for(agent.id), d.soft_limit, int(d.soft_limit * cfg.k), ctx(..., space="core"))
        delta = mem.post(post)
        state = state.after(post, delta, scratch_tokens=...)
        tracer.turn(problem.id, post, delta)
    final = await synthesizer.final(mem.core_view(), ctx(..., space="synthesis"))
    return ProblemResult(...)
```

- A turn is one post by one agent. `max_turns` counts posts, so a full
  exchange is 2 turns.
- Problems run concurrently with `asyncio.gather`, bounded by the LLM
  semaphore. Turns within a problem run one after another.
- Who speaks first is seeded per problem (`hash(seed, problem_id) % 2`).
  This keeps first-mover effects out of the comparison between objectives.

### `dialogic/synthesis.py`

`Synthesizer.final(core: CoreView, ctx) -> FinalAnswer(text, answer, solution_steps)`.
Only `SingleWriter(agent_id)` is in v1. It reuses that agent's model and
objective, uses `prompts/final_writer.txt`, reads `CoreView` only, and must
output `SOLUTION:` (numbered steps) and then `ANSWER:`. Synthesis tokens are
logged under their own space. The strategy is picked from a config registry,
so `joint` and `synthesizer` slot in later.

### `dialogic/trace.py`

`Tracer(run_dir)` provides `call()`, `turn()`, `decision()`, `problem()` and
`prompt(hash, messages)`. Each one appends one JSON line and flushes. Writes
happen on the event-loop thread, so rows never interleave and a crash keeps
everything written so far.

### `evals/`

- `datasets.py`: `Problem(id, question, gold, meta)`, `Dataset` protocol, and
  `load(name, split, subset)`.
- `gsm8k.py` downloads the official `test.jsonl` from `openai/grade-school-math` into `data/gsm8k/`
  (gitignored) and verifies a pinned sha256. The gold answer is the text
  after `####`. `id = f"gsm8k-{split}-{index}"`.
- The dev subset is 200 test-split ids, sampled once with seed 0 and
  committed to `evals/subsets/gsm8k_dev200.json`. The 50-problem dev run uses
  the first 50 ids of that file. Subsets are files, not RNG calls, so they
  stay stable across library versions.
- `metrics.py`:
  - `extract_answer(text)`: take the last `ANSWER:` line if there is one,
    otherwise the last number in the text. Strip `$ , %` and whitespace.
  - `normalize(x)` turns `"1,000.00" → "1000"` and `"-3.50" → "-3.5"`.
  - `exact_match`.
  - Per-run aggregation: accuracy with bootstrap 95% CI, token breakdown,
    turns, cost, agreement trajectory, answer flips, ledger growth.
- `baselines.py` (all use the same model and the same `LLM`, with `agent="baseline"`):
  - `direct`: answer only, `max_tokens=32`.
  - `cot`: step by step with `max_tokens = B`, and the prompt states the
    budget. Real usage is reported, since models don't fill budgets.
  - `self_consistency`: `n = max(3, round(B / mean_cot_tokens))` samples at
    `temperature=0.7`, a majority vote on normalized answers, and ties broken
    by the first sample.
  - `B` is the matched budget (see §2).

### `dialogic/run.py`

```
python -m dialogic.run configs/gsm8k_dev50_dialogue.yaml
python -m dialogic.run configs/gsm8k_dev50_baselines.yaml --match runs/<dialogue_run_id>
```

Steps the runner takes:
1. Load and validate the config.
2. Create `runs/<UTC timestamp>_<config name>/` and write the run files.
3. Build the dataset, LLM, tracer and method.
4. Run all problems.
5. Write `results.csv` and `summary.json`.

It refuses to start if the dataset is the full test split and
`final_run: true` is not set.

---

## 2. Matched-token budget

- **What is matched:** generated tokens, meaning completion tokens
  (including reasoning tokens) summed over core, scratchpad and synthesis.
  This is the "reasoning effort" being compared.
- **Reported, not matched:** prompt tokens and cost. Dialogue re-reads core
  every turn, so its input tokens grow roughly quadratically. All methods
  report this so the cost picture stays honest.
- **Level:** `B` = the mean generated tokens per problem of the referenced
  dialogue run (`--match`), matched over the whole subset. Matching per
  problem would hand the baseline an oracle difficulty signal.
  Per-problem budgets are kept as an optional ablation.

---

## 3. Run directory and trace schema

```
runs/<run_id>/
  config.yaml          # verbatim copy
  meta.json            # run_id, git_hash, git_dirty, model, started_at, seed, python/openai versions
  calls.jsonl          # one row per API call
  prompts.jsonl        # {prompt_hash, messages} deduped
  turns.jsonl          # one row per post (dialogue only)
  decisions.jsonl      # controller state + decision per turn
  problems.jsonl       # one row per problem: final, gold, correct, tokens by space, turns, stop_reason, ...
  results.csv          # flat per-problem table for analysis
  summary.json         # aggregate metrics
```

`calls.jsonl` row:

```json
{"run_id":"…","problem_id":"gsm8k-test-17","method":"dialogue","turn":3,"agent":"B",
 "space":"core","sample_idx":0,"model":"…","prompt_hash":"sha256:…","max_tokens":600,
 "temperature":0.0,"response":"…","prompt_tokens":812,"completion_tokens":291,
 "reasoning_tokens":0,"latency_s":2.41,"cached":false,"finish_reason":"stop",
 "system_fingerprint":"…","ts":"…"}
```

`turns.jsonl` row: problem_id, turn, agent, objective, answer, stance,
consensus, ledger_ops, ledger_delta, soft_limit, hard_cap, tokens, truncated,
protocol_error.

---

## 4. Config (example)

```yaml
name: gsm8k_dev50_dialogue
method: dialogue                 # dialogue | direct | cot | self_consistency
seed: 0
model: ${MODEL}                  # required; the runner errors if unset
temperature: 0.0
concurrency: 16
dataset: {name: gsm8k, split: test, subset: evals/subsets/gsm8k_dev200.json, limit: 50}
agents:
  A: {objective: accuracy}
  B: {objective: simplicity}
first_speaker: seeded            # seeded | A | B
controller:
  type: heuristic
  max_turns: 8
  soft_limit: 300
  soft_limit_choices: [150, 300, 600]   # optional; overrides soft_limit
  scratch_budget: 200
  k: 2.0
synthesis: {type: single_writer, writer: A}
```

---

## 5. Tests (`tests/`, pytest + pytest-asyncio, no network)

| Test | Checks |
|---|---|
| `test_extraction.py` | `####` gold parsing, `ANSWER:` precedence, commas/`$`/`%`, negatives, decimals, no-number → `None`. |
| `test_visibility.py` | `view_for("B")` never contains A's notes (checked on both content and type). The reverse holds too. `CoreView` has no scratchpad. An agent can't write to the other agent's pad. A canary string written to A's pad never appears in any prompt B or the writer sends (run end-to-end with `FakeLLM`). |
| `test_protocol.py` | Trailer parsing, lenient defaults, `protocol_error` flag. |
| `test_ledger.py` | Confirming your own fact does nothing. Confirming the other agent's fact moves it to `agreed`. Disputes move it back. |
| `test_controller.py` | `HeuristicController` satisfies `TurnController`. It stops at max_turns. It stops on mutual consensus with matching answers, but not with mismatched answers or one-sided consensus. Seeded `soft_limit` sampling is reproducible. |
| `test_orchestrator.py` | With a scripted `FakeLLM`, it checks: turn order, scratchpad calls skipped when budget is 0, the hard cap passed to the LLM, the trace files written, and the token split by space. |
| `test_cache.py` | The same key returns the cached response with `cached=true`. Different `sample_idx` values give different keys. |

`FakeLLM` implements the same `complete()` signature and replies from a
script keyed by `(agent, space, turn)`.

---

## 6. Order of work

1. `llm.py` + `trace.py` + cache tests. Smoke-test with one live call.
2. `memory.py`, `protocol.py` + visibility, ledger and protocol tests.
3. `controller/base.py`, `heuristic.py` + controller tests.
4. Prompts: `base_agent.txt`, `scratchpad.txt`, `final_writer.txt`,
   `objectives/accuracy.txt`, `objectives/simplicity.txt`.
5. `agents.py`, `orchestrator.py`, `synthesis.py` (single_writer) + orchestrator test.
6. `evals/` loader, dev subset file, metrics, baselines + extraction tests.
7. `run.py`. Run the dialogue on 50 dev problems first, then the baselines
   with `--match`.
8. Read 10–15 traces by hand, both correct and incorrect. Check protocol
   compliance, ledger use and truncation rate. Adjust the prompts before
   scaling.

Dependencies: `openai`, `pyyaml`, `tenacity`, `python-dotenv`, and for
dev, `pytest` and `pytest-asyncio`. These go in `pyproject.toml`.
