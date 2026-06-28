"""Offline harness for the wizard flow (no live bot, no network).

Drives the dong handlers with in-memory fakes to verify the plan-04 behaviour:

* the bot never repurposes a message (no ``edit_message_text``) and never
  deletes the owner's replies,
* the running summary is built correctly, and
* an uneven split flows all the way through to the persisted ledger.

JobQueue is absent (``context.job_queue = None``) so reminder scheduling is a
no-op, exactly as the production code already guards for.
"""

from __future__ import annotations

import asyncio
from decimal import Decimal
from types import SimpleNamespace

import pytest
from telegram.constants import ChatType

from bot import config, ledger, roster as roster_mod, state
from bot.handlers import dong


CHAT = 9090
OWNER = 100


def _sync(coro_fn):
    """Run an ``async def`` test via ``asyncio.run`` (no pytest-asyncio needed)."""

    def wrapper(*args, **kwargs):
        return asyncio.run(coro_fn(*args, **kwargs))

    wrapper.__name__ = coro_fn.__name__
    return wrapper


@pytest.fixture(autouse=True)
def temp_store(tmp_path):
    old = config.DATA_DIR
    config.DATA_DIR = tmp_path
    yield
    config.DATA_DIR = old
    state.chat_sessions.clear()


class FakeBot:
    def __init__(self):
        self.sent: list[SimpleNamespace] = []
        self.disabled: list[tuple[int, int]] = []
        self.edited_text: list = []  # must stay empty (no repurposing)
        self._id = 1000

    async def send_message(self, chat_id, text, reply_markup=None,
                           reply_to_message_id=None, **kw):
        self._id += 1
        msg = SimpleNamespace(
            chat_id=chat_id, text=text, reply_markup=reply_markup,
            reply_to=reply_to_message_id, message_id=self._id,
        )
        self.sent.append(msg)
        return SimpleNamespace(message_id=self._id)

    async def edit_message_reply_markup(self, chat_id=None, message_id=None,
                                        reply_markup=None, **kw):
        self.disabled.append((chat_id, message_id))

    async def edit_message_text(self, *a, **kw):  # pragma: no cover - asserted unused
        self.edited_text.append((a, kw))


class FakeQuery:
    def __init__(self, data, message_id, user_id=OWNER):
        self.data = data
        self.from_user = SimpleNamespace(id=user_id)
        self.message = SimpleNamespace(
            chat_id=CHAT, message_id=message_id,
            chat=SimpleNamespace(id=CHAT, type=ChatType.GROUP),
        )
        self.answers: list = []
        self.edited_text: list = []  # must stay empty

    async def answer(self, text=None, show_alert=False):
        self.answers.append(text)

    async def edit_message_reply_markup(self, reply_markup=None, **kw):
        pass

    async def edit_message_text(self, *a, **kw):  # pragma: no cover
        self.edited_text.append((a, kw))


class FakeMessage:
    def __init__(self, text, message_id, user_id=OWNER):
        self.text = text
        self.message_id = message_id
        self.from_user = SimpleNamespace(id=user_id)
        self.chat = SimpleNamespace(id=CHAT, type=ChatType.GROUP)
        self.replies: list = []
        self.deleted = False

    async def reply_text(self, text):
        self.replies.append(text)

    async def delete(self):  # pragma: no cover - asserted unused
        self.deleted = True


def _cb_update(query):
    return SimpleNamespace(callback_query=query)


def _msg_update(msg):
    return SimpleNamespace(
        effective_message=msg,
        effective_chat=SimpleNamespace(id=CHAT, type=ChatType.GROUP),
        effective_user=msg.from_user,
    )


def _seed_roster():
    roster_mod.remember_user(CHAT, 100, "ali", "Ali", False)
    roster_mod.remember_user(CHAT, 200, "sara", "Sara", False)
    roster_mod.remember_user(CHAT, 300, "reza", "Reza", False)


@_sync
async def test_uneven_flow_end_to_end():
    _seed_roster()
    bot = FakeBot()
    ctx = SimpleNamespace(bot=bot, job_queue=None)
    session = state.start_session(CHAT, OWNER, "ali", "Ali")

    # The first menu (payer) — pretend it already exists.
    session.menu_message_id = 1
    session.prompt_message_id = 1

    # 1) pick payer u100 -> disables payer menu, sends amount prompt.
    await dong.on_payer_callback(_cb_update(FakeQuery("pay|u100", 1)), ctx)
    assert session.draft_payer_key == "u100"
    assert session.awaiting_reply == "amount"

    # 2) owner replies the amount.
    amount_msg = FakeMessage("100", 2)
    await dong.on_amount_message(_msg_update(amount_msg), ctx)
    assert session.draft_amount == Decimal("100")
    assert amount_msg.deleted is False
    # participants prompt is a reply to the owner's amount message.
    assert bot.sent[-1].reply_to == 2

    # 3) toggle all three as participants, then continue.
    menu = session.menu_message_id
    for key in ("u100", "u200", "u300"):
        await dong.on_participant_callback(_cb_update(FakeQuery(f"ptog|{key}", menu)), ctx)
    await dong.on_participant_callback(_cb_update(FakeQuery("pok", menu)), ctx)
    assert bot.sent[-1].text == dong.messages.ASK_SPLIT_MODE

    # 4) choose uneven split.
    await dong.on_split_callback(_cb_update(FakeQuery("sun", session.menu_message_id)), ctx)
    assert session.awaiting_reply == "uneven_shares"
    assert session.draft_split_order == ["u100", "u200", "u300"]

    # 5) owner replies the shares, one per line.
    shares_msg = FakeMessage("30\n30\n40", 5)
    await dong.on_uneven_shares_message(_msg_update(shares_msg), ctx)
    assert shares_msg.replies == []  # accepted, no re-prompt
    assert shares_msg.deleted is False

    # payment committed with explicit shares.
    assert len(session.payments) == 1
    p = session.payments[0]
    assert p.shares == {"u100": Decimal("30"), "u200": Decimal("30"), "u300": Decimal("40")}

    # summary rendered, no @ pings, shares shown.
    summary_msg = bot.sent[-1].text
    assert "خلاصه تا الان" in summary_msg
    assert "@" not in summary_msg
    assert "ali (30)" in summary_msg
    assert "reza (40)" in summary_msg

    # 6) finish -> settle. Final summary re-sent, then debtor tabs dispatched.
    await dong.on_more_callback(_cb_update(FakeQuery("done", session.menu_message_id)), ctx)

    obls = ledger.load_obligations(CHAT)
    assert {(o.src, o.dst, o.amount) for o in obls} == {
        ("u200", "u100", Decimal("30")),
        ("u300", "u100", Decimal("40")),
    }

    # The bot never repurposed a message's text anywhere in the flow.
    assert bot.edited_text == []
    assert state.get_session(CHAT) is None  # session ended


@_sync
async def test_even_flow_still_works():
    _seed_roster()
    bot = FakeBot()
    ctx = SimpleNamespace(bot=bot, job_queue=None)
    session = state.start_session(CHAT, OWNER, "ali", "Ali")
    session.menu_message_id = 1
    session.prompt_message_id = 1

    await dong.on_payer_callback(_cb_update(FakeQuery("pay|u100", 1)), ctx)
    await dong.on_amount_message(_msg_update(FakeMessage("300", 2)), ctx)
    menu = session.menu_message_id
    for key in ("u100", "u200", "u300"):
        await dong.on_participant_callback(_cb_update(FakeQuery(f"ptog|{key}", menu)), ctx)
    await dong.on_participant_callback(_cb_update(FakeQuery("pok", menu)), ctx)

    # choose equal split.
    await dong.on_split_callback(_cb_update(FakeQuery("sev", session.menu_message_id)), ctx)
    assert len(session.payments) == 1
    assert session.payments[0].shares is None

    await dong.on_more_callback(_cb_update(FakeQuery("done", session.menu_message_id)), ctx)
    obls = ledger.load_obligations(CHAT)
    # 300 / 3 = 100 each; u200 and u300 each owe 100 to u100.
    assert {(o.src, o.dst, o.amount) for o in obls} == {
        ("u200", "u100", Decimal("100")),
        ("u300", "u100", Decimal("100")),
    }
    assert bot.edited_text == []


@_sync
async def test_uneven_sum_mismatch_reprompts():
    _seed_roster()
    bot = FakeBot()
    ctx = SimpleNamespace(bot=bot, job_queue=None)
    session = state.start_session(CHAT, OWNER, "ali", "Ali")
    session.draft_payer_key = "u100"
    session.draft_payer_label = "@ali"
    session.draft_amount = Decimal("100")
    session.draft_participants = {"u100", "u200", "u300"}
    session.draft_split_order = ["u100", "u200", "u300"]
    session.awaiting_reply = "uneven_shares"

    # sum 90 != 100 -> re-prompt, nothing committed.
    msg = FakeMessage("30\n30\n30", 9)
    await dong.on_uneven_shares_message(_msg_update(msg), ctx)
    assert len(msg.replies) == 1
    assert session.payments == []
    assert session.awaiting_reply == "uneven_shares"


@_sync
async def test_uneven_count_mismatch_reprompts():
    _seed_roster()
    bot = FakeBot()
    ctx = SimpleNamespace(bot=bot, job_queue=None)
    session = state.start_session(CHAT, OWNER, "ali", "Ali")
    session.draft_amount = Decimal("100")
    session.draft_split_order = ["u100", "u200", "u300"]
    session.awaiting_reply = "uneven_shares"

    msg = FakeMessage("50\n50", 9)  # only 2 numbers for 3 people
    await dong.on_uneven_shares_message(_msg_update(msg), ctx)
    assert len(msg.replies) == 1
    assert session.payments == []
