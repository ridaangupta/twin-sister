import sys
from pathlib import Path

import pytest

from evals.mixture import Mixture, solve_p_high, unit_hash

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import power  # noqa: E402

IDS = [f"p{i}" for i in range(4000)]


def test_unit_hash_is_deterministic_uniform_and_salted():
    xs = [unit_hash("s", i) for i in IDS]
    assert xs == [unit_hash("s", i) for i in IDS]
    assert all(0 <= x < 1 for x in xs) and abs(sum(xs) / len(xs) - 0.5) < 0.02
    assert xs != [unit_hash("t", i) for i in IDS]


def test_mixture_share_and_stability():
    m = Mixture(7, 8, 0.3, "sc")
    picks = [m.pick(i) for i in IDS]
    assert set(picks) == {7, 8} and abs(picks.count(8) / len(IDS) - 0.3) < 0.03
    assert picks == [Mixture(7, 8, 0.3, "sc").pick(i) for i in IDS]
    # raising p_high only moves problems from low to high (monotone)
    more = Mixture(7, 8, 0.5, "sc")
    assert all(more.pick(i) == 8 for i in IDS if m.pick(i) == 8)


def test_mixture_from_config_and_validation():
    assert Mixture.from_config(5, "x").pick("p1") == 5
    m = Mixture.from_config({"low": "low", "high": "medium", "p_high": 1.0}, "x")
    assert m.pick("p1") == "medium"
    with pytest.raises(ValueError):
        Mixture(1, 2, 1.5, "x")


def test_solve_p_high():
    assert solve_p_high(1.0, 2.0, 1.25) == pytest.approx(0.25)
    assert solve_p_high(1.0, 2.0, 3.0) == 1.0 and solve_p_high(1.0, 2.0, 0.5) == 0.0
    assert solve_p_high(1.0, 1.0, 1.0) == 0.0


def test_power_matches_planning_numbers():
    # docs/PLAN_v2.md table: discordance 0.16, Holm family of 4, 80% power
    assert power.n_superiority((0.16 + 0.05) / 2, (0.16 - 0.05) / 2, 0.05 / 4, 0.8) == 711
    assert power.n_superiority((0.16 + 0.04) / 2, (0.16 - 0.04) / 2, 0.05 / 4, 0.8) == 1113
    # TOST with true difference 0 needs z at 1 - beta/2: 90% power -> 1023 (not 809, an early planning slip)
    assert power.n_tost(0.085, 0.03, power=0.9) == 1023
    assert power.n_tost(0.085, 0.03, power=0.8) == 809
    with pytest.raises(ValueError):
        power.n_superiority(0.05, 0.05)
