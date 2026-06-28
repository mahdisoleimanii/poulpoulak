"""Debt-simplification algorithm (req 15) — pure and unit-tested.

Rule: every **debtor** makes exactly ONE outgoing payment (their whole debt
goes to a single creditor). Creditors may receive from several debtors and may
additionally settle residuals among themselves (creditor -> creditor transfers
are allowed because the one-transaction constraint only restricts debtors).

Money policy (developer answer to 0.3): use :class:`decimal.Decimal`, keep up
to 2 decimal places, and NEVER round up. Per-person shares are rounded DOWN, so
any sub-cent remainder favours the debtors and is absorbed (left unsettled)
rather than charged.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from decimal import ROUND_DOWN, Decimal
from typing import Iterable

TWO_PLACES = Decimal("0.01")


def quantize_down(value: Decimal) -> Decimal:
    """Round a Decimal DOWN to 2 decimal places (never up)."""
    return value.quantize(TWO_PLACES, rounding=ROUND_DOWN)


@dataclass(frozen=True)
class Payment:
    """A payment for settlement: ``payer`` paid ``amount`` for ``participants``.

    By default the amount is split **equally** among ``participants``. For an
    uneven split, ``shares`` carries an explicit ``(participant, amount)`` per
    person (a tuple of pairs, kept hashable so the dataclass stays frozen). When
    ``shares`` is set it overrides the equal split; the per-person amounts are
    expected to sum to ``amount`` (the caller validates this).
    """

    payer: str
    amount: Decimal
    participants: tuple[str, ...]
    shares: tuple[tuple[str, Decimal], ...] | None = None


@dataclass(frozen=True)
class Transaction:
    """``src`` should pay ``amount`` to ``dst``."""

    src: str
    dst: str
    amount: Decimal


def compute_balances(payments: Iterable[Payment]) -> dict[str, Decimal]:
    """Net balance per person: positive == creditor (owed), negative == debtor.

    Each participant of a payment owes ``amount / len(participants)`` rounded
    DOWN to 2 decimals. The payer is credited the full amount they paid.
    """
    paid: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    owed: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))

    for pmt in payments:
        n = len(pmt.participants)
        if n == 0:
            continue
        paid[pmt.payer] += pmt.amount
        if pmt.shares:
            # Uneven split: each person owes their explicitly-given share.
            for person, person_share in pmt.shares:
                owed[person] += quantize_down(person_share)
        else:
            # Even split: amount divided equally, rounded DOWN per person.
            share = quantize_down(pmt.amount / Decimal(n))
            for person in pmt.participants:
                owed[person] += share

    people = set(paid) | set(owed)
    return {p: quantize_down(paid[p] - owed[p]) for p in people}


def simplify(balances: dict[str, Decimal]) -> list[Transaction]:
    """Turn net balances into transactions obeying the one-payment-per-debtor rule.

    Returns transactions where every debtor appears as ``src`` at most once.
    Creditor -> creditor residual transfers may appear in addition.
    """
    zero = Decimal("0")
    creditor_remaining: dict[str, Decimal] = {
        p: bal for p, bal in balances.items() if bal > zero
    }
    debtors: dict[str, Decimal] = {
        p: -bal for p, bal in balances.items() if bal < zero
    }

    transactions: list[Transaction] = []

    # --- assignment phase: each debtor pays their full debt to one creditor ---
    # Largest debts first; for each, pick the creditor with the most remaining
    # capacity to absorb it (deterministic tie-break by key).
    for debtor in sorted(debtors, key=lambda p: (-debtors[p], p)):
        amount = debtors[debtor]
        if not creditor_remaining:
            break
        best = max(creditor_remaining, key=lambda c: (creditor_remaining[c], c))
        transactions.append(Transaction(debtor, best, amount))
        creditor_remaining[best] -= amount

    # --- residual phase: settle over/under-funded creditors among themselves ---
    # remaining > 0  -> creditor still under-funded (needs more)
    # remaining < 0  -> creditor over-funded (received surplus, can pay it out)
    overs = sorted(
        ((c, -r) for c, r in creditor_remaining.items() if r < zero),
        key=lambda x: (-x[1], x[0]),
    )
    unders = sorted(
        ((c, r) for c, r in creditor_remaining.items() if r > zero),
        key=lambda x: (-x[1], x[0]),
    )

    i = j = 0
    overs = [list(t) for t in overs]   # make mutable
    unders = [list(t) for t in unders]
    while i < len(overs) and j < len(unders):
        over_name, over_amt = overs[i]
        under_name, under_amt = unders[j]
        pay = min(over_amt, under_amt)
        if pay > zero:
            transactions.append(Transaction(over_name, under_name, pay))
        overs[i][1] -= pay
        unders[j][1] -= pay
        if overs[i][1] <= zero:
            i += 1
        if unders[j][1] <= zero:
            j += 1

    return transactions


def settle(payments: Iterable[Payment]) -> list[Transaction]:
    """Convenience: compute balances from payments then simplify."""
    return simplify(compute_balances(payments))
