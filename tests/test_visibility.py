"""Agent B can never read Agent A's scratchpad, and vice versa.

An end-to-end canary test through the orchestrator is added with step 5.
"""

import dataclasses

import pytest

from dialogic.memory import AgentView, CoreView, Memory, Post

CANARY_A = "CANARY-A-7f3e"
CANARY_B = "CANARY-B-91c2"


def _strings(obj):
    """Every string reachable from a view, so leaks can't hide in nested fields."""
    if isinstance(obj, str):
        yield obj
    elif dataclasses.is_dataclass(obj):
        for f in dataclasses.fields(obj):
            yield from _strings(getattr(obj, f.name))
    elif isinstance(obj, (tuple, list, set, frozenset)):
        for x in obj:
            yield from _strings(x)


def _leaks(view, canary):
    return any(canary in s for s in _strings(view))


@pytest.fixture
def mem():
    m = Memory("How many eggs?", ["A", "B"])
    m.write_scratch("A", f"private A note {CANARY_A}")
    m.write_scratch("B", f"private B note {CANARY_B}")
    m.post(Post.from_text(0, "A", "public\nANSWER: 36\nSTANCE: unsure\nCONSENSUS: no\nFACT+: 12 per box"))
    m.post(Post.from_text(1, "B", "public too\nANSWER: 36\nSTANCE: agree\nCONSENSUS: yes"))
    return m


def test_each_agent_sees_only_its_own_pad(mem):
    va, vb = mem.view_for("A"), mem.view_for("B")
    assert va.scratchpad == (f"private A note {CANARY_A}",)
    assert vb.scratchpad == (f"private B note {CANARY_B}",)
    assert not _leaks(vb, CANARY_A)
    assert not _leaks(va, CANARY_B)


def test_both_see_the_same_core(mem):
    va, vb = mem.view_for("A"), mem.view_for("B")
    assert va.task == vb.task and va.thread == vb.thread and va.ledger == vb.ledger
    assert len(va.thread) == 2 and va.ledger[0].text == "12 per box"


def test_core_view_has_no_scratchpad(mem):
    cv = mem.core_view()
    assert "scratchpad" not in {f.name for f in dataclasses.fields(CoreView)}
    assert not _leaks(cv, CANARY_A) and not _leaks(cv, CANARY_B)


def test_agent_view_is_not_a_core_view(mem):
    assert not isinstance(mem.view_for("A"), CoreView)
    assert not issubclass(AgentView, CoreView)


def test_views_are_snapshots(mem):
    vb = mem.view_for("B")
    mem.write_scratch("B", "later")
    mem.post(Post.from_text(2, "A", "ANSWER: 36\nSTANCE: agree\nCONSENSUS: yes"))
    assert len(vb.scratchpad) == 1 and len(vb.thread) == 2
    with pytest.raises(dataclasses.FrozenInstanceError):
        vb.scratchpad = ()  # type: ignore[misc]


def test_writes_go_only_to_the_named_pad():
    m = Memory("t", ["A", "B"])
    m.write_scratch("A", CANARY_A)
    assert m.view_for("B").scratchpad == ()


def test_unknown_agent_rejected(mem):
    with pytest.raises(KeyError):
        mem.view_for("C")
    with pytest.raises(KeyError):
        mem.write_scratch("C", "x")
    with pytest.raises(KeyError):
        mem.post(Post.from_text(3, "C", "ANSWER: 1\nSTANCE: agree\nCONSENSUS: no"))


def test_duplicate_agent_ids_rejected():
    with pytest.raises(ValueError):
        Memory("t", ["A", "A"])
