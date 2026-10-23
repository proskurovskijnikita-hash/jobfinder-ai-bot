
import os
import json
import re
import html
import logging
import asyncio
import urllib.request

from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

FEED_URL = "https://happymonday.ua/jobs-feed.json?per_page=100"
OWNER_ID = 7960334158
users = {}
waiting_for_criteria = set()

MENU = ReplyKeyboardMarkup(
    [
        ["🔎 Найти работу"],
        ["📝 Мои критерии", "ℹ️ Помощь"],
    ],
    resize_keyboard=True,
)


def download_vacancies():
    request = urllib.request.Request(
        FEED_URL,
        headers={"User-Agent": "JobFinderAI/1.0"},
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        data = json.loads(response.read().decode("utf-8"))

    if isinstance(data, list):
        items = data
    elif isinstance(data, dict):
        items = None
        for key in ("jobs", "results", "items", "vacancies"):
            if isinstance(data.get(key), list):
                items = data[key]
                break

        if items is None and isinstance(data.get("data"), list):
            items = data["data"]
        elif items is None and isinstance(data.get("data"), dict):
            nested = data["data"]
            for key in ("jobs", "results", "items", "vacancies"):
                if isinstance(nested.get(key), list):
                    items = nested[key]
                    break

        if items is None:
            items = [data] if data.get("title") else []
    else:
        items = []

    return [
        item for item in items
        if isinstance(item, dict) and item.get("title")
    ]


def clean_text(value):
    if isinstance(value, list):
        value = " ".join(
            str(x.get("name", "")) if isinstance(x, dict) else str(x)
            for x in value
        )
    elif isinstance(value, dict):
        value = " ".join(str(x) for x in value.values())

    value = re.sub(r"<[^>]*>", " ", str(value or ""))
    return html.unescape(value).strip()


def vacancy_text(job):
    fields = [
        job.get("title", ""),
        job.get("description", ""),
        job.get("cities", ""),
        job.get("city", ""),
        job.get("salary", ""),
        job.get("company", ""),
        job.get("employment_type", ""),
    ]
    return " ".join(clean_text(x) for x in fields).lower()


def find_matches(jobs, criteria):
    words = [
        word.lower()
        for word in re.findall(r"[^\W_]+", criteria, flags=re.UNICODE)
        if len(word) > 2
    ]

    if not words:
        return jobs[:5]

    scored = []
    for job in jobs:
        text = vacancy_text(job)
        score = sum(1 for word in words if word in text)
        if score:
            scored.append((score, job))

    scored.sort(key=lambda item: item[0], reverse=True)
    return [job for _, job in scored[:5]]


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    users.setdefault(user_id, {"requests": 0, "criteria": ""})

    await update.message.reply_text(
        "Привет! Я JobFinder AI 🤖\n\n"
        "Помогу найти вакансии с Happy Monday.\n"
        "У тебя есть 3 бесплатных поиска.\n\n"
        "Нажми «🔎 Найти работу» и напиши должность, "
        "город или ключевые слова.",
        reply_markup=MENU,
    )


async def search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = users.setdefault(
        user_id, {"requests": 0, "criteria": ""}
    )

    if user["requests"] >= 3:
        await update.message.reply_text(
            "Ты использовал 3 бесплатных поиска. "
            "Подписка и оплата пока ещё не подключены.",
            reply_markup=MENU,
        )
        return

    waiting_for_criteria.add(user_id)
    await update.message.reply_text(
        "Напиши, какую работу ищешь.\n\n"
        "Например: Python junior, Киев\n"
        "или: маркетолог, удалённо\n"
        "или: дизайнер без опыта.",
        reply_markup=MENU,
    )


async def help_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
    await update.message.reply_text(
        "Как пользоваться JobFinder AI:\n\n"
        "1. Нажми «🔎 Найти работу».\n"
        "2. Напиши должность, город или навыки.\n"
        "3. Получи подходящие вакансии и ссылки.\n\n"
        "Доступно 3 бесплатных поиска.",
        reply_markup=MENU,
    )


async def handle_message(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
    user_id = update.effective_user.id
    message = update.message.text or ""

    if message == "🔎 Найти работу":
        await search(update, context)
        return

    if message == "📝 Мои критерии":
        user = users.get(user_id, {})
        criteria = user.get("criteria", "")
        await update.message.reply_text(
            f"Твои последние критерии: {criteria or 'пока не указаны'}",
            reply_markup=MENU,
        )
        return

    if message == "ℹ️ Помощь":
        await help_command(update, context)
        return

    if user_id not in waiting_for_criteria:
        await update.message.reply_text(
            "Чтобы искать вакансии, нажми «🔎 Найти работу».",
            reply_markup=MENU,
        )
        return

    user = users.setdefault(
        user_id, {"requests": 0, "criteria": ""}
    )
    waiting_for_criteria.discard(user_id)

    if user["requests"] >= 3:
        await update.message.reply_text(
            "Бесплатные поиски закончились. "
            "Подписка и оплата пока не подключены.",
            reply_markup=MENU,
        )
        return

    user["requests"] += 1
    user["criteria"] = message

    await update.message.reply_text("🔎 Ищу подходящие вакансии...")

    try:
        jobs = await asyncio.to_thread(download_vacancies)
        matches = find_matches(jobs, message)

        if not matches:
            await update.message.reply_text(
                "По этим критериям вакансии не найдены. "
                "Попробуй другие слова или укажи другую должность.",
                reply_markup=MENU,
            )
            return

        for job in matches:
            title = clean_text(job.get("title", "Вакансия"))
            company = clean_text(job.get("company", ""))
            city = clean_text(
                job.get("cities", job.get("city", ""))
            )
            salary = clean_text(job.get("salary", ""))
            description = clean_text(job.get("description", ""))
            url = clean_text(job.get("url", job.get("link", "")))

            parts = [f"💼 {title}"]
            if company:
                parts.append(f"🏢 {company}")
            if city:
                parts.append(f"📍 {city}")
            if salary:
                parts.append(f"💰 {salary}")
            if description:
                parts.append(f"\n{description[:500]}")
            if url.startswith("https://") or url.startswith("http://"):
                parts.append(f"\n🔗 {url}")

            await update.message.reply_text(
                "\n".join(parts),
                reply_markup=MENU,
                disable_web_page_preview=True,
            )

        remaining = 3 - user["requests"]
        await update.message.reply_text(
            f"Готово! Осталось бесплатных поисков: {remaining}.",
            reply_markup=MENU,
        )

    except Exception:
        logger.exception("Ошибка при поиске вакансий")
        await update.message.reply_text(
            "Не получилось загрузить вакансии с Happy Monday. "
            "Попробуй ещё раз немного позже.",
            reply_markup=MENU,
        )


def main():
    token = os.getenv("BOT_TOKEN")
    if not token:
        raise RuntimeError(
            "Не задан BOT_TOKEN в секретах GitHub."
        )

    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("search", search))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            handle_message,
        )
    )

    print("JobFinder AI запускается...", flush=True)
    app.run_polling()


if __name__ == "__main__":
    main()
