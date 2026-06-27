"""Per-chat roster of known users, persisted across restarts (see store.py / 0.1).

Two kinds of "members" exist for a chat:

* **Seen users** — real Telegram users the bot has observed sending a message.
  We keep their ``id``, ``username`` and ``first_name`` so we can tag them later.
* **Manual names** — plain strings the owner typed for people the bot has never
  seen. They have no Telegram id, so they cannot be tagged with a real mention.

Both are stored per chat and survive restarts. Bots are never added.
"""

from __future__ import annotations

import html
from dataclasses import dataclass

from . import store


@dataclass(frozen=True)
class Member:
    """A selectable roster entry.

    ``key`` is the stable identity used by the settlement algorithm and in
    callback payloads. For seen users it is ``u<user_id>``; for manual names it
    is ``m<name>``.
    """

    key: str
    label: str            # what to show on the button / in plain text
    user_id: int | None   # None for manual entries
    username: str | None
    first_name: str | None

    @property
    def is_manual(self) -> bool:
        return self.user_id is None


def user_key(user_id: int) -> str:
    return f"u{user_id}"


def manual_key(name: str) -> str:
    return f"m{name.strip()}"


# --- persistence-backed accessors -------------------------------------------

def _chat_blob(data: dict, chat_id: int) -> dict:
    rosters = data["rosters"]
    key = str(chat_id)
    if key not in rosters:
        rosters[key] = {"users": {}, "manual": []}
    blob = rosters[key]
    blob.setdefault("users", {})
    blob.setdefault("manual", [])
    return blob


def remember_user(
    chat_id: int,
    user_id: int,
    username: str | None,
    first_name: str | None,
    is_bot: bool,
) -> None:
    """Record a seen user for this chat. Bots are ignored. Persists to disk.

    Called on every group message, so skip the disk write when nothing changed.
    """
    if is_bot:
        return
    data = store.load()
    blob = _chat_blob(data, chat_id)
    entry = {"username": username, "first_name": first_name}
    if blob["users"].get(str(user_id)) == entry:
        return  # already known and unchanged — no write needed
    blob["users"][str(user_id)] = entry
    store.save(data)


def add_manual_name(chat_id: int, name: str) -> None:
    """Persist a manually-entered name for this chat (deduplicated)."""
    name = name.strip()
    if not name:
        return
    data = store.load()
    blob = _chat_blob(data, chat_id)
    if name not in blob["manual"]:
        blob["manual"].append(name)
        store.save(data)


def members(chat_id: int) -> list[Member]:
    """Return all known members (seen users first, then manual names)."""
    data = store.load()
    rosters = data.get("rosters", {})
    blob = rosters.get(str(chat_id))
    result: list[Member] = []
    if not blob:
        return result
    for uid_str, info in blob.get("users", {}).items():
        uid = int(uid_str)
        username = info.get("username")
        first_name = info.get("first_name")
        label = (
            f"@{username}" if username else (first_name or f"کاربر {uid}")
        )
        result.append(
            Member(
                key=user_key(uid),
                label=label,
                user_id=uid,
                username=username,
                first_name=first_name,
            )
        )
    for name in blob.get("manual", []):
        result.append(
            Member(
                key=manual_key(name),
                label=name,
                user_id=None,
                username=None,
                first_name=name,
            )
        )
    return result


def find(chat_id: int, key: str) -> Member | None:
    """Look up a member by its stable key."""
    for m in members(chat_id):
        if m.key == key:
            return m
    return None


# --- tagging -----------------------------------------------------------------

def mention(member: Member) -> str:
    """Build a mention string for settlement messages (req 16, 0.4).

    * Has a username -> ``@username``.
    * Real user without username -> Markdown link on the first name using
      ``tg://user?id=...`` (the inline text-mention Telegram supports).
    * Manual name -> the plain name (cannot be linked, no id known).
    """
    if member.user_id is not None and member.username:
        return f"@{member.username}"
    if member.user_id is not None:
        name = member.first_name or f"کاربر {member.user_id}"
        return f"[{_escape_md(name)}](tg://user?id={member.user_id})"
    return _escape_md(member.label)


def mention_user(user_id: int, username: str | None, first_name: str | None) -> str:
    """Convenience mention for a raw user (e.g. the wizard owner)."""
    if username:
        return f"@{username}"
    name = first_name or f"کاربر {user_id}"
    return f"[{_escape_md(name)}](tg://user?id={user_id})"


def _escape_md(text: str) -> str:
    """Escape characters special to Telegram Markdown (legacy) link text."""
    for ch in ("[", "]", "(", ")"):
        text = text.replace(ch, "")
    return text


# --- HTML tagging (used by the persistent debtor-tab messages) ---------------
#
# The tab messages are sent with parse_mode=HTML because it is far more robust
# than legacy Markdown (only < > & need escaping), and a no-username user can
# still be reliably tagged/notified via a tg://user link.

def mention_html_user(
    user_id: int, username: str | None, first_name: str | None
) -> str:
    """HTML mention for a real user that reliably notifies them."""
    if username:
        return f"@{username}"
    name = html.escape(first_name or f"کاربر {user_id}")
    return f'<a href="tg://user?id={user_id}">{name}</a>'


def mention_html(member: Member) -> str:
    """HTML mention for a roster member (real -> tag, manual -> escaped name)."""
    if member.user_id is not None:
        return mention_html_user(member.user_id, member.username, member.first_name)
    return html.escape(member.label)
