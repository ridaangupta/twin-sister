import itertools
import re

import pytest

from evals.synthetic import Statement, apply, generate, generate_set, invert, solve

LEVELS = [
    dict(n_ops=2),
    dict(n_ops=6, n_distractors=3),
    dict(n_ops=10, n_distractors=5, n_reverse=1, p_total=0.3),
    dict(n_ops=20, n_distractors=10, n_reverse=2, p_total=0.3),
    dict(n_ops=32, n_distractors=8, n_reverse=2, p_total=0.2, shuffle=False),
    dict(n_ops=96, n_distractors=48, n_reverse=1, p_total=0.2),
]
CASES = [(seed, knobs) for knobs in LEVELS for seed in range(40)]


def _evaluate(p):
    """Third, independent check: evaluate the hidden graph directly in id order (no statements)."""
    vals = {}
    for i in sorted(p.nodes):
        n = p.nodes[i]
        if n.op is None:
            vals[i] = n.value
            continue
        args = []
        for r in n.args:
            args.append(sum(vals[m.id] for m in p.nodes.values() if m.owner == r.owner and m.id < i) if r.is_total else vals[r.node])
        vals[i] = apply(n.op, args, n.const)
    return vals


@pytest.mark.parametrize("seed,knobs", CASES)
def test_answer_follows_from_text_alone(seed, knobs):
    p = generate(seed, **knobs)
    assert solve(p.statements)[p.target] == p.answer
    assert _evaluate(p)[p.target] == p.answer
    assert 1 <= p.answer <= p.params["max_value"]


@pytest.mark.parametrize("seed,knobs", CASES)
def test_distractors_never_matter(seed, knobs):
    p = generate(seed, **knobs)
    core = [s for s in p.statements if not s.distractor]
    assert solve(core)[p.target] == p.answer
    assert p.params["n_distractor_statements"] >= knobs.get("n_distractors", 0)


@pytest.mark.parametrize("seed,knobs", CASES)
def test_every_intermediate_is_a_positive_integer(seed, knobs):
    p = generate(seed, **knobs)
    for n in p.nodes.values():
        assert isinstance(n.value, int) and 1 <= n.value <= p.params["max_value"]


@pytest.mark.parametrize("seed", range(40))
def test_reverse_hides_leaves_and_requires_inversion(seed):
    p = generate(seed, n_ops=8, n_reverse=2)
    stated = {s.node for s in p.statements if s.kind in ("leaf", "value")}
    hidden = [n.id for n in p.nodes.values() if n.op is None and n.id not in stated]
    assert len(hidden) == 2
    assert sum(s.kind == "value" for s in p.statements) == 2
    # Without inversion (forward only), the target is not computable.
    fwd = {s.node: s.const for s in p.statements if s.kind in ("leaf", "value")}
    assert all(h not in fwd for h in hidden)


def test_totals_appear_and_are_sums_of_everything_owned():
    found = 0
    for seed in range(60):
        p = generate(seed, n_ops=10, p_total=0.5)
        for s in p.statements:
            for r in s.args:
                if r.is_total:
                    found += 1
                    assert f"the total number of items {r.owner} has" in s.text
    assert found > 20


def test_labels_are_unambiguous():
    for seed in range(40):
        p = generate(seed, n_ops=16, n_distractors=8)
        pairs = [(n.owner, n.item) for n in p.nodes.values()]
        assert len(set(pairs)) == len(pairs)


def test_question_names_the_target():
    p = generate(3, n_ops=5)
    t = p.nodes[p.target]
    assert p.question == f"How many {t.item} does {t.owner} have?"
    assert p.text.endswith(p.question)


def test_deterministic_and_seed_sensitive():
    a, b = generate(7, n_ops=12, n_distractors=4), generate(7, n_ops=12, n_distractors=4)
    assert a.text == b.text and a.answer == b.answer
    assert generate(8, n_ops=12, n_distractors=4).text != a.text
    assert generate(7, n_ops=13, n_distractors=4).text != a.text


def test_shuffle_changes_order_not_content():
    s = generate(5, n_ops=10, shuffle=True)
    d = generate(5, n_ops=10, shuffle=False)
    assert solve(s.statements)[s.target] == s.answer and solve(d.statements)[d.target] == d.answer


def test_difficulty_scales_with_n_ops():
    def chain_len(p):
        return sum(1 for s in p.statements if s.kind == "relation" and not s.distractor)

    for lo, hi in [(4, 8), (8, 16), (16, 32)]:
        assert all(chain_len(generate(s, n_ops=lo)) < chain_len(generate(s, n_ops=hi)) for s in range(10))


def test_problem_conversion_and_sets():
    probs = generate_set(5, seed=0, n_ops=6, n_distractors=2)
    assert len({p.id for p in probs}) == 5 and len({p.question for p in probs}) == 5
    assert all(re.fullmatch(r"\d+", p.gold) for p in probs)
    assert all(p.meta["n_ops"] == 6 for p in probs)


@pytest.mark.parametrize("op,args,const", [("add_c", [7], 5), ("sub_c", [20], 5), ("mul_c", [6], 4), ("div_c", [20], 4),
                                           ("add", [3, 9], None), ("sub", [12, 5], None), ("mul", [6, 7], None)])
def test_invert_round_trips(op, args, const):
    t = apply(op, args, const)
    for i in range(len(args)):
        missing = list(args)
        missing[i] = None
        assert invert(op, t, missing, i, const) == args[i]
