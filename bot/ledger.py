"""Persistent debtor *tabs* — who still owes whom, across invoices.

This is the durable counterpart to the transient wizard in :mod:`bot.state`.
When a session owner finishes a "دنگ" run, the resulting transactions are merged
into the chat's outstanding tab and persisted here (in ``rosters[chat].tabs``).
Each debtor keeps a running tab until they confirm payment.

Design (see plans/03):

* **Source of truth = the outstanding ``obligations`` list.** Each obligation is
  one "``src`` should pay ``dst`` ``amount``" line. Genuine debtors have exactly
  one; an over-funded creditor may have residual creditor→creditor lines.
* A **new invoice** is merged by reconstructing net balances from the current
  obligations, adding the new invoice's balance delta, then re-running
  :func:`bot.settle.simplify` — so debts accumulate and every debtor still pays
  exactly once.
* **Confirming** a payment just removes that ``src``'s obligation(s).

This module is deliberately free of any Telegram imports so it can be unit
tested in isolation. It only knows about :mod:`bot.store` and :mod:`bot.settle`.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from . import settle, store


# --- model ------------------------------------------------------------------

@dataclass(frozen=True)
class Obligation:
    """One outstanding line: ``src`` should pay ``amount`` to ``dst``.

    ``src``/``dst`` are stable roster keys (``u<id>`` / ``m<name>``). The labels
    are carried so messages can be rendered even if a member later disappears.
    """

    src: str
    src_label: str
    dst: str
    dst_label: str
    amount: Decimal


def is_real_key(key: str) -> bool:
    """True for a real Telegram-user key (``u<id>``); False for manual (``m...``)."""
    return key.startswith("u")


def user_id_of(key: str) -> int | None:
    """Extract the numeric user id from a real key, or None for manual keys."""
    if not is_real_key(key):
        return None
    try:
        return int(key[1:])
    except ValueError:
        return None


# --- persistence ------------------------------------------------------------

def _empty_tabs() -> dict:
    return {"obligations": [], "real_msgs": {}, "manual_msg": None}


def _chat_tabs(data: dict, chat_id: int) -> dict:
    """Return the (mutable) ``tabs`` blob for a chat, creating it if absent."""
    rosters = data.setdefault("rosters", {})
    blob = rosters.setdefault(str(chat_id), {})
    tabs = blob.setdefault("tabs", _empty_tabs())
    tabs.setdefault("obligations", [])
    tabs.setdefault("real_msgs", {})
    tabs.setdefault("manual_msg", None)
    return tabs


def _to_dict(o: Obligation) -> dict:
    return {
        "src": o.src,
        "src_label": o.src_label,
        "dst": o.dst,
        "dst_label": o.dst_label,
        "amount": str(o.amount),
    }


def _from_dict(d: dict) -> Obligation:
    return Obligation(
        src=d["src"],
        src_label=d.get("src_label", d["src"]),
        dst=d["dst"],
        dst_label=d.get("dst_label", d["dst"]),
        amount=Decimal(str(d.get("amount", "0"))),
    )


def load_obligations(chat_id: int) -> list[Obligation]:
    data = store.load()
    rosters = data.get("rosters", {})
    blob = rosters.get(str(chat_id)) or {}
    tabs = blob.get("tabs") or {}
    return [_from_dict(d) for d in tabs.get("obligations", [])]


def _save_obligations(data: dict, chat_id: int, obls: list[Obligation]) -> None:
    tabs = _chat_tabs(data, chat_id)
    tabs["obligations"] = [_to_dict(o) for o in obls]


# --- balance bookkeeping ----------------------------------------------------

def balances_from_obligations(obls: list[Obligation]) -> dict[str, Decimal]:
    """Reconstruct net balances implied by the outstanding obligations.

    Positive == creditor (owed money), negative == debtor. Summing an
    obligation moves money from ``src`` (pays) to ``dst`` (receives).
    """
    bal: dict[str, Decimal] = {}
    for o in obls:
        bal[o.src] = bal.get(o.src, Decimal("0")) - o.amount
        bal[o.dst] = bal.get(o.dst, Decimal("0")) + o.amount
    return bal


def merge_invoice(
    chat_id: int,
    new_payments: list[settle.Payment],
    label_map: dict[str, str],
) -> list[Obligation]:
    """Fold a finished invoice into the chat's outstanding tab and persist.

    Net balances are reconstructed from the current obligations, the new
    invoice's balances are added, and the combined position is re-simplified so
    every debtor pays exactly once. The new obligation set REPLACES the old one;
    message bookkeeping (``real_msgs``/``manual_msg``) is reset so callers can
    send fresh messages.
    """
    data = store.load()
    current = [_from_dict(d) for d in _chat_tabs(data, chat_id)["obligations"]]

    balances = balances_from_obligations(current)
    for key, delta in settle.compute_balances(new_payments).items():
        balances[key] = balances.get(key, Decimal("0")) + delta

    txns = settle.simplify(balances)

    def _label(key: str) -> str:
        return label_map.get(key, key)

    obls = [
        Obligation(
            src=t.src,
            src_label=_label(t.src),
            dst=t.dst,
            dst_label=_label(t.dst),
            amount=t.amount,
        )
        for t in txns
        if t.amount > Decimal("0")
    ]

    tabs = _chat_tabs(data, chat_id)
    tabs["obligations"] = [_to_dict(o) for o in obls]
    tabs["real_msgs"] = {}
    tabs["manual_msg"] = None
    store.save(data)
    return obls


def group_by_src(obls: list[Obligation]) -> dict[str, list[Obligation]]:
    """Group obligations by paying ``src`` (insertion order preserved)."""
    grouped: dict[str, list[Obligation]] = {}
    for o in obls:
        grouped.setdefault(o.src, []).append(o)
    return grouped


def real_srcs(obls: list[Obligation]) -> list[str]:
    """Distinct real-user payer keys, in first-seen order."""
    seen: list[str] = []
    for o in obls:
        if is_real_key(o.src) and o.src not in seen:
            seen.append(o.src)
    return seen


def manual_srcs(obls: list[Obligation]) -> list[str]:
    """Distinct manual payer keys, in first-seen order."""
    seen: list[str] = []
    for o in obls:
        if not is_real_key(o.src) and o.src not in seen:
            seen.append(o.src)
    return seen


# --- confirmations ----------------------------------------------------------

def confirm_real(chat_id: int, src_key: str) -> list[Obligation]:
    """Mark a real debtor's tab paid: drop their obligation(s) and msg state.

    Returns the remaining obligations after removal.
    """
    data = store.load()
    tabs = _chat_tabs(data, chat_id)
    remaining = [
        _from_dict(d) for d in tabs["obligations"] if d["src"] != src_key
    ]
    tabs["obligations"] = [_to_dict(o) for o in remaining]
    tabs["real_msgs"].pop(src_key, None)
    store.save(data)
    return remaining


def confirm_manual(chat_id: int) -> tuple[list[Obligation], list[str]]:
    """Settle the manual debtors the owner has selected.

    Removes obligations whose ``src`` is in ``manual_msg.selected``. Returns
    ``(settled, remaining_manual_srcs)`` where ``settled`` are the removed
    obligations and ``remaining_manual_srcs`` are manual payers still unpaid.
    """
    data = store.load()
    tabs = _chat_tabs(data, chat_id)
    manual_msg = tabs.get("manual_msg") or {}
    selected = set(manual_msg.get("selected", []))

    all_obls = [_from_dict(d) for d in tabs["obligations"]]
    settled = [o for o in all_obls if o.src in selected]
    remaining = [o for o in all_obls if o.src not in selected]
    tabs["obligations"] = [_to_dict(o) for o in remaining]
    store.save(data)

    remaining_manual = manual_srcs(remaining)
    return settled, remaining_manual


# --- real-user message bookkeeping ------------------------------------------

def set_real_msg(
    chat_id: int,
    src_key: str,
    message_id: int,
    stage: str,
    last_sent: float,
) -> None:
    """Record the active reminder message for a real debtor."""
    data = store.load()
    tabs = _chat_tabs(data, chat_id)
    tabs["real_msgs"][src_key] = {
        "message_id": message_id,
        "stage": stage,
        "last_sent": last_sent,
    }
    store.save(data)


def get_real_msg(chat_id: int, src_key: str) -> dict | None:
    data = store.load()
    tabs = _chat_tabs(data, chat_id)
    return tabs["real_msgs"].get(src_key)


def set_real_stage(chat_id: int, src_key: str, stage: str) -> None:
    """Update just the confirm-stage of a real debtor's active message."""
    data = store.load()
    tabs = _chat_tabs(data, chat_id)
    entry = tabs["real_msgs"].get(src_key)
    if entry is None:
        return
    entry["stage"] = stage
    store.save(data)


def all_real_msgs(chat_id: int) -> dict[str, dict]:
    data = store.load()
    tabs = _chat_tabs(data, chat_id)
    return dict(tabs["real_msgs"])


def chats_with_tabs() -> list[int]:
    """Chat ids that currently have any persisted tab state (for restart)."""
    data = store.load()
    out: list[int] = []
    for key, blob in data.get("rosters", {}).items():
        tabs = (blob or {}).get("tabs") or {}
        if tabs.get("obligations") or tabs.get("real_msgs"):
            try:
                out.append(int(key))
            except ValueError:
                continue
    return out


# --- manual-group message bookkeeping ---------------------------------------

def set_manual_msg(
    chat_id: int, message_id: int, owner_id: int, selected: list[str] | None = None
) -> None:
    data = store.load()
    tabs = _chat_tabs(data, chat_id)
    tabs["manual_msg"] = {
        "message_id": message_id,
        "owner_id": owner_id,
        "selected": list(selected or []),
    }
    store.save(data)


def get_manual_msg(chat_id: int) -> dict | None:
    data = store.load()
    tabs = _chat_tabs(data, chat_id)
    return tabs.get("manual_msg")


def clear_manual_msg(chat_id: int) -> None:
    data = store.load()
    tabs = _chat_tabs(data, chat_id)
    tabs["manual_msg"] = None
    store.save(data)


def toggle_manual_selected(chat_id: int, src_key: str) -> list[str]:
    """Toggle a manual debtor in the owner's selection; return the new selection."""
    data = store.load()
    tabs = _chat_tabs(data, chat_id)
    manual_msg = tabs.get("manual_msg")
    if manual_msg is None:
        return []
    selected = manual_msg.setdefault("selected", [])
    if src_key in selected:
        selected.remove(src_key)
    else:
        selected.append(src_key)
    store.save(data)
    return list(selected)
