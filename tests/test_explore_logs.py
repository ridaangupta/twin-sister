"""Claim extraction edge cases found while validating scripts/explore_logs.py on real posts."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import explore_logs as E  # noqa: E402

from evals.synthetic import Node, Synthetic  # noqa: E402


def problem():
    nodes = {
        0: Node(0, "Hugo", "cups", None, value=8),
        1: Node(1, "Ruby", "hats", None, value=271),
        2: Node(2, "Tariq", "plums", "sub", value=263),
        3: Node(3, "Amara", "socks", "sub_c", value=72),
        4: Node(4, "Nadia", "rocks", "mul_c", value=432),
    }
    return Synthetic([], "q", nodes, 2, 263)


def claims(text):
    return {(c.key[1], c.value) for c in E.extract_claims(text, E.label_patterns(problem()))}


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Tariq's plums = Ruby's hats − Hugo's cups = 271 − 8 = 263.", {(2, 263)}),  # RHS labels are not claims
        (r"Let plums Tariq \(=271-8=263\), and cups Hugo \(=8\).", {(2, 263), (0, 8)}),  # LaTeX, two claims
        ("Socks Amara = 72 and Rocks Nadia = 432.", {(3, 72), (4, 432)}),  # chained claims split on 'and'
        ("which is 6 times Amara's socks = 432", set()),  # word operator before the label
        ("Tariq's plums = 271 + Sven's bowls requires Sven's bowls = 25", set()),  # words between '=' and the value
        ("Hugo has 8 cups.", {(0, 8)}),  # 'X has N items' form
        ("- Ruby's hats = 1,271.", {(1, 1271)}),  # bullet and thousands separator
        ("Tariq's plums is 4 more than", set()),  # a restated relation, not a value
    ],
)
def test_extract_claims(text, expected):
    assert claims(text) == expected


def test_total_claims():
    found = {(c.key, c.value) for c in E.extract_claims("so Hugo's total = 3+5 = 8.", E.label_patterns(problem()))}
    assert (("total", "Hugo"), 8.0) in found


def test_misread_alternatives_cover_inverse_and_direction():
    assert 160 / 4 in E.misread_alternatives("mul_c", [160], 4)  # x4 read as /4
    assert 32 in E.misread_alternatives("div_c", [16], 2)  # 'half of' read as x2
    assert 5 in E.misread_alternatives("add_c", [9], 4)  # 'more than' read as 'less than'
