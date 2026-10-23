
import os
import logging

from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

logging.basicConfig(level=logging.INFO)

users = {}
waiting_for_criteria = set()

MENU = ReplyKeyboardMarkup(
    [
        ["🔎 Найти работу"],
        ["📝 Мои критерии", "ℹ️ Помощь"],
    ],
    resize_keyboard=True,
)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    users.setdefault(user_id, {"requests": 0})

    await update.message.reply_text(
        "👋 Привет! Я JobFinder AI.\n\n"
        "Помогу подобрать работу по твоим критериям:\n"
        "📍 Город или страна\n"
        "💼 Профессия\n"
        "💰 Зарплата\n"
        "🎓 Опыт работы\n"
        "🏠 Удалённо или офис\n\n"
        "🎁 У тебя 3 бесплатных запроса.\n"
        "Нажми «🔎 Найти работу», чтобы начать!",
        reply_markup=MENU,
    )


async def search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = users.setdefault(user_id, {"requests": 0})

    if user["requests"] >= 3:
        await update.message.reply_text(
            "🎁 Бесплатные запросы закончились. "
            "Дополнительные возможности подключим позже.",
            reply_markup=MENU,
        )
        return

    waiting_for_criteria.add(user_id)
    await update.message.reply_text(
        "Напиши, какую работу ищешь.\n\n"
        "Например: оператор чата, Львов, удалённо, "
        "без опыта, зарплата от 20000 грн."
    )


async def help_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
    await update.message.reply_text(
        "ℹ️ Как пользоваться JobFinder AI:\n\n"
        "1. Нажми «🔎 Найти работу».\n"
        "2. Напиши свои критерии.\n"
        "3. Следуй подсказкам бота.",
        reply_markup=MENU,
    )


async def handle_message(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
    user_id = update.effective_user.id
    message = update.message.text

    if message == "🔎 Найти работу":
        await search(update, context)
        return

    if message == "📝 Мои критерии":
        await update.message.reply_text(
            "Нажми «🔎 Найти работу» и укажи свои критерии.",
            reply_markup=MENU,
        )
        return

    if message == "ℹ️ Помощь":
        await help_command(update, context)
        return

    if user_id in waiting_for_criteria:
        user = users.setdefault(user_id, {"requests": 0})
        waiting_for_criteria.discard(user_id)

        if user["requests"] >= 3:
            await update.message.reply_text(
                "Бесплатные запросы закончились.",
                reply_markup=MENU,
            )
            return

        user["requests"] += 1

        await update.message.reply_text(
            f"✅ Критерии приняты:\n\n{message}\n\n"
            f"Использовано запросов: {user['requests']} из 3.\n\n"
            "Реальный поиск вакансий подключим следующим этапом.",
            reply_markup=MENU,
        )
        return

    await update.message.reply_text(
        "Чтобы начать, нажми «🔎 Найти работу».",
        reply_markup=MENU,
    )


def main():
    token = os.environ.get("BOT_TOKEN")

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
