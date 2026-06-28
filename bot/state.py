"""Transient, in-memory conversation state (NOT persisted).

This holds the per-chat lock, the wizard's current selections, and the handle
to the inactivity-timeout job. All of it is lost on restart by design — only
roster/member data is persisted (see roster.py / store.py).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Optional


@dataclass
class Payment:
    """One recorded payment: who paid, how much, and for whom."""

    payer_key: str
    payer_label: str
    amount: Decimal
    participant_keys: list[str] = field(default_factory=list)
    participant_labels: list[str] = field(default_factory=list)
    # Explicit per-participant shares for an uneven split (key -> amount).
    # None means the amount is split equally among the participants.
    shares: Optional[dict[str, Decimal]] = None


@dataclass
class Session:
    """The active "دنگ" wizard for a single chat.

    Only ``owner_id`` (the user who sent the first "دنگ") may drive it (req 14).
    """

    chat_id: int
    owner_id: int
    owner_username: Optional[str]
    owner_first_name: Optional[str]

    # Completed payments so far.
    payments: list[Payment] = field(default_factory=list)

    # Draft for the payment currently being built.
    draft_payer_key: Optional[str] = None
    draft_payer_label: Optional[str] = None
    draft_amount: Optional[Decimal] = None
    draft_participants: set[str] = field(default_factory=set)
    # Uneven-split draft: explicit shares (key -> amount) and the ordered list of
    # participant keys as shown to the owner, so the numbered prompt and the
    # newline-separated reply line up.
    draft_shares: Optional[dict[str, Decimal]] = None
    draft_split_order: list[str] = field(default_factory=list)

    # The message id of the active menu (so prompts/replies can target it and
    # the timeout can disable it).
    menu_message_id: Optional[int] = None
    # The message id of the bot question the owner must reply to (manual entry
    # / amount), for the reply-only enforcement (req 14).
    prompt_message_id: Optional[int] = None

    # What kind of free-text reply we are currently expecting, if any:
    # "amount", "manual_payer", "manual_participants", "uneven_shares", or None.
    awaiting_reply: Optional[str] = None

    # Handle to the JobQueue inactivity job, so we can reschedule/cancel it.
    timeout_job: Any = None


# Per-chat active session. Presence of a key == the chat is "locked" (req 8/18).
chat_sessions: dict[int, Session] = {}


def get_session(chat_id: int) -> Optional[Session]:
    return chat_sessions.get(chat_id)


def is_locked(chat_id: int) -> bool:
    return chat_id in chat_sessions


def start_session(
    chat_id: int,
    owner_id: int,
    owner_username: Optional[str],
    owner_first_name: Optional[str],
) -> Session:
    session = Session(
        chat_id=chat_id,
        owner_id=owner_id,
        owner_username=owner_username,
        owner_first_name=owner_first_name,
    )
    chat_sessions[chat_id] = session
    return session


def end_session(chat_id: int) -> Optional[Session]:
    """Remove and return the session (releasing the lock)."""
    return chat_sessions.pop(chat_id, None)
