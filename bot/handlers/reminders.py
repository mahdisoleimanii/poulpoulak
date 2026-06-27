"""6-hourly reminders for debtors who haven't confirmed payment yet.

Each unpaid real-user debtor has a repeating JobQueue job. When it fires we
disable the previous reminder's button and post a fresh (identical) message, so
only the latest message is actionable. Jobs stop once the debtor confirms (their
obligation disappears) — see :mod:`bot.ledger` and :mod:`bot.handlers.tabs`.

JobQueue jobs live only in memory, so :func:`reschedule_all` (wired as the
Application ``post_init``) rebuilds them from persisted ``real_msgs`` on startup.
"""

from __future__ import annotations

import logging
import time

from telegram.ext import ContextTypes

from .. import config, ledger

log = logging.getLogger(__name__)

JOB_PREFIX = "dong-remind"


def job_name(chat_id: int, src: str) -> str:
    return f"{JOB_PREFIX}:{chat_id}:{src}"


def schedule(
    context: ContextTypes.DEFAULT_TYPE, chat_id: int, src: str, first: float
) -> None:
    """(Re)start the repeating reminder for one debtor."""
    jq = context.job_queue
    if jq is None:
        return
    cancel(context, chat_id, src)
    jq.run_repeating(
        reminder_job,
        interval=config.REMINDER_INTERVAL_SECONDS,
        first=max(0, first),
        data={"chat_id": chat_id, "src": src},
        name=job_name(chat_id, src),
    )


def cancel(context: ContextTypes.DEFAULT_TYPE, chat_id: int, src: str) -> None:
    jq = context.job_queue
    if jq is None:
        return
    for job in jq.get_jobs_by_name(job_name(chat_id, src)):
        job.schedule_removal()


def cancel_all(context: ContextTypes.DEFAULT_TYPE, chat_id: int) -> None:
    """Cancel every reminder job for a chat (used when tabs are replaced)."""
    jq = context.job_queue
    if jq is None:
        return
    prefix = f"{JOB_PREFIX}:{chat_id}:"
    for job in list(jq.jobs()):
        if job.name and job.name.startswith(prefix):
            job.schedule_removal()


async def reminder_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Fired every REMINDER_INTERVAL: re-ping the debtor if still unpaid."""
    data = context.job.data or {}
    chat_id = data.get("chat_id")
    src = data.get("src")
    if chat_id is None or src is None:
        return

    src_obls = [o for o in ledger.load_obligations(chat_id) if o.src == src]
    if not src_obls:
        # Paid (or tab replaced) — this job is obsolete.
        context.job.schedule_removal()
        return

    # Deferred import avoids a circular import at module load time.
    from . import tabs

    log.info("chat %s: reminding debtor %s", chat_id, src)
    try:
        await tabs.refresh_debtor_message(context, chat_id, src, src_obls)
    except Exception:
        log.exception("chat %s: failed to send reminder to %s", chat_id, src)


async def reschedule_all(application) -> None:
    """post_init hook: rebuild reminder jobs from persisted state after a restart."""
    jq = application.job_queue
    if jq is None:
        return
    now = time.time()
    count = 0
    for chat_id in ledger.chats_with_tabs():
        for src, entry in ledger.all_real_msgs(chat_id).items():
            last = entry.get("last_sent", now)
            first = config.REMINDER_INTERVAL_SECONDS - (now - last)
            jq.run_repeating(
                reminder_job,
                interval=config.REMINDER_INTERVAL_SECONDS,
                first=max(0, first),
                data={"chat_id": chat_id, "src": src},
                name=job_name(chat_id, src),
            )
            count += 1
    if count:
        log.info("rescheduled %d debtor reminder(s) after restart", count)
