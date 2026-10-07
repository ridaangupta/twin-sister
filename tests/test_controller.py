import pytest

from dialogic.controller import ControllerState, HeuristicController, TurnController, TurnDecision, make_controller
from dialogic.memory import Ledger, LedgerDelta, Post

AGENTS = ("A", "B")


def post(turn, agent, answer="36", stance="agree", consensus="no", tokens=100, extra=""):
    return Post.from_text(turn, agent, f"x\nANSWER: {answer}\nSTANCE: {stance}\nCONSENSUS: {consensus}\n{extra}", completion_tokens=tokens)


def run(posts, max_turns=8, scratch=0):
    """Feed posts through a ledger + state the way the orchestrator will."""
    led = Ledger()
    s = ControllerState.initial("p1", AGENTS, max_turns)
    for p in posts:
        d = led.apply(p.ledger_ops, p.agent, p.turn)
        s = s.after(p, d, ledger_agreed=len(led.agreed()), scratch_tokens=scratch)
    return s


# ---------------------------------------------------------------- interface


def test_heuristic_satisfies_interface():
    c = make_controller({"type": "heuristic", "max_turns": 4})
    assert isinstance(c, TurnController) and isinstance(c, HeuristicController)
    d = c.decide(ControllerState.initial("p1", AGENTS, 4))
    assert isinstance(d, TurnDecision)
    assert (d.stop, d.reason, d.stop_prob) == (False, "continue", 0.0)


def test_interface_cannot_be_instantiated_without_decide():
    with pytest.raises(TypeError):
        TurnController()  # type: ignore[abstract]

    class Incomplete(TurnController):
        pass

    with pytest.raises(TypeError):
        Incomplete()  # type: ignore[abstract]


def test_unknown_controller_type():
    with pytest.raises(ValueError):
        make_controller({"type": "learned", "max_turns": 4})


def test_max_turns_must_be_positive():
    with pytest.raises(ValueError):
        HeuristicController(max_turns=0)


# ---------------------------------------------------------------- stopping


def test_stops_at_max_turns():
    c = HeuristicController(max_turns=3)
    s = run([post(0, "A", consensus="no"), post(1, "B", answer="40", consensus="no"), post(2, "A", consensus="no")], max_turns=3)
    d = c.decide(s)
    assert (d.stop, d.reason, d.stop_prob) == (True, "max_turns", 1.0)


def test_stops_on_mutual_consensus_with_matching_answers():
    s = run([post(0, "A", consensus="yes"), post(1, "B", consensus="yes")])
    assert s.mutual_consensus
    assert HeuristicController(max_turns=8).decide(s).reason == "consensus"


@pytest.mark.parametrize(
    "posts",
    [
        [post(0, "A", consensus="yes")],  # only one agent has spoken
        [post(0, "A", consensus="yes"), post(1, "B", consensus="no")],  # one-sided
        [post(0, "A", consensus="yes"), post(1, "B", answer="40", consensus="yes")],  # answers differ
        [post(0, "A", consensus="yes"), post(1, "B", consensus="yes"), post(2, "A", consensus="no")],  # A withdrew
    ],
)
def test_no_stop_without_true_consensus(posts):
    s = run(posts)
    assert not s.mutual_consensus
    assert not HeuristicController(max_turns=8).decide(s).stop


# ---------------------------------------------------------------- budgets


def test_fixed_budgets():
    d = HeuristicController(max_turns=4, soft_limit=250, scratch_budget=120).decide(ControllerState.initial("p", AGENTS, 4))
    assert (d.soft_limit, d.scratch_budget) == (250, 120)


def test_soft_limit_sampling_is_seeded_and_order_independent():
    choices = [150, 300, 600]
    c1 = HeuristicController(max_turns=8, soft_limit_choices=choices, seed=0)
    c2 = HeuristicController(max_turns=8, soft_limit_choices=choices, seed=0)
    states = [ControllerState.initial(f"p{i}", AGENTS, 8) for i in range(40)]

    forward = [c1.decide(s).soft_limit for s in states]
    backward = [c2.decide(s).soft_limit for s in reversed(states)][::-1]
    assert forward == backward
    assert set(forward) <= set(choices) and len(set(forward)) > 1

    c3 = HeuristicController(max_turns=8, soft_limit_choices=choices, seed=1)
    assert [c3.decide(s).soft_limit for s in states] != forward


# ---------------------------------------------------------------- state & features


def test_state_accumulates_tokens_and_ledger():
    s = run(
        [
            post(0, "A", tokens=120, extra="FACT+: 12 per box"),
            post(1, "B", tokens=80, extra="FACT_OK: F1\nFACT+: 3 boxes"),
            post(2, "A", tokens=50, extra="FACT_DISPUTE: F1"),
        ],
        scratch=30,
    )
    assert (s.turn, s.core_tokens, s.scratch_tokens, s.last_post_tokens) == (3, 250, 90, 50)
    assert (s.ledger_agreed, s.ledger_delta, s.ledger_disputes) == (0, 1, 1)


def test_answer_changes_ignore_none_gaps():
    s = run(
        [
            post(0, "A", answer="none"),  # None -> x is not a change
            post(1, "B", answer="40"),
            post(2, "A", answer="36"),
            post(3, "B", answer="none"),  # x -> None is not a change
            post(4, "A", answer="36"),
            post(5, "B", answer="36"),  # 40 -> (none) -> 36 counts once
        ]
    )
    assert dict(s.answer_changes) == {"A": 0, "B": 1}
    assert s.last_change_turn == 5
    assert s.features()["turns_since_answer_change"] == 0


def test_features_are_stable_numeric_vector():
    s0 = ControllerState.initial("p", AGENTS, 8)
    s = run([post(0, "A", stance="disagree"), post(1, "B", stance="disagree", consensus="yes")])
    f0, f = s0.features(), s.features()
    assert list(f0) == list(f)  # same keys, same order before and after posts
    assert all(isinstance(v, (int, float)) for v in f.values())
    assert f["turn"] == 2 and f["turn_frac"] == 0.25
    assert f["disagree_recent"] == 2 and f["last_stance_disagree"] == 1.0
    assert f["answers_agree"] == 1.0 and f["consensus_B"] == 1.0 and f["consensus_A"] == 0.0


def test_state_is_immutable():
    s = ControllerState.initial("p", AGENTS, 8)
    s2 = s.after(post(0, "A"), LedgerDelta(), ledger_agreed=0)
    assert s.turn == 0 and s.answers["A"] is None and s2.answers["A"] == "36"
    with pytest.raises(TypeError):
        s2.answers["A"] = "1"  # type: ignore[index]


def test_stops_when_both_agree_there_is_no_answer():
    s = run([post(0, "A", answer="none", consensus="yes"), post(1, "B", answer="none", consensus="yes")])
    assert not s.mutual_consensus and s.consensus_without_answer
    assert HeuristicController(max_turns=8).decide(s).reason == "consensus_no_answer"
    one_sided = run([post(0, "A", answer="none", consensus="yes"), post(1, "B", answer="none", consensus="no")])
    assert not HeuristicController(max_turns=8).decide(one_sided).stop
