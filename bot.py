
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
PROMO_SEARCHES = 10
RESULTS_LIMIT = 5


# =========================
# ХРАНЕНИЕ ДАННЫХ
# =========================

def load_data():
    if DATA_FILE.exists():
        try:
            with DATA_FILE.open("r", encoding="utf-8") as file:
                data = json.load(file)
                if isinstance(data, dict):
                    data.setdefault("users", {})
                    data.setdefault("promos", {})
                    return data
        except (OSError, json.JSONDecodeError):
            pass

    return {"users": {}, "promos": {}}


data = load_data()


def save_data():
    temp_file = DATA_FILE.with_suffix(".tmp")
    with temp_file.open("w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=2)
    temp_file.replace(DATA_FILE)


def get_user(user_id):
    key = str(user_id)

    if key not in data["users"]:
        data["users"][key] = {
            "requests": 0,
            "bonus": 0,
        }
        save_data()

    return data["users"][key]


def is_owner(user_id):
    return user_id == OWNER_ID


def can_search(user_id):
    if is_owner(user_id):
        return True

    user = get_user(user_id)
    return user["requests"] < FREE_SEARCHES or user["bonus"] > 0


def use_search(user_id):
    if is_owner(user_id):
        return

    user = get_user(user_id)

    if user["requests"] < FREE_SEARCHES:
        user["requests"] += 1
    elif user["bonus"] > 0:
        user["bonus"] -= 1

    save_data()


# =========================
# ЗАГРУЗКА ВАКАНСИЙ
# =========================

def download_vacancies():
    request = urllib.request.Request(
        FEED_URL,
        headers={"User-Agent": "JobFinderAI/1.0"},
    )

    with urllib.request.urlopen(request, timeout=20) as response:
        payload = json.loads(response.read().decode("utf-8"))

    if isinstance(payload, dict):
        jobs = payload.get("data", [])
    elif isinstance(payload, list):
        jobs = payload
    else:
        jobs = []

    if not isinstance(jobs, list):
        return []

    return [
        job for job in jobs
        if isinstance(job, dict) and job.get("title")
    ]


# =========================
# ОБРАБОТКА ТЕКСТА
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
        return " ".join(clean_text(item) for item in value.values())

    text = str(value)
    parser = TextExtractor()

    try:
        parser.feed(text)
        text = parser.get_text()
    except Exception:
        pass

    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def vacancy_text(job):
    parts = [
        job.get("title", ""),
        job.get("description", ""),
        job.get("company", ""),
        job.get("job_type", []),
        job.get("job_format", []),
        job.get("job_level", []),
        job.get("english_level", []),
        job.get("cities", []),
        job.get("categories", []),
    ]

    return clean_text(parts).lower()


def find_matches(jobs, criteria):
    words = {
        word.lower()
        for word in re.findall(r"[^\W_]+", criteria, flags=re.UNICODE)
        if len(word) > 1
    }

    if not jobs or not words:
        return []

    scored = []

    for job in jobs:
        title = clean_text(job.get("title", "")).lower()
        text = vacancy_text(job)

        score = sum(
            3 if word in title else 1
            for word in words
            if word in text
        )

        if score > 0:
            scored.append((score, job))

    scored.sort(key=lambda item: item[0], reverse=True)
    return [job for _, job in scored[:RESULTS_LIMIT]]


# =========================
# ФОРМАТ ВАКАНСИИ
# =========================

def format_vacancy(job):
    title = clean_text(job.get("title", "Вакансия"))
    company = clean_text(job.get("company", {}))
    cities = clean_text(job.get("cities", []))
    formats = clean_text(job.get("job_format", []))
    job_types = clean_text(job.get("job_type", []))
    levels = clean_text(job.get("job_level", []))
    description = clean_text(job.get("description", ""))
    url = job.get("url", "")

    salary_data = job.get("salary", {})
    salary = ""

    if isinstance(salary_data, dict):
        minimum = salary_data.get("min", "")
        maximum = salary_data.get("max", "")
        currency = salary_data.get("currency", "")

        if minimum and maximum:
            salary = f"{minimum}–{maximum} {currency.upper()}"
        elif minimum:
            salary = f"от {minimum} {currency.upper()}"
        elif maximum:
            salary = f"до {maximum} {currency.upper()}"

    lines = [f"💼 {title}"]

    if company:
        lines.append(f"🏢 Компания: {company}")
    if cities:
        lines.append(f"📍 Место: {cities}")
    if formats:
        lines.append(f"🏠 Формат: {formats}")
    if job_types:
        lines.append(f"🕒 Занятость: {job_types}")
    if levels:
        lines.append(f"📊 Уровень: {levels}")
    if salary:
        lines.append(f"💰 Зарплата: {salary}")

    if description:
        short_description = description[:700]
        if len(description) > 700:
            short_description += "…"
        lines.append("")
        lines.append(short_description)

    if isinstance(url, str) and url.startswith("https://"):
        lines.extend(["", f"🔗 Откликнуться: {url}"])

    return "\n".join(lines)


# =========================
# КОМАНДЫ БОТА
# =========================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    get_user(user_id)

    if is_owner(user_id):
        limit_text = "Для тебя поиск без ограничений."
    else:
        user = get_user(user_id)
        remaining = max(0, FREE_SEARCHES - user["requests"])
        limit_text = (
            f"Бесплатных поисков осталось: {remaining}.\n"
            f"Дополнительные поиски можно получить по промокоду."
        )

    await update.message.reply_text(
        "Привет! Я JobFinder AI — бот для поиска вакансий.\n\n"
        "Напиши /search, чтобы найти работу по ключевым словам.\n"
        "Напиши /help, чтобы увидеть команды.\n\n"
        f"{limit_text}"
    )


async def help_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    await update.message.reply_text(
        "📌 Команды JobFinder AI\n\n"
        "/start — запустить бота\n"
        "/search — поиск вакансий\n"
        "/redeem КОД — активировать промокод\n"
        "/help — помощь\n\n"
        "Введи /search, затем отправь должность или ключевые слова, "
        "например: Python, маркетолог, дизайнер, удалённая работа."
    )


async def search_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    user_id = update.effective_user.id
    get_user(user_id)

    if not can_search(user_id):
        await update.message.reply_text(
            "Бесплатные поиски закончились.\n"
            "Если у тебя есть промокод, введи /redeem КОД."
        )
        return

    context.user_data["awaiting_search"] = True

    await update.message.reply_text(
        "🔎 Напиши должность или ключевые слова для поиска.\n"
        "Например: Python, дизайнер, маркетолог, удалённая работа."
    )


async def redeem_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    user_id = update.effective_user.id

    if not context.args:
        await update.message.reply_text(
            "Использование: /redeem ТВОЙ_КОД"
        )
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
    user["bonus"] += int(promo.get("searches", PROMO_SEARCHES))

    save_data()

    await update.message.reply_text(
        f"✅ Промокод активирован!\n"
        f"Добавлено поисков: {promo.get('searches', PROMO_SEARCHES)}."
    )


async def addpromo_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    user_id = update.effective_user.id

    if not is_owner(user_id):
        await update.message.reply_text("Эта команда доступна только владельцу.")
        return

    if context.args:
        code = context.args[0].strip().upper()
    else:
        alphabet = string.ascii_uppercase + string.digits
        code = "".join(secrets.choice(alphabet) for _ in range(10))

    if not re.fullmatch(r"[A-Z0-9_-]{4,40}", code):
        await update.message.reply_text(
            "Код должен содержать от 4 до 40 символов: "
            "латинские буквы, цифры, _ или -."
        )
        return

    if code in data["promos"]:
        await update.message.reply_text("Такой промокод уже существует.")
        return

    data["promos"][code] = {
        "used": False,
        "searches": PROMO_SEARCHES,
    }
    save_data()

    await update.message.reply_text(
        f"🎟 Промокод создан: {code}\n"
        f"Он даёт {PROMO_SEARCHES} дополнительных поисков.\n"
        "Передай код пользователю после подтверждения оплаты."
    )


# =========================
# ПОИСК ПО СООБЩЕНИЮ
# =========================

async def handle_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    if not update.message or not update.message.text:
        return

    if not context.user_data.get("awaiting_search"):
        return

    user_id = update.effective_user.id
    criteria = update.message.text.strip()

    if not criteria:
        await update.message.reply_text("Введи ключевые слова для поиска.")
        return

    if not can_search(user_id):
        context.user_data["awaiting_search"] = False
        await update.message.reply_text(
            "Бесплатные поиски закончились. Используй /redeem КОД."
        )
        return

    context.user_data["awaiting_search"] = False

    status_message = await update.message.reply_text(
        "⏳ Ищу вакансии. Подожди немного..."
    )

    try:
        jobs = download_vacancies()
        matches = find_matches(jobs, criteria)

        if not jobs:
            await status_message.edit_text(
                "Не удалось получить вакансии с сайта. Попробуй позже."
            )
            return

        use_search(user_id)

        if not matches:
            await status_message.edit_text(
                f"По запросу «{criteria}» совпадений не найдено.\n"
                "Попробуй другую должность или ключевые слова."
            )
            return

        await status_message.edit_text(
            f"✅ Найдено вакансий: {len(matches)}\n"
            f"Запрос: {criteria}"
        )

        for job in matches:
            text = format_vacancy(job)

            if len(text) > 4000:
                text = text[:3990] + "…"

            await update.message.reply_text(text)

        if not is_owner(user_id):
            user = get_user(user_id)
            remaining = max(0, FREE_SEARCHES - user["requests"])
            await update.message.reply_text(
                f"Бесплатных поисков осталось: {remaining}.\n"
                f"Бонусных поисков: {user['bonus']}."
            )

    except Exception:
        await status_message.edit_text(
            "Произошла ошибка при поиске вакансий. Попробуй позже."
        )


# =========================
# ЗАПУСК
# =========================

def main():
    if not BOT_TOKEN:
        raise RuntimeError(
            "Не найден BOT_TOKEN. Добавь его в Secrets GitHub Actions."
        )

    application = Application.builder().token(BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("search", search_command))
    application.add_handler(CommandHandler("redeem", redeem_command))
    application.add_handler(CommandHandler("addpromo", addpromo_command))

    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            handle_message,
        )
    )

    print("JobFinder AI запущен.")
    application.run_polling()


if __name__ == "__main__":
    main()
