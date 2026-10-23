
import json
import os
import re
import html
import secrets
import string
import urllib.request
from pathlib import Path
from html.parser import HTMLParser

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# =========================
# НАСТРОЙКИ
# =========================


import json
import os
import re
import html
import secrets
import string
import urllib.request
from pathlib import Path
from html.parser import HTMLParser

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# =========================
# НАСТРОЙКИ
# =========================

OWNER_ID = 7960334158
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
FEED_URL = "https://happymonday.ua/jobs-feed.json?per_page=100"

DATA_FILE = Path("bot_data.json")
FREE_SEARCHES = 3
BONUS_SEARCHES = 10
RESULTS_LIMIT = 5


# =========================
# ДАННЫЕ
# =========================

def load_data():
    if DATA_FILE.exists():
        try:
            with DATA_FILE.open("r", encoding="utf-8") as f:
                result = json.load(f)
                if isinstance(result, dict):
                    result.setdefault("users", {})
                    result.setdefault("promos", {})
                    return result
        except (OSError, json.JSONDecodeError):
            pass
    return {"users": {}, "promos": {}}


data = load_data()


def save_data():
    temporary = DATA_FILE.with_suffix(".tmp")
    with temporary.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    temporary.replace(DATA_FILE)


def is_owner(user_id):
    return int(user_id) == OWNER_ID


def get_user(user_id):
    key = str(user_id)
    if key not in data["users"]:
        data["users"][key] = {"requests": 0, "bonus": 0}
        save_data()
    return data["users"][key]


def can_search(user_id):
    # Владелец всегда может искать без ограничений.
    if is_owner(user_id):
        return True

    user = get_user(user_id)
    return user["requests"] < FREE_SEARCHES or user["bonus"] > 0


def use_search(user_id):
    # Никогда не списываем поиски у владельца.
    if is_owner(user_id):
        return

    user = get_user(user_id)

    if user["requests"] < FREE_SEARCHES:
        user["requests"] += 1
    elif user["bonus"] > 0:
        user["bonus"] -= 1

    save_data()


# =========================
# ВАКАНСИИ
# =========================

def download_vacancies():
    request = urllib.request.Request(
        FEED_URL,
        headers={"User-Agent": "JobFinderAI/1.0"},
    )

    with urllib.request.urlopen(request, timeout=25) as response:
        payload = json.loads(response.read().decode("utf-8"))

    # Поддерживаем распространённые структуры JSON.
    if isinstance(payload, list):
        jobs = payload
    elif isinstance(payload, dict):
        jobs = None

        for key in ("jobs", "data", "results", "items", "vacancies"):
            value = payload.get(key)
            if isinstance(value, list):
                jobs = value
                break

        if jobs is None:
            jobs = []

    else:
        jobs = []

    return [
        job for job in jobs
        if isinstance(job, dict)
        and (job.get("title") or job.get("name"))
    ]


# =========================
# ТЕКСТ
# =========================

class TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []

    def handle_data(self, text):
        self.parts.append(text)

    def get_text(self):
        return " ".join(self.parts)


def clean_text(value):
    if value is None:
        return ""

    if isinstance(value, list):
        return " ".join(clean_text(item) for item in value)

    if isinstance(value, dict):
        return " ".join(
            clean_text(item) for item in value.values()
        )

    parser = TextExtractor()

    try:
        parser.feed(str(value))
        result = parser.get_text()
    except Exception:
        result = str(value)

    return re.sub(r"\s+", " ", html.unescape(result)).strip()


def get_title(job):
    return clean_text(job.get("title") or job.get("name") or "Вакансия")


def get_description(job):
    return clean_text(
        job.get("description")
        or job.get("content")
        or job.get("excerpt")
        or ""
    )


def get_company(job):
    company = job.get("company") or job.get("employer") or ""
    return clean_text(company)


def get_url(job):
    for key in ("url", "link", "apply_url", "job_url"):
        value = job.get(key)
        if isinstance(value, str) and value.startswith("https://"):
            return value
    return ""


def vacancy_text(job):
    return clean_text(job).lower()


def find_matches(jobs, criteria):
    words = {
        word.lower()
        for word in re.findall(
            r"[^\W_]+", criteria, flags=re.UNICODE
        )
        if len(word) > 1
    }

    if not jobs or not words:
        return []

    scored = []

    for job in jobs:
        title = get_title(job).lower()
        text = vacancy_text(job)

        score = 0
        for word in words:
            if word in text:
                score += 3 if word in title else 1

        if score > 0:
            scored.append((score, job))

    scored.sort(key=lambda item: item[0], reverse=True)
    return [job for score, job in scored[:RESULTS_LIMIT]]


def format_vacancy(job):
    title = get_title(job)
    company = get_company(job)
    description = get_description(job)
    url = get_url(job)

    lines = [f"💼 {title}"]

    if company:
        lines.append(f"🏢 Компания: {company}")

    for key, label in (
        ("cities", "📍 Место"),
        ("location", "📍 Место"),
        ("job_format", "🏠 Формат"),
        ("employment_type", "🕒 Занятость"),
        ("salary", "💰 Зарплата"),
    ):
        value = clean_text(job.get(key))
        if value:
            lines.append(f"{label}: {value}")

    if description:
        lines.extend(["", description[:800]])

    if url:
        lines.extend(["", f"🔗 Подробнее: {url}"])

    return "\n".join(lines)[:4000]


# =========================
# КОМАНДЫ
# =========================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    get_user(user_id)

    if is_owner(user_id):
        message = (
            "👑 Ты администратор JobFinder AI.\n"
            "Для тебя поиск без ограничений."
        )
    else:
        user = get_user(user_id)
        remaining = max(0, FREE_SEARCHES - user["requests"])
        message = (
            f"Бесплатных поисков осталось: {remaining}.\n"
            f"Бонусных поисков: {user['bonus']}."
        )

    await update.message.reply_text(
        "Привет! Я JobFinder AI — бот для поиска вакансий.\n\n"
        "/search — искать вакансии\n"
        "/help — помощь\n"
        "/redeem КОД — активировать промокод\n\n"
        + message
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📌 Команды:\n\n"
        "/start — запуск\n"
        "/search — поиск вакансий\n"
        "/redeem КОД — активировать промокод\n"
        "/help — помощь\n\n"
        "Администратор может создавать промокоды командой /addpromo."
    )


async def search_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    if not can_search(user_id):
        await update.message.reply_text(
            "Ты использовал 3 бесплатных поиска.\n"
            "Подписка и оплата пока не подключены.\n"
            "Если у тебя есть промокод, введи /redeem КОД."
        )
        return

    context.user_data["awaiting_search"] = True
    await update.message.reply_text(
        "🔎 Напиши должность или ключевые слова.\n"
        "Например: Python, дизайнер, маркетолог, удалённая работа."
    )


async def redeem_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    if not context.args:
        await update.message.reply_text("Использование: /redeem КОД")
        return

    code = context.args[0].strip().upper()
    promo = data["promos"].get(code)

    if not promo or promo.get("used"):
        await update.message.reply_text(
            "Промокод недействителен или уже использован."
        )
        return

    promo["used"] = True
    promo["used_by"] = user_id

    user = get_user(user_id)
    user["bonus"] += int(promo.get("searches", BONUS_SEARCHES))
    save_data()

    await update.message.reply_text(
        f"✅ Промокод активирован! Добавлено поисков: "
        f"{promo.get('searches', BONUS_SEARCHES)}."
    )


async def addpromo_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    if not is_owner(user_id):
        await update.message.reply_text("Команда доступна только администратору.")
        return

    if context.args:
        code = context.args[0].strip().upper()
    else:
        alphabet = string.ascii_uppercase + string.digits
        code = "".join(secrets.choice(alphabet) for _ in range(10))

    if not re.fullmatch(r"[A-Z0-9_-]{4,40}", code):
        await update.message.reply_text(
            "Код должен содержать от 4 до 40 латинских букв, цифр, _ или -."
        )
        return

    if code in data["promos"]:
        await update.message.reply_text("Такой код уже существует.")
        return

    data["promos"][code] = {
        "used": False,
        "searches": BONUS_SEARCHES,
    }
    save_data()

    await update.message.reply_text(
        f"🎟 Создан промокод: {code}\n"
        f"Он даёт {BONUS_SEARCHES} дополнительных поисков."
    )


# =========================
# ОБРАБОТКА ПОИСКА
# =========================

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    if not context.user_data.get("awaiting_search"):
        return

    user_id = update.effective_user.id
    criteria = update.message.text.strip()
    context.user_data["awaiting_search"] = False

    if not can_search(user_id):
        await update.message.reply_text(
            "Бесплатные поиски закончились. Используй /redeem КОД."
        )
        return

    status = await update.message.reply_text("⏳ Ищу вакансии...")

    try:
        jobs = download_vacancies()

        if not jobs:
            await status.edit_text(
                "Сайт не вернул вакансии в ожидаемом формате. "
                "Попробуй позже."
            )
            return

        matches = find_matches(jobs, criteria)

        if not matches:
            await status.edit_text(
                f"По запросу «{criteria}» совпадений не найдено. "
                "Попробуй другие ключевые слова."
            )
            return

        use_search(user_id)

        await status.edit_text(f"✅ Найдено вакансий: {len(matches)}")

        for job in matches:
            await update.message.reply_text(format_vacancy(job))

        if not is_owner(user_id):
            user = get_user(user_id)
            remaining = max(0, FREE_SEARCHES - user["requests"])
            await update.message.reply_text(
                f"Бесплатных поисков осталось: {remaining}.\n"
                f"Бонусных поисков: {user['bonus']}."
            )

    except Exception as error:
        print(f"Ошибка поиска: {error}")
        await status.edit_text(
            "Ошибка при загрузке вакансий. Попробуй позже."
        )


# =========================
# ЗАПУСК
# =========================

def main():
    if not BOT_TOKEN:
        raise RuntimeError(
            "Не найден BOT_TOKEN в секретах GitHub Actions."
        )

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("search", search_command))
    app.add_handler(CommandHandler("redeem", redeem_command))
    app.add_handler(CommandHandler("addpromo", addpromo_command))

    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)
    )

    print(f"JobFinder AI запущен. ID владельца: {OWNER_ID}")
    app.run_polling()


if __name__ == "__main__":
    main()

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
FEED_URL = "https://happymonday.ua/jobs-feed.json?per_page=100"

DATA_FILE = Path("bot_data.json")
FREE_SEARCHES = 3
BONUS_SEARCHES = 10
RESULTS_LIMIT = 5


# =========================
# ДАННЫЕ
# =========================

def load_data():
    if DATA_FILE.exists():
        try:
            with DATA_FILE.open("r", encoding="utf-8") as f:
                result = json.load(f)
                if isinstance(result, dict):
                    result.setdefault("users", {})
                    result.setdefault("promos", {})
                    return result
        except (OSError, json.JSONDecodeError):
            pass
    return {"users": {}, "promos": {}}


data = load_data()


def save_data():
    temporary = DATA_FILE.with_suffix(".tmp")
    with temporary.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    temporary.replace(DATA_FILE)


def is_owner(user_id):
    return int(user_id) == OWNER_ID


def get_user(user_id):
    key = str(user_id)
    if key not in data["users"]:
        data["users"][key] = {"requests": 0, "bonus": 0}
        save_data()
    return data["users"][key]


def can_search(user_id):
    # Владелец всегда может искать без ограничений.
    if is_owner(user_id):
        return True

    user = get_user(user_id)
    return user["requests"] < FREE_SEARCHES or user["bonus"] > 0


def use_search(user_id):
    # Никогда не списываем поиски у владельца.
    if is_owner(user_id):
        return

    user = get_user(user_id)

    if user["requests"] < FREE_SEARCHES:
        user["requests"] += 1
    elif user["bonus"] > 0:
        user["bonus"] -= 1

    save_data()


# =========================
# ВАКАНСИИ
# =========================

def download_vacancies():
    request = urllib.request.Request(
        FEED_URL,
        headers={"User-Agent": "JobFinderAI/1.0"},
    )

    with urllib.request.urlopen(request, timeout=25) as response:
        payload = json.loads(response.read().decode("utf-8"))

    # Поддерживаем распространённые структуры JSON.
    if isinstance(payload, list):
        jobs = payload
    elif isinstance(payload, dict):
        jobs = None

        for key in ("jobs", "data", "results", "items", "vacancies"):
            value = payload.get(key)
            if isinstance(value, list):
                jobs = value
                break

        if jobs is None:
            jobs = []

    else:
        jobs = []

    return [
        job for job in jobs
        if isinstance(job, dict)
        and (job.get("title") or job.get("name"))
    ]


# =========================
# ТЕКСТ
# =========================

class TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []

    def handle_data(self, text):
        self.parts.append(text)

    def get_text(self):
        return " ".join(self.parts)


def clean_text(value):
    if value is None:
        return ""

    if isinstance(value, list):
        return " ".join(clean_text(item) for item in value)

    if isinstance(value, dict):
        return " ".join(
            clean_text(item) for item in value.values()
        )

    parser = TextExtractor()

    try:
        parser.feed(str(value))
        result = parser.get_text()
    except Exception:
        result = str(value)

    return re.sub(r"\s+", " ", html.unescape(result)).strip()


def get_title(job):
    return clean_text(job.get("title") or job.get("name") or "Вакансия")


def get_description(job):
    return clean_text(
        job.get("description")
        or job.get("content")
        or job.get("excerpt")
        or ""
    )


def get_company(job):
    company = job.get("company") or job.get("employer") or ""
    return clean_text(company)


def get_url(job):
    for key in ("url", "link", "apply_url", "job_url"):
        value = job.get(key)
        if isinstance(value, str) and value.startswith("https://"):
            return value
    return ""


def vacancy_text(job):
    return clean_text(job).lower()


def find_matches(jobs, criteria):
    words = {
        word.lower()
        for word in re.findall(
            r"[^\W_]+", criteria, flags=re.UNICODE
        )
        if len(word) > 1
    }

    if not jobs or not words:
        return []

    scored = []

    for job in jobs:
        title = get_title(job).lower()
        text = vacancy_text(job)

        score = 0
        for word in words:
            if word in text:
                score += 3 if word in title else 1

        if score > 0:
            scored.append((score, job))

    scored.sort(key=lambda item: item[0], reverse=True)
    return [job for score, job in scored[:RESULTS_LIMIT]]


def format_vacancy(job):
    title = get_title(job)
    company = get_company(job)
    description = get_description(job)
    url = get_url(job)

    lines = [f"💼 {title}"]

    if company:
        lines.append(f"🏢 Компания: {company}")

    for key, label in (
        ("cities", "📍 Место"),
        ("location", "📍 Место"),
        ("job_format", "🏠 Формат"),
        ("employment_type", "🕒 Занятость"),
        ("salary", "💰 Зарплата"),
    ):
        value = clean_text(job.get(key))
        if value:
            lines.append(f"{label}: {value}")

    if description:
        lines.extend(["", description[:800]])

    if url:
        lines.extend(["", f"🔗 Подробнее: {url}"])

    return "\n".join(lines)[:4000]


# =========================
# КОМАНДЫ
# =========================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    get_user(user_id)

    if is_owner(user_id):
        message = (
            "👑 Ты администратор JobFinder AI.\n"
            "Для тебя поиск без ограничений."
        )
    else:
        user = get_user(user_id)
        remaining = max(0, FREE_SEARCHES - user["requests"])
        message = (
            f"Бесплатных поисков осталось: {remaining}.\n"
            f"Бонусных поисков: {user['bonus']}."
        )

    await update.message.reply_text(
        "Привет! Я JobFinder AI — бот для поиска вакансий.\n\n"
        "/search — искать вакансии\n"
        "/help — помощь\n"
        "/redeem КОД — активировать промокод\n\n"
        + message
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📌 Команды:\n\n"
        "/start — запуск\n"
        "/search — поиск вакансий\n"
        "/redeem КОД — активировать промокод\n"
        "/help — помощь\n\n"
        "Администратор может создавать промокоды командой /addpromo."
    )


async def search_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    if not can_search(user_id):
        await update.message.reply_text(
            "Ты использовал 3 бесплатных поиска.\n"
            "Подписка и оплата пока не подключены.\n"
            "Если у тебя есть промокод, введи /redeem КОД."
        )
        return

    context.user_data["awaiting_search"] = True
    await update.message.reply_text(
        "🔎 Напиши должность или ключевые слова.\n"
        "Например: Python, дизайнер, маркетолог, удалённая работа."
    )


async def redeem_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    if not context.args:
        await update.message.reply_text("Использование: /redeem КОД")
        return

    code = context.args[0].strip().upper()
    promo = data["promos"].get(code)

    if not promo or promo.get("used"):
        await update.message.reply_text(
            "Промокод недействителен или уже использован."
        )
        return

    promo["used"] = True
    promo["used_by"] = user_id

    user = get_user(user_id)
    user["bonus"] += int(promo.get("searches", BONUS_SEARCHES))
    save_data()

    await update.message.reply_text(
        f"✅ Промокод активирован! Добавлено поисков: "
        f"{promo.get('searches', BONUS_SEARCHES)}."
    )


async def addpromo_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    if not is_owner(user_id):
        await update.message.reply_text("Команда доступна только администратору.")
        return

    if context.args:
        code = context.args[0].strip().upper()
    else:
        alphabet = string.ascii_uppercase + string.digits
        code = "".join(secrets.choice(alphabet) for _ in range(10))

    if not re.fullmatch(r"[A-Z0-9_-]{4,40}", code):
        await update.message.reply_text(
            "Код должен содержать от 4 до 40 латинских букв, цифр, _ или -."
        )
        return

    if code in data["promos"]:
        await update.message.reply_text("Такой код уже существует.")
        return

    data["promos"][code] = {
        "used": False,
        "searches": BONUS_SEARCHES,
    }
    save_data()

    await update.message.reply_text(
        f"🎟 Создан промокод: {code}\n"
        f"Он даёт {BONUS_SEARCHES} дополнительных поисков."
    )


# =========================
# ОБРАБОТКА ПОИСКА
# =========================

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    if not context.user_data.get("awaiting_search"):
        return

    user_id = update.effective_user.id
    criteria = update.message.text.strip()
    context.user_data["awaiting_search"] = False

    if not can_search(user_id):
        await update.message.reply_text(
            "Бесплатные поиски закончились. Используй /redeem КОД."
        )
        return

    status = await update.message.reply_text("⏳ Ищу вакансии...")

    try:
        jobs = download_vacancies()

        if not jobs:
            await status.edit_text(
                "Сайт не вернул вакансии в ожидаемом формате. "
                "Попробуй позже."
            )
            return

        matches = find_matches(jobs, criteria)

        if not matches:
            await status.edit_text(
                f"По запросу «{criteria}» совпадений не найдено. "
                "Попробуй другие ключевые слова."
            )
            return

        use_search(user_id)

        await status.edit_text(f"✅ Найдено вакансий: {len(matches)}")

        for job in matches:
            await update.message.reply_text(format_vacancy(job))

        if not is_owner(user_id):
            user = get_user(user_id)
            remaining = max(0, FREE_SEARCHES - user["requests"])
            await update.message.reply_text(
                f"Бесплатных поисков осталось: {remaining}.\n"
                f"Бонусных поисков: {user['bonus']}."
            )

    except Exception as error:
        print(f"Ошибка поиска: {error}")
        await status.edit_text(
            "Ошибка при загрузке вакансий. Попробуй позже."
        )


# =========================
# ЗАПУСК
# =========================

def main():
    if not BOT_TOKEN:
        raise RuntimeError(
            "Не найден BOT_TOKEN в секретах GitHub Actions."
        )

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("search", search_command))
    app.add_handler(CommandHandler("redeem", redeem_command))
    app.add_handler(CommandHandler("addpromo", addpromo_command))

    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)
    )

    print(f"JobFinder AI запущен. ID владельца: {OWNER_ID}")
    app.run_polling()


if __name__ == "__main__":
    main()
