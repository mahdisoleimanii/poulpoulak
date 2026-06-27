"""Tests for the persistent debtor-tab ledger (bot/ledger.py).

These exercise the pure bookkeeping: merging invoices (accumulation + one
payment per debtor), confirming real/manual payments, and the balance
round-trip. No Telegram objects are involved.
"""

from __future__ import annotations

from collections import Counter
from decimal import Decimal

import pytest

from bot import config, ledger
from bot.settle import Payment, simplify


CHAT = 4242


@pytest.fixture(autouse=True)
def temp_store(tmp_path):
    """Point the JSON store at a throwaway dir for each test."""
    old = config.DATA_DIR
    config.DATA_DIR = tmp_path
    yield
    config.DATA_DIR = old


def D(x: str) -> Decimal:
    return Decimal(x)


def pay(payer: str, amount: str, participants: list[str]) -> Payment:
    return Payment(payer=payer, amount=D(amount), participants=tuple(participants))


def _debtor_pays_once(obls):
    """Every genuine debtor (negative net balance) is a src at most once."""
    bal = ledger.balances_from_obligations(obls)
    debtors = {k for k, v in bal.items() if v < 0}
    counts = Counter(o.src for o in obls)
    for d in debtors:
        assert counts[d] <= 1, f"{d} pays {counts[d]} times"


# --- single invoice ---------------------------------------------------------

def test_merge_single_invoice():
    label_map = {"u1": "Ali", "u2": "Sara", "u3": "Reza"}
    obls = ledger.merge_invoice(
        CHAT, [pay("u1", "300", ["u1", "u2", "u3"])], label_map
    )
    # Two debtors each owe 100 to the payer.
    assert {(o.src, o.dst, o.amount) for o in obls} == {
        ("u2", "u1", D("100")),
        ("u3", "u1", D("100")),
    }
    _debtor_pays_once(obls)
    # Persisted and reloadable.
    assert ledger.load_obligations(CHAT) == obls
    # Labels carried.
    assert all(o.src_label and o.dst_label for o in obls)


# --- accumulation across invoices ------------------------------------------

def test_second_invoice_accumulates_and_one_payment_each():
    label_map = {"u1": "Ali", "u2": "Sara", "u3": "Reza"}
    ledger.merge_invoice(CHAT, [pay("u1", "300", ["u1", "u2", "u3"])], label_map)
    # Nobody paid yet; a new invoice where u2 fronts money.
    obls = ledger.merge_invoice(
        CHAT, [pay("u2", "300", ["u1", "u2", "u3"])], label_map
    )
    _debtor_pays_once(obls)
    # Net over both invoices: u1 +0? u1 paid 300 owed 200 -> +100; u2 paid 300
    # owed 200 -> +100; u3 paid 0 owed 200 -> -200. So u3 owes 200 total, split
    # between u1 and u2 but as a single payment (one src) plus a residual.
    bal = ledger.balances_from_obligations(obls)
    assert bal["u3"] == D("-200")
    assert sum(bal.values()) == D("0")
    # u3 (the only debtor) appears exactly once.
    assert Counter(o.src for o in obls)["u3"] == 1


# --- confirm a real debtor --------------------------------------------------

def test_confirm_real_removes_obligation():
    label_map = {"u1": "Ali", "u2": "Sara", "u3": "Reza"}
    ledger.merge_invoice(CHAT, [pay("u1", "300", ["u1", "u2", "u3"])], label_map)
    remaining = ledger.confirm_real(CHAT, "u2")
    assert all(o.src != "u2" for o in remaining)
    assert {o.src for o in ledger.load_obligations(CHAT)} == {"u3"}


# --- manual settlement ------------------------------------------------------

def test_confirm_manual_selected_and_remaining():
    label_map = {"u1": "Ali", "mBob": "Bob", "mTom": "Tom"}
    # Ali fronts 300 for himself + two manual people; each owes 100.
    ledger.merge_invoice(
        CHAT, [pay("u1", "300", ["u1", "mBob", "mTom"])], label_map
    )
    assert set(ledger.manual_srcs(ledger.load_obligations(CHAT))) == {"mBob", "mTom"}

    # Owner marks only Bob as paid.
    ledger.set_manual_msg(CHAT, message_id=99, owner_id=1, selected=["mBob"])
    settled, remaining_manual = ledger.confirm_manual(CHAT)
    assert {o.src for o in settled} == {"mBob"}
    assert remaining_manual == ["mTom"]
    assert {o.src for o in ledger.load_obligations(CHAT)} == {"mTom"}


def test_toggle_manual_selected():
    ledger.set_manual_msg(CHAT, message_id=1, owner_id=7, selected=[])
    assert ledger.toggle_manual_selected(CHAT, "mBob") == ["mBob"]
    assert ledger.toggle_manual_selected(CHAT, "mTom") == ["mBob", "mTom"]
    assert ledger.toggle_manual_selected(CHAT, "mBob") == ["mTom"]


# --- balance round-trip -----------------------------------------------------

def test_balances_round_trip_with_simplify():
    label_map = {"u1": "A", "u2": "B", "u3": "C", "u4": "Dd"}
    obls = ledger.merge_invoice(
        CHAT,
        [pay("u1", "400", ["u1", "u2", "u3", "u4"])],
        label_map,
    )
    bal = ledger.balances_from_obligations(obls)
    # Re-simplifying the reconstructed balances yields the same money movement.
    re_txns = simplify(bal)
    assert sum(t.amount for t in re_txns) == sum(o.amount for o in obls)
    assert ledger.balances_from_obligations(
        [ledger.Obligation(t.src, "", t.dst, "", t.amount) for t in re_txns]
    ) == bal


# --- real-msg bookkeeping ---------------------------------------------------

def test_real_msg_state():
    ledger.merge_invoice(
        CHAT, [pay("u1", "200", ["u1", "u2"])], {"u1": "A", "u2": "B"}
    )
    ledger.set_real_msg(CHAT, "u2", message_id=55, stage="prompt", last_sent=1.0)
    assert ledger.get_real_msg(CHAT, "u2")["message_id"] == 55
    ledger.set_real_stage(CHAT, "u2", "confirm")
    assert ledger.get_real_msg(CHAT, "u2")["stage"] == "confirm"
    assert CHAT in ledger.chats_with_tabs()
