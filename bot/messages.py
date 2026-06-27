"""All user-facing strings. The bot UI is Persian-only (req 6).

Strings that embed a tag use ``{tag}`` placeholders; callers pass an
already-formatted mention (see :mod:`bot.roster` ``mention``).
"""

from __future__ import annotations

# --- /start (private chat) ---------------------------------------------------

def start_non_admin(repo_url: str) -> str:
    return (
        "سلام! 👋\n\n"
        "این یک ربات «دنگ» است؛ برای تقسیم خرج‌های گروهی بین دوستان.\n"
        "این ربات فقط داخل گروه و توسط ادمین‌های اصلی کار می‌کند.\n\n"
        f"سورس‌کد و راهنمای راه‌اندازی نسخهٔ خودتان:\n{repo_url}"
    )


def start_admin(repo_url: str) -> str:
    return (
        "سلام ادمین! 👋\n\n"
        "برای استفاده:\n"
        "۱) ربات را به یک گروه اضافه کن (فقط ادمین‌های اصلی می‌توانند اضافه کنند).\n"
        "۲) بعد از اضافه‌شدن، ربات اعضای گروه را به‌محض ارسال پیام می‌شناسد.\n"
        "۳) هر کسی در گروه با ارسال پیامی که فقط شامل کلمهٔ «دنگ» باشد، "
        "محاسبه را شروع می‌کند.\n\n"
        "نکته: تلگرام اجازهٔ گرفتن لیست کامل اعضا را به ربات نمی‌دهد؛ "
        "برای همین ربات فقط کسانی را نشان می‌دهد که پیامی فرستاده‌اند. "
        "بقیه را می‌توانی دستی وارد کنی.\n\n"
        f"سورس‌کد:\n{repo_url}"
    )


# --- Access control ----------------------------------------------------------

# Bot added to a group by a non-super-admin (req 5).
ADDED_BY_NON_ADMIN = (
    "متأسفم، فقط ادمین‌های اصلیِ این ربات می‌توانند آن را به گروه اضافه کنند.\n"
    "این ربات در این گروه کار نخواهد کرد."
)

ADDED_BY_ADMIN = (
    "سلام به همگی! 🎉\n"
    "ربات «دنگ» فعال شد. هر وقت خواستید خرج‌ها را حساب کنیم، "
    "کافیست کسی فقط کلمهٔ «دنگ» را بفرستد."
)


# --- The wizard --------------------------------------------------------------

def greeting(tag: str) -> str:
    return (
        f"سلام {tag}!\n\n"
        "امیدوارم که بهتون خوش گذشته باشه 😁!\n"
        "بریم خرجا رو حساب کنیم. اگه بیشتر از یه نفر هم حساب کرده نگران نباش، "
        "بعدش درستش میکنیم.\n\n"
        "کی پول داده؟"
    )


def ask_amount(tag: str) -> str:
    return f"{tag} چقد پول داد؟ (به تومن وارد کن)"


ASK_PARTICIPANTS = "این خرج مال کیاست؟"

ASK_MORE_PAYERS = (
    "کس دیگه ای هم خرج کرده؟\n\n"
    'اگه آره، انتخابش کن. اگه نه، بزن "✅ تموم"'
)

# Manual-entry prompts (None-of-the-above path).
ASK_MANUAL_PAYER = "اسم کسی که پول داده رو بنویس (در پاسخ به همین پیام)."
ASK_MANUAL_PARTICIPANTS = (
    "اسم کسایی که تو این خرج بودن رو بنویس. "
    "می‌تونی چند اسم رو با کاما (،) جدا کنی. (در پاسخ به همین پیام)"
)

# Validation / errors.
INVALID_AMOUNT = "مبلغ نامعتبره. لطفاً یک عدد مثبت وارد کن (مثلاً ۱۲۵۰۰۰)."
NO_PARTICIPANTS_SELECTED = "حداقل یک نفر رو انتخاب کن."
ONLY_OWNER = "این محاسبه رو یکی دیگه شروع کرده؛ فقط خودش می‌تونه ادامه بده."
REPLY_REQUIRED = "لطفاً جوابت رو روی همون پیام سؤال ربات «ریپلای» کن."

# Cancel / timeout / busy.
CANCELLED = "هیچ خرجی ثبت نشد."
TIMEOUT = "زمان محاسبه تموم شد و منو غیرفعال شد. هیچ خرجی ثبت نشد."
BUSY = "یکی داره همین الان از ربات استفاده می‌کنه. لطفاً صبر کن تا تموم شه."
NO_ROSTER = (
    "هنوز کسی رو نمی‌شناسم! اول بذار چند نفر تو گروه پیام بدن، "
    "یا از گزینهٔ «یکی دیگه» برای وارد کردن دستی اسم‌ها استفاده کن."
)

# Settlement.
NOTHING_TO_SETTLE = "حسابی برای تسویه نیست؛ همه با هم بی‌حسابن. 🙂"
SETTLEMENT_HEADER = "تسویه‌حساب 🧾\n"


def settlement_line(src_tag: str, dst_tag: str, amount: str) -> str:
    return f"{src_tag}\nبه: {dst_tag}\nمبلغ: {amount} تومن"


# --- Debtor tabs (persistent settlement) -------------------------------------

def debtor_tab(src_tag: str, amount: str, dst_tag: str) -> str:
    """The pay-message sent to (and tagging) a real-user debtor."""
    return (
        f"{src_tag} 👋\n\n"
        f"سهم تو از دنگ: <b>{amount} تومن</b>\n"
        f"باید بدی به: {dst_tag}\n\n"
        "وقتی پرداخت کردی، دکمهٔ زیر رو بزن."
    )


def debtor_tab_line(amount: str, dst_tag: str) -> str:
    return f"• {amount} تومن به {dst_tag}"


def debtor_tab_multi(src_tag: str, lines: list[str]) -> str:
    """Pay-message when one debtor owes more than one creditor (residual case)."""
    body = "\n".join(lines)
    return (
        f"{src_tag} 👋\n\n"
        f"سهم تو از دنگ:\n{body}\n\n"
        "وقتی همه رو پرداخت کردی، دکمهٔ زیر رو بزن."
    )


# Appended to the same message after the first button press (anti-misclick).
DOUBLE_CONFIRM_SUFFIX = "\n\n⚠️ برای اطمینان، یه بار دیگه تایید کن."


def debtor_paid(src_tag: str, dst_tag: str, amount: str) -> str:
    """Settled state shown on the debtor's message after final confirmation."""
    return f"✅ {src_tag} مبلغ {amount} تومن رو به {dst_tag} پرداخت کرد. ممنون!"


def debtor_paid_generic(src_tag: str) -> str:
    """Settled state when the debtor had several lines."""
    return f"✅ {src_tag} دنگش رو تسویه کرد. ممنون!"


def manual_settle(owner_tag: str, lines: list[str]) -> str:
    """Owner-facing message for manually-added debtors (can't be tagged)."""
    body = "\n".join(lines)
    return (
        f"{owner_tag} این‌ها رو دستی اضافه کردی و هنوز بدهکارن 👇\n\n"
        f"{body}\n\n"
        "هر کدوم که پرداخت کرد رو انتخاب کن و بعد «✅ تایید» رو بزن."
    )


def manual_line(label: str, amount: str, dst_tag: str) -> str:
    return f"• {label} باید {amount} تومن بده به {dst_tag}"


def manual_settled_summary(lines: list[str]) -> str:
    body = "\n".join(lines) if lines else "—"
    return f"✅ این بدهی‌ها تسویه شد:\n{body}"


TAB_ALL_SETTLED = "همهٔ دنگا تسویه شد! 🎉"
NOT_YOUR_BUTTON = "این دکمه مال تو نیست 🙂"


# --- Button labels -----------------------------------------------------------

BTN_NONE_OF_ABOVE = "یکی دیگه"
BTN_CANCEL = "بیخیال ❌"
BTN_CHANGE_PAYER = "تغییر پرداخت کننده"
BTN_CHANGE_AMOUNT = "تغییر مبلغ"
BTN_DONE = "✅ تموم"
BTN_CONFIRM_PARTICIPANTS = "✅ ادامه"
SELECTED = "🟢"
UNSELECTED = "🔘"

# Debtor-tab buttons.
BTN_PAID = "دنگمو دادم"
BTN_PAID_CONFIRM = "تایید میکنم دنگمو دادم"
BTN_MANUAL_CONFIRM = "✅ تایید"
BTN_EXPIRED = "⏰ غیرفعال"
