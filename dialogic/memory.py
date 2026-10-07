"""Core (shared) memory, private scratchpads, the agreed-facts ledger, and visibility rules.

Visibility is enforced by construction: agents never receive `Memory`, only an
`AgentView` built from the core plus exactly one scratchpad (their own).
`CoreView`, used for synthesis and answer extraction, has no scratchpad field.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, NamedTuple

from dialogic.protocol import LedgerOp, Stance, parse_post

FactStatus = Literal["pending", "agreed", "disputed"]


class Note(NamedTuple):
    turn: int  # the post this note was written before
    text: str
    seen: int  # posts in the thread when it was written; orders notes among posts in true time order


@dataclass(frozen=True)
class Post:
    turn: int
    agent: str
    text: str  # raw model output, trailer included
    body: str
    answer: str | None
    stance: Stance
    consensus: bool
    ledger_ops: tuple[LedgerOp, ...]
    completion_tokens: int = 0
    truncated: bool = False
    protocol_errors: tuple[str, ...] = ()

    @property
    def protocol_error(self) -> bool:
        return bool(self.protocol_errors) or self.truncated

    @classmethod
    def from_text(cls, turn: int, agent: str, text: str, *, completion_tokens: int = 0, truncated: bool = False) -> Post:
        p = parse_post(text)
        return cls(turn, agent, text, p.body, p.answer, p.stance, p.consensus, p.ledger_ops, completion_tokens, truncated, p.errors)


# -------------------------------------------------------------------------- ledger


@dataclass(frozen=True)
class Fact:
    id: str
    text: str
    proposed_by: str
    turn_added: int
    status: FactStatus
    confirmed_by: frozenset[str]


@dataclass(frozen=True)
class LedgerDelta:
    added: tuple[str, ...] = ()
    agreed: tuple[str, ...] = ()
    disputed: tuple[str, ...] = ()
    rejected: tuple[tuple[LedgerOp, str], ...] = ()

    @property
    def size(self) -> int:
        """Number of state changes (rejected ops excluded)."""
        return len(self.added) + len(self.agreed) + len(self.disputed)


@dataclass
class _Entry:
    id: str
    text: str
    proposed_by: str
    turn_added: int
    status: FactStatus = "pending"
    confirmed_by: set[str] = field(default_factory=set)

    def freeze(self) -> Fact:
        return Fact(self.id, self.text, self.proposed_by, self.turn_added, self.status, frozenset(self.confirmed_by))


class Ledger:
    """Facts are proposed by one agent and become `agreed` only when the *other* agent confirms.

    A dispute from either agent moves a fact to `disputed`; it needs a fresh
    confirmation from a non-proposer to return to `agreed`.
    """

    def __init__(self) -> None:
        self._entries: dict[str, _Entry] = {}
        self.disputes_total = 0

    def apply(self, ops: tuple[LedgerOp, ...], agent: str, turn: int) -> LedgerDelta:
        added, agreed, disputed, rejected = [], [], [], []
        for op in ops:
            if op.kind == "add":
                fid = f"F{len(self._entries) + 1}"
                self._entries[fid] = _Entry(fid, op.text or "", agent, turn)
                added.append(fid)
                continue

            entry = self._entries.get(op.fact_id or "")
            if entry is None:
                rejected.append((op, "unknown fact id"))
            elif op.kind == "confirm":
                if entry.proposed_by == agent:
                    rejected.append((op, "cannot confirm own fact"))
                elif entry.status != "agreed":
                    entry.status = "agreed"
                    entry.confirmed_by.add(agent)
                    agreed.append(entry.id)
            elif op.kind == "dispute":
                if entry.status != "disputed":
                    entry.status = "disputed"
                    entry.confirmed_by.clear()
                    disputed.append(entry.id)
                    self.disputes_total += 1
        return LedgerDelta(tuple(added), tuple(agreed), tuple(disputed), tuple(rejected))

    def snapshot(self) -> tuple[Fact, ...]:
        return tuple(e.freeze() for e in self._entries.values())

    def agreed(self) -> tuple[Fact, ...]:
        return tuple(f for f in self.snapshot() if f.status == "agreed")

    def open(self) -> tuple[Fact, ...]:
        return tuple(f for f in self.snapshot() if f.status != "agreed")


# -------------------------------------------------------------------------- views


class _LedgerAccessors:
    ledger: tuple[Fact, ...]

    @property
    def agreed_facts(self) -> tuple[Fact, ...]:
        return tuple(f for f in self.ledger if f.status == "agreed")

    @property
    def open_claims(self) -> tuple[Fact, ...]:
        return tuple(f for f in self.ledger if f.status != "agreed")


# Deliberately unrelated types: an AgentView is not a CoreView, so code typed to
# take core only (synthesis, extraction) cannot be handed a scratchpad.
@dataclass(frozen=True)
class CoreView(_LedgerAccessors):
    task: str
    thread: tuple[Post, ...]
    ledger: tuple[Fact, ...]


@dataclass(frozen=True)
class AgentView(_LedgerAccessors):
    agent_id: str
    task: str
    thread: tuple[Post, ...]
    ledger: tuple[Fact, ...]
    scratchpad: tuple[Note, ...]  # the viewing agent's own notes only


@dataclass
class Scratchpad:
    owner: str
    notes: list[Note] = field(default_factory=list)


class Memory:
    def __init__(self, task: str, agent_ids: list[str] | tuple[str, ...]):
        if len(set(agent_ids)) != len(agent_ids):
            raise ValueError("agent ids must be unique")
        self.task = task
        self.agent_ids = tuple(agent_ids)
        self.thread: list[Post] = []
        self.ledger = Ledger()
        self._pads = {a: Scratchpad(a) for a in agent_ids}

    def _check(self, agent_id: str) -> None:
        if agent_id not in self._pads:
            raise KeyError(f"unknown agent {agent_id!r}")

    def view_for(self, agent_id: str) -> AgentView:
        self._check(agent_id)
        return AgentView(
            task=self.task,
            thread=tuple(self.thread),
            ledger=self.ledger.snapshot(),
            agent_id=agent_id,
            scratchpad=tuple(self._pads[agent_id].notes),
        )

    def core_view(self) -> CoreView:
        return CoreView(task=self.task, thread=tuple(self.thread), ledger=self.ledger.snapshot())

    def write_scratch(self, agent_id: str, note: str, turn: int | None = None) -> None:
        """Append to the agent's own pad; `turn` is the post the note precedes (default: the next post)."""
        self._check(agent_id)
        seen = len(self.thread)
        self._pads[agent_id].notes.append(Note(seen if turn is None else turn, note, seen))

    def post(self, post: Post) -> LedgerDelta:
        self._check(post.agent)
        self.thread.append(post)
        return self.ledger.apply(post.ledger_ops, post.agent, post.turn)
