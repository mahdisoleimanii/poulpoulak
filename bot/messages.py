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


# --- Button labels -----------------------------------------------------------

BTN_NONE_OF_ABOVE = "یکی دیگه"
BTN_CANCEL = "بیخیال ❌"
BTN_CHANGE_PAYER = "تغییر پرداخت کننده"
BTN_CHANGE_AMOUNT = "تغییر مبلغ"
BTN_DONE = "✅ تموم"
BTN_CONFIRM_PARTICIPANTS = "✅ ادامه"
SELECTED = "🟢"
UNSELECTED = "🔘"
