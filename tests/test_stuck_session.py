"""Test that stuck sessions can be recovered via stale-lock expiry or /cancel."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from telegram.constants import ChatType

from bot import access, config, messages, roster, state
from bot.handlers.dong import on_cancel_command


def _sync(coro_fn):
    """Run an async def test via asyncio.run (no pytest-asyncio needed)."""

    def wrapper(*args, **kwargs):
        return asyncio.run(coro_fn(*args, **kwargs))

    wrapper.__name__ = coro_fn.__name__
    return wrapper


@pytest.fixture(autouse=True)
def temp_store(tmp_path):
    """Use a temporary directory for DATA_DIR during tests."""
    old_dir = config.DATA_DIR
    config.DATA_DIR = tmp_path
    yield
    config.DATA_DIR = old_dir
    state.chat_sessions.clear()


def _make_update(chat_id, user_id, text="", username="test_user", first_name="Test"):
    """Create a fake Update for group chat."""
    msg = SimpleNamespace(
        text=text,
        chat=SimpleNamespace(id=chat_id, type=ChatType.GROUP),
        from_user=SimpleNamespace(
            id=user_id, username=username, first_name=first_name, is_bot=False
        ),
        reply_text=AsyncMock(),
    )
    return SimpleNamespace(
        effective_chat=SimpleNamespace(id=chat_id, type=ChatType.GROUP),
        effective_user=SimpleNamespace(
            id=user_id, username=username, first_name=first_name, is_bot=False
        ),
        effective_message=msg,
    )


def _make_context():
    """Create a fake Context for testing."""
    bot = SimpleNamespace(send_message=AsyncMock())
    return SimpleNamespace(bot=bot, job_queue=None)


@_sync
async def test_stale_lock_expires_on_keyword():
    """A stale session (idle past timeout) is released when the keyword arrives."""
    chat_id = -100
    owner_id = 1
    access.authorize_chat(chat_id)
    roster.remember_user(chat_id, owner_id, "test_user", "Test", False)

    # Start a session directly.
    session = state.start_session(chat_id, owner_id, "test_user", "Test")
    assert session is not None

    # Backdate to simulate a stuck session.
    session.last_activity -= config.SESSION_TIMEOUT_SECONDS + 10

    # Verify session is stale.
    assert session.is_stale(config.SESSION_TIMEOUT_SECONDS)

    # Import here to use the stale check inside on_dong_keyword.
    from bot.handlers.dong import on_dong_keyword

    # A keyword should clear the stale session and start fresh.
    update = _make_update(chat_id, owner_id, text="دنگ")
    context = _make_context()
    await on_dong_keyword(update, context)

    new_session = state.get_session(chat_id)
    assert new_session is not None
    assert new_session is not session  # A new session was created


@_sync
async def test_cancel_command_owner():
    """The session owner can /cancel their own session."""
    chat_id = -100
    owner_id = 1
    access.authorize_chat(chat_id)
    roster.remember_user(chat_id, owner_id, "test_user", "Test", False)

    # Start a session directly.
    session = state.start_session(chat_id, owner_id, "test_user", "Test")
    assert session is not None

    # Owner calls /cancel.
    update = _make_update(chat_id, owner_id, text="/cancel")
    context = _make_context()
    await on_cancel_command(update, context)

    # Session should be cleared.
    assert state.get_session(chat_id) is None

    # Check confirmation was sent.
    update.effective_message.reply_text.assert_called_once_with(messages.CANCELLED)


@_sync
async def test_cancel_command_admin():
    """A super-admin can /cancel any session."""
    chat_id = -100
    owner_id = 1
    admin_id = 9999  # A different user who is a super-admin
    access.authorize_chat(chat_id)
    roster.remember_user(chat_id, owner_id, "owner", "Owner", False)
    roster.remember_user(chat_id, admin_id, "admin", "Admin", False)

    # Temporarily add admin to SUPER_ADMINS.
    old_admins = config.SUPER_ADMINS
    config.SUPER_ADMINS = old_admins | {admin_id}

    try:
        # Start a session as owner.
        session = state.start_session(chat_id, owner_id, "owner", "Owner")
        assert session is not None

        # Admin calls /cancel.
        update = _make_update(chat_id, admin_id, text="/cancel", username="admin", first_name="Admin")
        context = _make_context()
        await on_cancel_command(update, context)

        # Session should be cleared.
        assert state.get_session(chat_id) is None

        # Check confirmation was sent.
        update.effective_message.reply_text.assert_called_once_with(messages.CANCELLED)
    finally:
        config.SUPER_ADMINS = old_admins


@_sync
async def test_cancel_command_unauthorized_user():
    """A non-owner, non-admin cannot /cancel the session."""
    chat_id = -100
    owner_id = 1
    other_id = 2
    access.authorize_chat(chat_id)
    roster.remember_user(chat_id, owner_id, "owner", "Owner", False)
    roster.remember_user(chat_id, other_id, "other", "Other", False)

    # Start a session as owner.
    session = state.start_session(chat_id, owner_id, "owner", "Owner")
    assert session is not None

    # Other user tries /cancel.
    update = _make_update(chat_id, other_id, text="/cancel", username="other", first_name="Other")
    context = _make_context()
    await on_cancel_command(update, context)

    # Session should remain active.
    assert state.get_session(chat_id) is session

    # Unauthorized users get ONLY_OWNER message.
    update.effective_message.reply_text.assert_called_once_with(messages.ONLY_OWNER)


@_sync
async def test_cancel_command_no_session():
    """Calling /cancel with no active session does nothing."""
    chat_id = -100
    user_id = 1
    access.authorize_chat(chat_id)
    roster.remember_user(chat_id, user_id, "test_user", "Test", False)

    # No session exists.
    assert state.get_session(chat_id) is None

    # User calls /cancel.
    update = _make_update(chat_id, user_id, text="/cancel")
    context = _make_context()
    await on_cancel_command(update, context)

    # Still no session.
    assert state.get_session(chat_id) is None

    # NO_ACTIVE_SESSION message sent.
    update.effective_message.reply_text.assert_called_once_with(messages.NO_ACTIVE_SESSION)
