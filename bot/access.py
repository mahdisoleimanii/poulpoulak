"""Access-control helpers: super-admins and per-chat authorization.

A chat becomes *authorized* when a super-admin adds the bot to it (req 5). That
flag is persisted alongside the roster (store.py) so a restart does not silently
de-authorize a group.
"""

from __future__ import annotations

from . import config, store


def is_super_admin(user_id: int | None) -> bool:
    return config.is_super_admin(user_id)


def is_authorized_chat(chat_id: int) -> bool:
    data = store.load()
    return chat_id in set(data.get("authorized_chats", []))


def authorize_chat(chat_id: int) -> None:
    data = store.load()
    chats = data.setdefault("authorized_chats", [])
    if chat_id not in chats:
        chats.append(chat_id)
        store.save(data)


def deauthorize_chat(chat_id: int) -> None:
    """Drop authorization (e.g. when the bot is removed from the group)."""
    data = store.load()
    chats = data.setdefault("authorized_chats", [])
    if chat_id in chats:
        chats.remove(chat_id)
        store.save(data)
