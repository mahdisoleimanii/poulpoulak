"""Offline tests for the stale-tab-button guard (plans/05).

A pay-message from a previous invoice (whose disabling edit never landed) must
not be able to confirm the debtor's *current* obligation. Only the latest
tracked message per debtor — and the latest manual-settle message — is
actionable. Driven with in-memory fakes; no live bot, no network.
"""

from __future__ import annotations

import asyncio
from decimal import Decimal
from types import SimpleNamespace

import pytest

from bot import config, ledger, messages, roster as roster_mod
from bot.handlers import tabs
from bot.settle import Payment


CHAT = 7777


@pytest.fixture(autouse=True)
def temp_store(tmp_path):
    old = config.DATA_DIR
    config.DATA_DIR = tmp_path
    yield
    config.DATA_DIR = old


def _sync(coro_fn):
    def wrapper(*args, **kwargs):
        return asyncio.run(coro_fn(*args, **kwargs))

    wrapper.__name__ = coro_fn.__name__
    return wrapper


class FakeBot:
    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id, text, **kw):
        self.sent.append(text)
        return SimpleNamespace(message_id=9999)


class FakeQuery:
    def __init__(self, data, message_id, user_id):
        self.data = data
        self.from_user = SimpleNamespace(id=user_id)
        self.message = SimpleNamespace(chat_id=CHAT, message_id=message_id)
        self.answers = []
        self.disabled = False
        self.edited_text = []

    async def answer(self, text=None, show_alert=False):
        self.answers.append(text)

    async def edit_message_reply_markup(self, reply_markup=None, **kw):
        self.disabled = True

    async def edit_message_text(self, *a, **kw):
        self.edited_text.append((a, kw))


def _seed_one_obligation():
    """u2 owes u1 100; track u2's current pay-message as id 500."""
    roster_mod.remember_user(CHAT, 1, "ali", "Ali", False)
    roster_mod.remember_user(CHAT, 2, "sara", "Sara", False)
    ledger.merge_invoice(
        CHAT,
        [Payment("u1", Decimal("200"), ("u1", "u2"))],
        {"u1": "@ali", "u2": "@sara"},
    )
    ledger.set_real_msg(CHAT, "u2", message_id=500, stage="prompt", last_sent=1.0)


@_sync
async def test_stale_real_press_is_rejected():
    _seed_one_obligation()
    ctx = SimpleNamespace(bot=FakeBot(), job_queue=None)

    # Press paid2 from an OLD message (499) — not the tracked 500.
    q = FakeQuery("paid2|u2", message_id=499, user_id=2)
    await tabs.on_paid_callback(SimpleNamespace(callback_query=q), ctx)

    # Obligation untouched, user warned, stale message disabled, no confirmation.
    assert {o.src for o in ledger.load_obligations(CHAT)} == {"u2"}
    assert q.answers == [messages.TAB_MESSAGE_OUTDATED]
    assert q.disabled is True
    assert q.edited_text == []


@_sync
async def test_current_real_press_confirms():
    _seed_one_obligation()
    ctx = SimpleNamespace(bot=FakeBot(), job_queue=None)

    # Press paid2 from the CURRENT tracked message (500).
    q = FakeQuery("paid2|u2", message_id=500, user_id=2)
    await tabs.on_paid_callback(SimpleNamespace(callback_query=q), ctx)

    # Obligation removed (confirmed).
    assert all(o.src != "u2" for o in ledger.load_obligations(CHAT))
    assert messages.TAB_MESSAGE_OUTDATED not in q.answers


@_sync
async def test_stale_manual_press_is_rejected():
    roster_mod.remember_user(CHAT, 1, "ali", "Ali", False)
    ledger.merge_invoice(
        CHAT,
        [Payment("u1", Decimal("300"), ("u1", "mBob", "mTom"))],
        {"u1": "@ali", "mBob": "Bob", "mTom": "Tom"},
    )
    ledger.set_manual_msg(CHAT, message_id=600, owner_id=7, selected=[])
    ctx = SimpleNamespace(bot=FakeBot(), job_queue=None)

    # Owner presses confirm from an OLD manual message (599) — not tracked 600.
    q = FakeQuery("mconf", message_id=599, user_id=7)
    await tabs.on_manual_settle_callback(SimpleNamespace(callback_query=q), ctx)

    # Nothing settled; warned and disabled.
    assert {o.src for o in ledger.load_obligations(CHAT)} == {"mBob", "mTom"}
    assert q.answers == [messages.TAB_MESSAGE_OUTDATED]
    assert q.disabled is True
