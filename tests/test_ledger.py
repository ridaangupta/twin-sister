from dialogic.memory import Ledger
from dialogic.protocol import LedgerOp

ADD = LedgerOp("add", text="a box holds 12 eggs")


def ok(fid="F1"):
    return LedgerOp("confirm", fact_id=fid)


def dispute(fid="F1"):
    return LedgerOp("dispute", fact_id=fid)


def test_add_starts_pending_with_sequential_ids():
    led = Ledger()
    d = led.apply((ADD, LedgerOp("add", text="3 boxes")), "A", 0)
    assert d.added == ("F1", "F2") and d.size == 2
    assert [f.status for f in led.snapshot()] == ["pending", "pending"]
    assert led.agreed() == () and len(led.open()) == 2


def test_self_confirm_is_rejected():
    led = Ledger()
    led.apply((ADD,), "A", 0)
    d = led.apply((ok(),), "A", 1)
    assert d.agreed == () and d.rejected[0][1] == "cannot confirm own fact"
    assert led.snapshot()[0].status == "pending"


def test_other_agent_confirms():
    led = Ledger()
    led.apply((ADD,), "A", 0)
    d = led.apply((ok(),), "B", 1)
    assert d.agreed == ("F1",)
    f = led.agreed()[0]
    assert f.proposed_by == "A" and f.confirmed_by == frozenset({"B"})


def test_reconfirming_agreed_fact_is_noop():
    led = Ledger()
    led.apply((ADD,), "A", 0)
    led.apply((ok(),), "B", 1)
    assert led.apply((ok(),), "B", 2).size == 0


def test_dispute_moves_back_and_needs_fresh_confirm():
    led = Ledger()
    led.apply((ADD,), "A", 0)
    led.apply((ok(),), "B", 1)
    d = led.apply((dispute(),), "B", 2)
    assert d.disputed == ("F1",) and led.disputes_total == 1
    f = led.snapshot()[0]
    assert f.status == "disputed" and f.confirmed_by == frozenset()

    assert led.apply((dispute(),), "A", 3).size == 0  # already disputed
    assert led.disputes_total == 1
    assert led.apply((ok(),), "A", 4).rejected  # proposer still cannot confirm
    assert led.apply((ok(),), "B", 5).agreed == ("F1",)


def test_unknown_id_rejected():
    d = Ledger().apply((ok("F9"), dispute("F9")), "A", 0)
    assert d.size == 0 and [r[1] for r in d.rejected] == ["unknown fact id"] * 2


def test_snapshot_is_immutable_copy():
    led = Ledger()
    led.apply((ADD,), "A", 0)
    snap = led.snapshot()
    led.apply((ok(),), "B", 1)
    assert snap[0].status == "pending"
