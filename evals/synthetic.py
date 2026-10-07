"""Procedurally generated multi-step word problems (GSM-Infinite style).

Each problem is a random graph of integer quantities ("the number of pens Mia has")
linked by stated relations and rendered as English statements. The gold answer
comes from evaluating the graph and is re-derived by `solve`, an independent
constraint solver that reads only the structured statements. So every shipped
problem is derivable from its text.

Difficulty knobs:
  n_ops         derived quantities on the path to the answer (a chain with branches)
  n_distractors extra quantities that never feed the answer
  n_reverse     leaves whose value is hidden; a downstream value is stated instead,
                so a relation has to be inverted
  p_total       chance an operand is "the total number of items X has" (an implicit sum
                over everything X has)
  shuffle       statements in random order instead of definition order
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Any, Literal

from evals.datasets import Problem

NAMES = [
    "Mia", "Leo", "Ava", "Noah", "Zoe", "Omar", "Ivy", "Raj", "Lena", "Hugo", "Nina", "Theo", "Ruby", "Kai",
    "Sara", "Felix", "Maya", "Jonas", "Elif", "Tariq", "Greta", "Diego", "Hana", "Pavel", "Iris", "Emeka",
    "Lucia", "Sven", "Amara", "Bruno", "Yara", "Mateo", "Freya", "Kenji", "Alma", "Viktor", "Nadia", "Rafael",
]
ITEMS = [
    "apples", "pens", "marbles", "stamps", "coins", "shells", "stickers", "books", "candles", "buttons", "cards",
    "pebbles", "ribbons", "kites", "jars", "spoons", "bells", "beads", "crayons", "feathers", "keys", "lemons",
    "mugs", "nails", "oranges", "paperclips", "plums", "postcards", "puzzles", "rings", "rocks", "scarves",
    "seeds", "socks", "spools", "tickets", "tiles", "toys", "trophies", "walnuts", "whistles", "yo-yos",
    "acorns", "badges", "baskets", "bottles", "bowls", "brushes", "cups", "dice", "envelopes", "flags",
    "gloves", "hats", "lanterns", "maps", "notebooks", "onions", "pears", "pillows", "plates", "potatoes",
    "quilts", "radishes", "sandals", "saucers", "teacups", "thimbles", "umbrellas", "vases", "wagons", "whisks",
]
# Closes the world so "the total number of items X has" is well defined, and rules out
# "cannot be determined" as an answer (every generated problem is solvable; see `solve`).
PREAMBLE = (
    "Each person has only the items mentioned below, and every quantity is a whole number. "
    '"The total number of items X has" means the sum of all of X\'s quantities mentioned below. '
    "The problem is consistent and has exactly one answer, which is a whole number: if your working "
    "leads to a contradiction or a non-whole number, an earlier step is wrong."
)
FRACTIONS = {2: "half", 3: "one third", 4: "one quarter", 5: "one fifth"}

def people_for(n_ops: int) -> int:
    return min(len(NAMES), 6 + n_ops // 4)

Op = Literal["add_c", "sub_c", "mul_c", "div_c", "add", "sub", "mul"]


class _Retry(Exception):
    pass


@dataclass(frozen=True)
class Ref:
    """An operand: a stated quantity, or the implicit total of everything an owner has."""

    node: int | None = None
    owner: str | None = None  # owner of `node`, or whose total this is

    @property
    def is_total(self) -> bool:
        return self.node is None


@dataclass
class Node:
    id: int
    owner: str
    item: str
    op: Op | None  # None for a leaf
    args: tuple[Ref, ...] = ()
    const: int | None = None
    value: int = 0
    distractor: bool = False


@dataclass(frozen=True)
class Statement:
    kind: Literal["leaf", "value", "relation"]
    node: int
    owner: str
    text: str
    op: Op | None = None
    args: tuple[Ref, ...] = ()
    const: int | None = None  # relation constant, or the stated value for leaf/value
    distractor: bool = False


@dataclass
class Synthetic:
    statements: list[Statement]
    question: str
    nodes: dict[int, Node]
    target: int
    answer: int
    params: dict[str, Any] = field(default_factory=dict)

    @property
    def text(self) -> str:
        return PREAMBLE + "\n\n" + " ".join(s.text for s in self.statements) + "\n\n" + self.question

    def to_problem(self, pid: str) -> Problem:
        return Problem(pid, self.text, str(self.answer), dict(self.params))


# ------------------------------------------------------------------ arithmetic


def apply(op: Op, args: list[int], const: int | None) -> int:
    a = args[0]
    if op == "add_c":
        return a + const  # type: ignore[operator]
    if op == "sub_c":
        return a - const  # type: ignore[operator]
    if op == "mul_c":
        return a * const  # type: ignore[operator]
    if op == "div_c":
        if a % const:  # type: ignore[operator]
            raise ValueError("non-integer division")
        return a // const  # type: ignore[operator]
    b = args[1]
    return {"add": a + b, "sub": a - b, "mul": a * b}[op]


def invert(op: Op, target: int, args: list[int | None], missing: int, const: int | None) -> int | None:
    """Value of args[missing] given the relation's result. None if not an integer."""
    if op == "add_c":
        return target - const  # type: ignore[operator]
    if op == "sub_c":
        return target + const  # type: ignore[operator]
    if op == "mul_c":
        return target // const if target % const == 0 else None  # type: ignore[operator]
    if op == "div_c":
        return target * const  # type: ignore[operator]
    other = args[1 - missing]
    assert other is not None
    if op == "add":
        return target - other
    if op == "sub":
        return target + other if missing == 0 else other - target
    if op == "mul":
        return target // other if other and target % other == 0 else None
    raise ValueError(op)


# ------------------------------------------------------------------ rendering


def _np(nodes: dict[int, Node], ref: Ref) -> str:
    if ref.is_total:
        return f"the total number of items {ref.owner} has"
    n = nodes[ref.node]  # type: ignore[index]
    return f"the number of {n.item} {n.owner} has"


def _cap(s: str) -> str:
    return s[0].upper() + s[1:]


def _relation_text(nodes: dict[int, Node], n: Node, rng: random.Random) -> str:
    me = _cap(_np(nodes, Ref(n.id, n.owner)))
    a = [_np(nodes, r) for r in n.args]
    if n.op == "add_c":
        return f"{me} is {n.const} more than {a[0]}."
    if n.op == "sub_c":
        return f"{me} is {n.const} less than {a[0]}."
    if n.op == "mul_c":
        return rng.choice([f"{me} is {n.const} times {a[0]}.", f"{n.owner} has {n.const} times as many {n.item} as {a[0]}."])
    if n.op == "div_c":
        return f"{me} is {FRACTIONS[n.const]} of {a[0]}."  # type: ignore[index]
    if n.op == "add":
        return rng.choice([f"{me} equals {a[0]} plus {a[1]}.", f"{me} is the sum of {a[0]} and {a[1]}."])
    if n.op == "sub":
        return f"{me} equals {a[0]} minus {a[1]}."
    if n.op == "mul":
        return f"{me} equals {a[0]} multiplied by {a[1]}."
    raise ValueError(n.op)


def _value_text(n: Node, rng: random.Random) -> str:
    return rng.choice([f"{n.owner} has {n.value} {n.item}.", f"The number of {n.item} {n.owner} has is {n.value}."])


# ------------------------------------------------------------------ generation


class _Builder:
    def __init__(self, rng: random.Random, max_value: int, n_people: int):
        self.rng = rng
        self.max_value = max_value
        self.nodes: dict[int, Node] = {}
        self.people = rng.sample(NAMES, n_people)
        self.used: set[tuple[str, str]] = set()  # (owner, item) labels must be unique
        self.closed: set[str] = set()  # owners whose total is used; they get no further quantities

    def _new(self, op: Op | None, value: int, args: tuple[Ref, ...] = (), const: int | None = None, distractor: bool = False) -> Node:
        owners = [p for p in self.people if p not in self.closed]
        if not owners:
            raise _Retry
        for _ in range(50):
            owner, item = self.rng.choice(owners), self.rng.choice(ITEMS)
            if (owner, item) not in self.used:
                break
        else:
            raise _Retry
        self.used.add((owner, item))
        n = Node(len(self.nodes), owner, item, op, args, const, value, distractor)
        self.nodes[n.id] = n
        return n

    def ref(self, n: Node) -> Ref:
        return Ref(n.id, n.owner)

    def value(self, r: Ref) -> int:
        if r.is_total:
            return sum(n.value for n in self.nodes.values() if n.owner == r.owner)
        return self.nodes[r.node].value  # type: ignore[index]

    def leaf(self, distractor: bool = False) -> Node:
        return self._new(None, self.rng.randint(2, 30), distractor=distractor)

    def unary(self, src: Ref, distractor: bool = False) -> Node | None:
        v = self.value(src)
        c, k = self.rng.randint(2, 40), self.rng.randint(2, 6)
        options: list[tuple[Op, int, int]] = [("add_c", v + c, c), ("sub_c", v - c, c), ("mul_c", v * k, k)]
        divisors = [d for d in FRACTIONS if v % d == 0]
        if divisors:
            d = self.rng.choice(divisors)
            options.append(("div_c", v // d, d))
        options = [o for o in options if 1 <= o[1] <= self.max_value]
        if not options:
            return None
        op, value, const = self.rng.choice(options)
        return self._new(op, value, (src,), const, distractor)

    def binary(self, a: Ref, b: Ref) -> Node | None:
        va, vb = self.value(a), self.value(b)
        options: list[tuple[Op, int, tuple[Ref, Ref]]] = [("add", va + vb, (a, b))]
        if va != vb:
            options.append(("sub", abs(va - vb), (a, b) if va > vb else (b, a)))
        if va <= 25 and vb <= 25:
            options.append(("mul", va * vb, (a, b)))
        options = [o for o in options if 1 <= o[1] <= self.max_value]
        if not options:
            return None
        op, value, args = self.rng.choice(options)
        return self._new(op, value, args)

    def total(self, owner: str) -> Ref | None:
        if owner in self.closed or sum(n.owner == owner for n in self.nodes.values()) < 2:
            return None
        self.closed.add(owner)
        return Ref(None, owner)

    def ancestors(self, target: int) -> set[int]:
        seen: set[int] = set()
        stack = [Ref(target, self.nodes[target].owner)]
        while stack:
            r = stack.pop()
            ids = [n.id for n in self.nodes.values() if n.owner == r.owner] if r.is_total else [r.node]
            for i in ids:
                if i not in seen:
                    seen.add(i)  # type: ignore[arg-type]
                    stack.extend(self.nodes[i].args)  # type: ignore[index]
        return seen


def _build(rng: random.Random, n_ops: int, n_distractors: int, n_reverse: int, p_total: float, max_value: int, shuffle: bool) -> Synthetic:
    b = _Builder(rng, max_value, people_for(n_ops))
    current = b.leaf()
    for _ in range(n_ops):
        src = b.ref(current)
        if rng.random() < p_total and (t := b.total(current.owner)) is not None:
            src = t
        new = None
        if rng.random() < 0.4:
            pool = [n for n in b.nodes.values() if n.id != current.id]
            other = b.ref(rng.choice(pool)) if pool and rng.random() < 0.5 else b.ref(b.leaf())
            new = b.binary(src, other)
        new = new or b.unary(src)
        if new is None:
            raise _Retry
        current = new
    target = current.id

    # Anything off the answer's dependency path (e.g. a leaf made for a binary op that fell back to unary) is a distractor.
    needed = b.ancestors(target)
    for n in b.nodes.values():
        n.distractor = n.id not in needed
    core = sorted(needed)
    for _ in range(n_distractors):
        d = b.unary(b.ref(b.nodes[rng.choice(core)]), distractor=True) if rng.random() < 0.6 else b.leaf(distractor=True)
        if d is None:
            raise _Retry
    if b.ancestors(target) != needed:  # a distractor leaked into a total
        raise _Retry

    # Reverse: hide a core leaf that feeds a relation and state that relation's output instead,
    # so the leaf must be recovered by inverting it. `solve` later rejects unsolvable picks.
    reversed_children: list[Node] = []
    hidden: set[int] = set()
    pairs = [
        (child, r.node)
        for child in b.nodes.values()
        if child.op is not None and not child.distractor and child.id != target
        for r in child.args
        if not r.is_total and b.nodes[r.node].op is None  # type: ignore[index]
    ]
    rng.shuffle(pairs)
    for child, leaf_id in pairs:
        if len(hidden) == n_reverse:
            break
        if leaf_id in hidden or child in reversed_children:
            continue
        hidden.add(leaf_id)  # type: ignore[arg-type]
        reversed_children.append(child)
    if len(hidden) < n_reverse:
        raise _Retry

    statements: list[Statement] = []
    for n in b.nodes.values():
        if n.op is None:
            if n.id not in hidden:
                statements.append(Statement("leaf", n.id, n.owner, _value_text(n, rng), const=n.value, distractor=n.distractor))
        else:
            statements.append(Statement("relation", n.id, n.owner, _relation_text(b.nodes, n, rng), n.op, n.args, n.const, n.distractor))
    for child in reversed_children:
        statements.append(Statement("value", child.id, child.owner, _value_text(child, rng), const=child.value))
    if shuffle:
        rng.shuffle(statements)

    t = b.nodes[target]
    question = f"How many {t.item} does {t.owner} have?"
    return Synthetic(statements, question, b.nodes, target, t.value)


def solve(statements: list[Statement]) -> dict[int, int]:
    """Values derivable from the statements alone, by forward evaluation and inversion."""
    known: dict[int, int] = {}
    members: dict[str, set[int]] = {}
    for s in statements:
        members.setdefault(s.owner, set()).add(s.node)
        for r in s.args:
            if not r.is_total:
                members.setdefault(r.owner, set()).add(r.node)  # type: ignore[arg-type]
        if s.kind in ("leaf", "value"):
            known[s.node] = s.const  # type: ignore[assignment]

    def val(r: Ref) -> int | None:
        if r.is_total:
            ids = members.get(r.owner, set())  # type: ignore[arg-type]
            return sum(known[i] for i in ids) if ids and all(i in known for i in ids) else None
        return known.get(r.node)  # type: ignore[arg-type]

    changed = True
    while changed:
        changed = False
        for s in statements:
            if s.kind != "relation":
                continue
            args = [val(r) for r in s.args]
            if s.node not in known:
                if all(v is not None for v in args):
                    known[s.node] = apply(s.op, args, s.const)  # type: ignore[arg-type]
                    changed = True
                continue
            missing = [i for i, v in enumerate(args) if v is None]
            if len(missing) == 1 and not s.args[missing[0]].is_total:
                inv = invert(s.op, known[s.node], args, missing[0], s.const)  # type: ignore[arg-type]
                if inv is not None:
                    known[s.args[missing[0]].node] = inv  # type: ignore[index]
                    changed = True
    return known


def generate(
    seed: int,
    n_ops: int,
    *,
    n_distractors: int = 0,
    n_reverse: int = 0,
    p_total: float = 0.0,
    shuffle: bool = True,
    max_value: int = 10_000,
    max_attempts: int = 500,
) -> Synthetic:
    params = dict(n_ops=n_ops, n_distractors=n_distractors, n_reverse=n_reverse, p_total=p_total, shuffle=shuffle, max_value=max_value)
    rng = random.Random(f"synthetic:{seed}:{sorted(params.items())}")
    for attempt in range(max_attempts):
        try:
            p = _build(rng, n_ops, n_distractors, n_reverse, p_total, max_value, shuffle)
        except _Retry:
            continue
        # The answer must follow from the text alone, with and without the distractors.
        if solve(p.statements).get(p.target) != p.answer:
            continue
        if solve([s for s in p.statements if not s.distractor]).get(p.target) != p.answer:
            continue
        p.params = {
            **params,
            "seed": seed,
            "attempts": attempt + 1,
            "n_statements": len(p.statements),
            "n_distractor_statements": sum(s.distractor for s in p.statements),
            "n_totals": sum(r.is_total for s in p.statements for r in s.args),
            "ops": sorted(s.op for s in p.statements if s.op),  # type: ignore[type-var]
        }
        return p
    raise RuntimeError(f"could not generate a valid problem for {params} after {max_attempts} attempts")


def standard_knobs(n_ops: int) -> dict[str, Any]:
    """The one-knob recipe used for calibration and the frozen sets."""
    return dict(n_ops=n_ops, n_distractors=n_ops // 2, n_reverse=1 if n_ops >= 8 else 0, p_total=0.2, shuffle=True)


def generate_set(n: int, seed: int, **knobs: Any) -> list[Problem]:
    tag = "-".join(f"{k}{v}" for k, v in sorted(knobs.items()) if k != "shuffle")
    return [generate(seed * 1_000_003 + i, **knobs).to_problem(f"syn-{tag}-s{seed}-{i}") for i in range(n)]
