"""Tests for the debt-simplification algorithm (bot/settle.py).

Encodes the two worked examples from PLAN.md part 15 and the core invariant:
every debtor appears as a payment source (``src``) in at most one transaction.
"""

from __future__ import annotations

from collections import Counter
from decimal import Decimal

from bot.settle import Payment, Transaction, compute_balances, settle, simplify


def D(x: str) -> Decimal:
    return Decimal(x)


# --- invariants used by several tests ---------------------------------------

def assert_debtor_single_payment(balances, txns):
    """Each debtor (negative balance) is the ``src`` of at most one transaction."""
    debtors = {p for p, b in balances.items() if b < 0}
    src_counts = Counter(t.src for t in txns)
    for d in debtors:
        assert src_counts[d] <= 1, f"debtor {d} pays more than once: {src_counts[d]}"


def assert_conserved(balances, txns):
    """Each person's (received - sent) must equal their net balance."""
    net = {p: Decimal("0") for p in balances}
    for t in txns:
        net[t.src] = net.get(t.src, Decimal("0")) - t.amount
        net[t.dst] = net.get(t.dst, Decimal("0")) + t.amount
    for p, bal in balances.items():
        assert net.get(p, Decimal("0")) == bal, (
            f"{p}: settled {net.get(p)} != balance {bal}"
        )


# --- Example 1: the 500 / 450 case ------------------------------------------

def test_example_1_balances():
    # A paid 500 for B, C, D, E (A not included).
    # B paid 450 for everyone (A, B, C, D, E).
    payments = [
        Payment("A", D("500"), ("B", "C", "D", "E")),
        Payment("B", D("450"), ("A", "B", "C", "D", "E")),
    ]
    balances = compute_balances(payments)
    assert balances["A"] == D("410")
    assert balances["B"] == D("235")
    assert balances["C"] == D("-215")
    assert balances["D"] == D("-215")
    assert balances["E"] == D("-215")


def test_example_1_settlement():
    payments = [
        Payment("A", D("500"), ("B", "C", "D", "E")),
        Payment("B", D("450"), ("A", "B", "C", "D", "E")),
    ]
    balances = compute_balances(payments)
    txns = settle(payments)

    assert_debtor_single_payment(balances, txns)
    assert_conserved(balances, txns)

    # C, D, E each owe 215 and each must pay exactly once.
    for d in ("C", "D", "E"):
        paid = [t for t in txns if t.src == d]
        assert len(paid) == 1
        assert paid[0].amount == D("215")

    # The plan's expected shape: 3 debtor payments + 1 creditor residual = 4.
    assert len(txns) == 4


# --- Example 2: the 400 / 600 case ------------------------------------------

def test_example_2_balances():
    payments = [
        Payment("A", D("400"), ("A", "B", "C", "D", "E")),
        Payment("B", D("600"), ("A", "B", "C", "D", "E")),
    ]
    balances = compute_balances(payments)
    assert balances["A"] == D("200")
    assert balances["B"] == D("400")
    assert balances["C"] == D("-200")
    assert balances["D"] == D("-200")
    assert balances["E"] == D("-200")


def test_example_2_settlement():
    payments = [
        Payment("A", D("400"), ("A", "B", "C", "D", "E")),
        Payment("B", D("600"), ("A", "B", "C", "D", "E")),
    ]
    balances = compute_balances(payments)
    txns = settle(payments)

    assert_debtor_single_payment(balances, txns)
    assert_conserved(balances, txns)

    # Clean split: one debtor pays A, the other two pay B. No residuals needed.
    assert len(txns) == 3
    # A receives exactly one 200 payment; B receives two.
    assert sum(1 for t in txns if t.dst == "A") == 1
    assert sum(1 for t in txns if t.dst == "B") == 2


# --- Simple single-payer division (req 15a) ---------------------------------

def test_simple_single_payer():
    # A pays 300 for A, B, C -> B and C each owe 100, each pays A once.
    payments = [Payment("A", D("300"), ("A", "B", "C"))]
    balances = compute_balances(payments)
    assert balances["A"] == D("200")
    assert balances["B"] == D("-100")
    assert balances["C"] == D("-100")

    txns = settle(payments)
    assert_debtor_single_payment(balances, txns)
    assert_conserved(balances, txns)
    assert len(txns) == 2
    assert all(t.dst == "A" and t.amount == D("100") for t in txns)


# --- Rounding policy: never round up (0.3) ----------------------------------

def test_never_rounds_up():
    # 100 split 3 ways -> 33.33 each (33.3333... rounded DOWN to 33.33).
    payments = [Payment("A", D("100"), ("A", "B", "C"))]
    balances = compute_balances(payments)
    # Each non-payer owes 33.33 (rounded down, not 33.34).
    assert balances["B"] == D("-33.33")
    assert balances["C"] == D("-33.33")
    # Payer A: paid 100, owes own share 33.33 -> +66.67.
    assert balances["A"] == D("66.67")


def test_no_transactions_when_balanced():
    payments = [Payment("A", D("100"), ("A", "B")), Payment("B", D("100"), ("A", "B"))]
    balances = compute_balances(payments)
    assert balances["A"] == D("0")
    assert balances["B"] == D("0")
    assert simplify(balances) == []


def test_returns_transaction_objects():
    txns = settle([Payment("A", D("10"), ("A", "B"))])
    assert all(isinstance(t, Transaction) for t in txns)
