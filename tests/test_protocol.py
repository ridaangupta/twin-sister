import pytest

from dialogic.protocol import LedgerOp, normalize_answer, normalize_fact_id, parse_post

FULL = """Each box holds 12 eggs, so 3 boxes hold 36.

ANSWER: 36
STANCE: agree
CONSENSUS: yes
FACT+: one box holds 12 eggs
FACT+: there are 3 boxes
FACT_OK: F1
FACT_DISPUTE: F2
"""


def test_full_trailer():
    p = parse_post(FULL)
    assert p.answer == "36"
    assert p.stance == "agree"
    assert p.consensus is True
    assert p.ledger_ops == (
        LedgerOp("add", text="one box holds 12 eggs"),
        LedgerOp("add", text="there are 3 boxes"),
        LedgerOp("confirm", fact_id="F1"),
        LedgerOp("dispute", fact_id="F2"),
    )
    assert not p.protocol_error
    assert p.body == "Each box holds 12 eggs, so 3 boxes hold 36."


def test_markdown_and_case_tolerant():
    p = parse_post("work\n**ANSWER:** $1,250.00\n- stance: Disagree\n`CONSENSUS`: NO\nfact_ok: [F3]")
    assert (p.answer, p.stance, p.consensus) == ("1250", "disagree", False)
    assert p.ledger_ops == (LedgerOp("confirm", fact_id="F3"),)
    assert not p.protocol_error


def test_missing_fields_get_defaults_and_flag():
    p = parse_post("I think it's 7 but I'm not sure.")
    assert (p.answer, p.stance, p.consensus) == (None, "unsure", False)
    assert set(p.errors) == {"missing ANSWER", "missing STANCE", "missing CONSENSUS"}
    assert p.protocol_error


def test_invalid_values_flag():
    p = parse_post("ANSWER: about seven\nSTANCE: maybe\nCONSENSUS: probably\nFACT_OK: banana")
    assert (p.answer, p.stance, p.consensus) == (None, "unsure", False)
    assert len(p.errors) == 4 and p.ledger_ops == ()


def test_answer_none_is_not_an_error():
    p = parse_post("ANSWER: none\nSTANCE: unsure\nCONSENSUS: no")
    assert p.answer is None and not p.protocol_error


def test_last_single_valued_field_wins():
    p = parse_post("ANSWER: 5\nSTANCE: disagree\nCONSENSUS: no\n...\nANSWER: 6\nSTANCE: agree\nCONSENSUS: yes")
    assert (p.answer, p.stance, p.consensus) == ("6", "agree", True)


def test_mid_line_mentions_are_not_fields():
    p = parse_post("My ANSWER: is below.\nANSWER: 4\nSTANCE: agree\nCONSENSUS: no")
    assert p.answer == "4"


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("36", "36"),
        ("1,000", "1000"),
        ("$1,000.00", "1000"),
        ("-3.50", "-3.5"),
        ("0.250", "0.25"),
        (".5", "0.5"),
        ("18 dollars", "18"),
        ("x = 3 so 9", "9"),
        ("12.0%", "12"),
        ("none", None),
        ("", None),
        (None, None),
    ],
)
def test_normalize_answer(raw, expected):
    assert normalize_answer(raw) == expected


@pytest.mark.parametrize("raw,expected", [("F3", "F3"), ("f12", "F12"), ("3", "F3"), ("[F07]", "F7"), ("Fx", None)])
def test_normalize_fact_id(raw, expected):
    assert normalize_fact_id(raw) == expected
