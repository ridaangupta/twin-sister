"""Parse the structured trailer every core post ends with.

    ANSWER: <number | none>
    STANCE: agree | disagree | unsure
    CONSENSUS: yes | no
    FACT+: <one-line fact>          (0..n)
    FACT_OK: F<id>                  (0..n)
    FACT_DISPUTE: F<id>             (0..n)

Parsing is lenient: a missing or malformed field gets a neutral default and the
post is flagged `protocol_error`, so a sloppy turn never crashes a run.
For single-valued fields the last occurrence wins.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Literal

Stance = Literal["agree", "disagree", "unsure"]
OpKind = Literal["add", "confirm", "dispute"]

_FIELD = re.compile(
    r"^[ \t>*_`-]*(ANSWER|STANCE|CONSENSUS|FACT\+|FACT_OK|FACT_DISPUTE)[*_`]*[ \t]*:[*_`]*[ \t]*(.*?)[ \t*_`]*$",
    re.IGNORECASE | re.MULTILINE,
)
_NUMBER = re.compile(r"-?(?:\d[\d,]*(?:\.\d+)?|\.\d+)")
_FACT_ID = re.compile(r"^\[?F?(\d+)\]?$", re.IGNORECASE)
_EMPTY = {"", "none", "n/a", "-", "(none)", "(optional)"}
_ANSWER_LINE = re.compile(r"^[ \t>*_`-]*ANSWER[*_`]*[ \t]*:[*_`]*[ \t]*(.+)$", re.IGNORECASE | re.MULTILINE)


@dataclass(frozen=True)
class LedgerOp:
    kind: OpKind
    text: str | None = None  # for "add"
    fact_id: str | None = None  # for "confirm" / "dispute"


@dataclass(frozen=True)
class ParsedPost:
    body: str  # text with trailer lines removed
    answer: str | None
    stance: Stance
    consensus: bool
    ledger_ops: tuple[LedgerOp, ...]
    errors: tuple[str, ...]

    @property
    def protocol_error(self) -> bool:
        return bool(self.errors)


def normalize_answer(value: str | None, *, pick: Literal["first", "last"] = "last") -> str | None:
    """Canonical numeric form of the first/last number in the string: no commas, no trailing zeros."""
    if value is None:
        return None
    matches = _NUMBER.findall(value.replace("$", ""))
    if not matches:
        return None
    try:
        d = Decimal(matches[0 if pick == "first" else -1].replace(",", ""))
    except InvalidOperation:
        return None
    if d == d.to_integral_value():
        return str(d.quantize(Decimal(1)))
    return format(d.normalize(), "f")


def extract_answer(text: str) -> str | None:
    """Final answer from free text: first number on the last ANSWER line, else the last number in the text."""
    lines = _ANSWER_LINE.findall(text)
    return normalize_answer(lines[-1], pick="first") if lines else normalize_answer(text)


def normalize_fact_id(value: str) -> str | None:
    m = _FACT_ID.match(value.strip())
    return f"F{int(m.group(1))}" if m else None


def parse_post(text: str) -> ParsedPost:
    answer: str | None = None
    stance: Stance = "unsure"
    consensus = False
    ops: list[LedgerOp] = []
    errors: list[str] = []
    seen: set[str] = set()

    for m in _FIELD.finditer(text):
        name, value = m.group(1).upper(), m.group(2).strip()
        seen.add(name)
        if name == "ANSWER":
            if value.lower() in ("none", "n/a", ""):
                answer = None
            else:
                answer = normalize_answer(value, pick="first")
                if answer is None:
                    errors.append(f"unparseable ANSWER: {value!r}")
        elif name == "STANCE":
            v = value.lower()
            if v in ("agree", "disagree", "unsure"):
                stance = v  # type: ignore[assignment]
            else:
                stance = "unsure"
                errors.append(f"invalid STANCE: {value!r}")
        elif name == "CONSENSUS":
            v = value.lower()
            if v in ("yes", "no"):
                consensus = v == "yes"
            else:
                consensus = False
                errors.append(f"invalid CONSENSUS: {value!r}")
        elif value.lower() in _EMPTY:
            continue  # the trailer's optional lines are often written out blank
        elif name == "FACT+":
            ops.append(LedgerOp("add", text=value))
        else:
            fid = normalize_fact_id(value)
            if fid is None:
                errors.append(f"invalid fact id in {name}: {value!r}")
            else:
                ops.append(LedgerOp("confirm" if name == "FACT_OK" else "dispute", fact_id=fid))

    for required in ("ANSWER", "STANCE", "CONSENSUS"):
        if required not in seen:
            errors.append(f"missing {required}")

    body = _FIELD.sub("", text).strip()
    return ParsedPost(body, answer, stance, consensus, tuple(ops), tuple(errors))
