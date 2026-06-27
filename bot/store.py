"""Tiny JSON-file persistence for per-group roster data and authorized chats.

Requirement 0.1 (developer answer) overrides the original "no data" rule for
*member data*: the bot may save the members it has seen per group so the list
survives restarts, plus any manually-added names — each group keeps its own
data. Transient *wizard* state (locks, draft selections, the inactivity timer)
is NOT persisted; it lives only in :mod:`bot.state`.

Outstanding **debtor tabs** ARE persisted, per chat, under each roster's ``tabs``
key (see :mod:`bot.ledger`): who still owes whom, plus the bookkeeping needed to
re-ping debtors every few hours and to survive a restart.

The store is intentionally minimal: a single JSON file written atomically.
Concurrency is not a concern because python-telegram-bot processes updates on a
single asyncio loop.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from . import config


_DEFAULT: dict[str, Any] = {"authorized_chats": [], "rosters": {}}


def _path() -> Path:
    return config.DATA_DIR / "rosters.json"


def load() -> dict[str, Any]:
    """Load the persisted blob, returning a fresh default if absent/corrupt."""
    path = _path()
    try:
        with path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return json.loads(json.dumps(_DEFAULT))  # deep copy of default
    # Defensive: make sure the expected keys exist.
    data.setdefault("authorized_chats", [])
    data.setdefault("rosters", {})
    return data


def save(data: dict[str, Any]) -> None:
    """Atomically write the blob to disk (create the data dir if needed)."""
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    # Write to a temp file in the same dir then replace, so a crash mid-write
    # never leaves a half-written JSON file.
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except Exception:
        # Best-effort cleanup of the temp file on failure.
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
