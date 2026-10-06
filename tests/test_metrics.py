from evals.metrics import bootstrap_ci, cost_usd, mind_changes, summarize


def test_mind_changes_attributes_adoption():
    traj = [
        {"A": "36", "B": None},
        {"A": "36", "B": "40"},
        {"A": "40", "B": "40"},  # A adopts B's answer
        {"A": "40", "B": "42"},  # B moves to a new answer on its own
        {"A": "42", "B": "42"},  # A adopts B's again
    ]
    assert mind_changes(traj) == {"A<-B": 2, "B<-self": 1}


def test_mind_changes_ignores_none_gaps():
    traj = [{"A": "1", "B": "2"}, {"A": None, "B": "2"}, {"A": "1", "B": "2"}]
    assert mind_changes(traj) == {}


def test_bootstrap_ci_brackets_mean():
    lo, hi = bootstrap_ci([1.0] * 30 + [0.0] * 20)
    assert lo < 0.6 < hi and 0 <= lo and hi <= 1
    assert bootstrap_ci([1.0, 1.0]) == (1.0, 1.0)


def test_cost():
    assert cost_usd(1_000_000, 500_000, {"input_per_mtok": 1.0, "output_per_mtok": 4.0}) == 3.0
    assert cost_usd(10, 10, None) is None


def test_summarize_dialogue_and_baseline_rows():
    dlg = [
        {"method": "dialogue", "correct": True, "final_answer": "1", "tokens": {"generated": 100, "core": 80}, "turns": 2,
         "stop_reason": "consensus", "agreement_trajectory": [False, True], "answer_trajectory": [{"A": "1", "B": None}, {"A": "1", "B": "1"}],
         "ledger_agreed": 1, "ledger_total": 2, "ledger_disputes": 0, "protocol_errors": 0, "solution_steps": 2},
        {"method": "dialogue", "correct": False, "final_answer": None, "tokens": {"generated": 300, "core": 200}, "turns": 8,
         "stop_reason": "max_turns", "agreement_trajectory": [False], "answer_trajectory": [{"A": "1", "B": "2"}, {"A": "2", "B": "2"}],
         "ledger_agreed": 0, "ledger_total": 1, "ledger_disputes": 1, "protocol_errors": 1, "solution_steps": 4},
    ]
    s = summarize(dlg)
    assert s["n"] == 2 and s["accuracy"] == 0.5 and s["no_answer_rate"] == 0.5
    assert s["tokens_mean"] == {"core": 140, "generated": 200}
    assert s["stop_reasons"] == {"consensus": 1, "max_turns": 1} and s["consensus_rate"] == 0.5
    assert s["final_agreement_rate"] == 0.5 and s["mind_changes"] == {"A<-B": 1}

    sc = summarize([{"method": "self_consistency", "correct": True, "final_answer": "3", "tokens": {"generated": 50}, "n_samples": 5}])
    assert s.get("samples_mean") is None and sc["samples_mean"] == 5 and "turns_mean" not in sc
