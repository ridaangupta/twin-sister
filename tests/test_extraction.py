import pytest

from evals.gsm8k import parse_gold
from evals.metrics import exact_match, extract_answer


@pytest.mark.parametrize(
    "solution,gold",
    [
        ("16 - 3 - 4 = 9\n9 * 2 = $18\n#### 18", "18"),
        ("...\n#### 1,000", "1000"),
        ("...\n#### -3", "-3"),
        ("...\n#### 0.5", "0.5"),
        ("a #### b\n#### 7", "7"),  # last marker wins
    ],
)
def test_parse_gold(solution, gold):
    assert parse_gold(solution) == gold


def test_parse_gold_rejects_missing_marker():
    with pytest.raises(ValueError):
        parse_gold("the answer is 18")


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Step 1: 16-3-4=9. Step 2: 9*2=18.\nANSWER: 18", "18"),
        ("ANSWER: 17\nwait, recheck\nANSWER: 18", "18"),  # last ANSWER line wins
        ("ANSWER: $1,234.50", "1234.5"),
        ("**Answer:** 42", "42"),
        ("She makes 9 * 2 = 18 dollars.", "18"),  # no ANSWER line: last number
        ("ANSWER: 12 (from 3 boxes of 4)", "12"),  # first number on the ANSWER line
        ("I cannot solve this.", None),
        ("", None),
        ("ANSWER: -7", "-7"),
        ("ANSWER: 50%", "50"),
    ],
)
def test_extract_answer(text, expected):
    assert extract_answer(text) == expected


@pytest.mark.parametrize(
    "pred,gold,ok",
    [("18", "18", True), ("18.00", "18", True), ("1,000", "1000", True), ("17", "18", False), (None, "18", False), ("x", "18", False)],
)
def test_exact_match(pred, gold, ok):
    assert exact_match(pred, gold) is ok
