"""Configuration loaded strictly from environment variables.

Required:
  BOT_TOKEN     -- the Telegram bot token (from @BotFather).
  SUPER_ADMINS  -- comma/space separated list of Telegram user IDs.

Optional:
  DATA_DIR      -- directory for the small JSON roster store (default: ./data).
  REPO_URL      -- public repository URL shown in info messages.
  SESSION_TIMEOUT_SECONDS -- inactivity timeout for a session (default: 300).
  MAX_MEMBER_BUTTONS -- cap on roster buttons shown (default: 20).
  REMINDER_INTERVAL_SECONDS -- how often to re-ping unpaid debtors
                               (default: 21600 = 6 hours).

A local `.env` file is loaded for development convenience if python-dotenv
is available; real deployments should pass env vars directly.
"""

from __future__ import annotations

import os
from pathlib import Path

try:  # optional dev convenience only
    from dotenv import load_dotenv

    # override=True so edits to .env always win over a stale value left in the
    # shell/OS environment from an earlier run (otherwise added SUPER_ADMINS
    # silently don't take effect).
    load_dotenv(override=True)
except Exception:  # pragma: no cover - dotenv is optional
    pass


def _parse_super_admins(raw: str | None) -> frozenset[int]:
    """Parse SUPER_ADMINS from a comma/whitespace separated string of IDs."""
    if not raw:
        return frozenset()
    ids: set[int] = set()
    for chunk in raw.replace(",", " ").split():
        chunk = chunk.strip()
        if not chunk:
            continue
        try:
            ids.add(int(chunk))
        except ValueError:
            # Ignore malformed entries rather than crashing the whole bot.
            continue
    return frozenset(ids)


BOT_TOKEN: str = os.environ.get("BOT_TOKEN", "").strip()
SUPER_ADMINS: frozenset[int] = _parse_super_admins(os.environ.get("SUPER_ADMINS"))

REPO_URL: str = os.environ.get(
    "REPO_URL", "https://github.com/mahdisoleimani/poulpoulak"
).strip()

DATA_DIR: Path = Path(os.environ.get("DATA_DIR", "data")).expanduser()

SESSION_TIMEOUT_SECONDS: int = int(
    os.environ.get("SESSION_TIMEOUT_SECONDS", "300")
)

# Requirement: the bot only supports groups with fewer than 20 members for
# the button list. Buttons are laid out in 2 columns (see keyboards.py).
MAX_MEMBER_BUTTONS: int = int(os.environ.get("MAX_MEMBER_BUTTONS", "20"))

# How often to re-ping a debtor who hasn't confirmed payment yet (req: remind
# every 6 hours). Configurable mainly so tests / demos can shorten it.
REMINDER_INTERVAL_SECONDS: int = int(
    os.environ.get("REMINDER_INTERVAL_SECONDS", str(6 * 60 * 60))
)


def is_super_admin(user_id: int | None) -> bool:
    """Return True if the given Telegram user id is a configured super-admin."""
    return user_id is not None and user_id in SUPER_ADMINS


def validate() -> None:
    """Raise a clear error if required configuration is missing."""
    if not BOT_TOKEN:
        raise RuntimeError(
            "BOT_TOKEN environment variable is not set. "
            "Get a token from @BotFather and export BOT_TOKEN."
        )
    if not SUPER_ADMINS:
        # Not strictly fatal, but the bot would be unusable, so warn loudly.
        raise RuntimeError(
            "SUPER_ADMINS environment variable is empty. "
            "Set it to a comma-separated list of Telegram user IDs."
        )
