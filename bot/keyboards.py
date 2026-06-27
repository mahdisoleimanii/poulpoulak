"""Inline keyboard builders for the wizard.

Callback-data scheme (kept short; Telegram caps callback_data at 64 bytes):
  pay|<member_key>      select a payer
  pno                   payer: "none of the above" (manual entry)
  pcancel               cancel the whole wizard
  achange               amount step: change payer (go back)
  acancel               amount step: cancel
  ptog|<member_key>     participants: toggle a member
  pmanual               participants: "none of the above" (manual entry)
  pok                   participants: confirm selection
  pback                 participants: change amount (go back)
  ppcancel              participants: cancel
  more|<member_key>     more-payers: pick another payer
  done                  more-payers: finish -> settle
  mcancel               more-payers: cancel

Debtor-tab buttons (post-settlement, see bot/ledger.py):
  paid1|<member_key>    debtor: "I paid" (first press -> ask to re-confirm)
  paid2|<member_key>    debtor: confirm payment (locked to that user)
  mtog|<member_key>     manual settle: owner toggles a manual debtor as paid
  mconf                 manual settle: owner confirms the selection
  noop                  inert (disabled / expired button)

Member buttons are laid out in 2 columns (req 0.5 answer).
"""

from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from . import config, messages
from .roster import Member


def _rows_2col(buttons: list[InlineKeyboardButton]) -> list[list[InlineKeyboardButton]]:
    """Lay buttons out in 2 columns."""
    return [buttons[i : i + 2] for i in range(0, len(buttons), 2)]


def _capped(members: list[Member]) -> list[Member]:
    return members[: config.MAX_MEMBER_BUTTONS]


def payer_keyboard(members: list[Member]) -> InlineKeyboardMarkup:
    """Step 9: pick who paid."""
    btns = [
        InlineKeyboardButton(m.label, callback_data=f"pay|{m.key}")
        for m in _capped(members)
    ]
    rows = _rows_2col(btns)
    rows.append(
        [InlineKeyboardButton(messages.BTN_NONE_OF_ABOVE, callback_data="pno")]
    )
    rows.append(
        [InlineKeyboardButton(messages.BTN_CANCEL, callback_data="pcancel")]
    )
    return InlineKeyboardMarkup(rows)


def amount_keyboard() -> InlineKeyboardMarkup:
    """Step 10: change payer / cancel while entering the amount."""
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(messages.BTN_CHANGE_PAYER, callback_data="achange")],
            [InlineKeyboardButton(messages.BTN_CANCEL, callback_data="acancel")],
        ]
    )


def participants_keyboard(
    members: list[Member], selected: set[str]
) -> InlineKeyboardMarkup:
    """Step 11: multi-select participants (toggle emojis)."""
    btns = []
    for m in _capped(members):
        mark = messages.SELECTED if m.key in selected else messages.UNSELECTED
        btns.append(
            InlineKeyboardButton(f"{mark} {m.label}", callback_data=f"ptog|{m.key}")
        )
    rows = _rows_2col(btns)
    rows.append(
        [InlineKeyboardButton(messages.BTN_NONE_OF_ABOVE, callback_data="pmanual")]
    )
    rows.append(
        [InlineKeyboardButton(messages.BTN_CONFIRM_PARTICIPANTS, callback_data="pok")]
    )
    rows.append(
        [InlineKeyboardButton(messages.BTN_CHANGE_AMOUNT, callback_data="pback")]
    )
    rows.append(
        [InlineKeyboardButton(messages.BTN_CANCEL, callback_data="ppcancel")]
    )
    return InlineKeyboardMarkup(rows)


def more_payers_keyboard(members: list[Member]) -> InlineKeyboardMarkup:
    """Step 12: pick another payer or finish."""
    btns = [
        InlineKeyboardButton(m.label, callback_data=f"more|{m.key}")
        for m in _capped(members)
    ]
    rows = _rows_2col(btns)
    rows.append([InlineKeyboardButton(messages.BTN_DONE, callback_data="done")])
    rows.append(
        [InlineKeyboardButton(messages.BTN_NONE_OF_ABOVE, callback_data="moreno")]
    )
    rows.append(
        [InlineKeyboardButton(messages.BTN_CANCEL, callback_data="mcancel")]
    )
    return InlineKeyboardMarkup(rows)


# --- debtor-tab keyboards ----------------------------------------------------

def debtor_prompt_keyboard(src_key: str) -> InlineKeyboardMarkup:
    """First state of a debtor's pay-message: a single 'I paid' button."""
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton(messages.BTN_PAID, callback_data=f"paid1|{src_key}")]]
    )


def debtor_confirm_keyboard(src_key: str) -> InlineKeyboardMarkup:
    """Second state (after first press): the anti-misclick confirm button."""
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton(
            messages.BTN_PAID_CONFIRM, callback_data=f"paid2|{src_key}"
        )]]
    )


def manual_settle_keyboard(
    srcs: list[tuple[str, str]], selected: set[str]
) -> InlineKeyboardMarkup:
    """Owner picks which manual debtors have paid.

    ``srcs`` is a list of ``(src_key, label)`` pairs (one per manual debtor).
    """
    rows = []
    for key, label in srcs:
        mark = messages.SELECTED if key in selected else messages.UNSELECTED
        rows.append(
            [InlineKeyboardButton(f"{mark} {label}", callback_data=f"mtog|{key}")]
        )
    rows.append(
        [InlineKeyboardButton(messages.BTN_MANUAL_CONFIRM, callback_data="mconf")]
    )
    return InlineKeyboardMarkup(rows)


def disabled_keyboard() -> InlineKeyboardMarkup:
    """A single inert button used to neutralise a superseded message."""
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton(messages.BTN_EXPIRED, callback_data="noop")]]
    )
