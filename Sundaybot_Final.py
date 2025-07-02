import requests
import datetime
import asyncio
from pytz import timezone
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Bot, Update
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler,
    MessageHandler, ContextTypes, filters
)
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import nest_asyncio

nest_asyncio.apply()

BOT_TOKEN = '7651692145:AAGmvAfhjqJ_bhKOyTM-KN3EDGlGaqLOY6E'
WEBHOOK_URL = 'https://script.google.com/macros/s/AKfycbwR2zO90VW6LIQr8BO3Aray8VXXoKgotu90n_HVZ4yUvmLO2ZZB-6pN85yw-U8WMvIz/exec'

EXCLUSIONS = { ... }  # same as before
USER_GROUPS = { ... }  # same as before
MEMBER_LISTS = { ... }  # same as before

user_sessions = {}
scheduler = AsyncIOScheduler(timezone="Asia/Manila")

async def start_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE, label: str):
    user_id = update.effective_user.id
    group = USER_GROUPS.get(user_id)
    if not group:
        await update.message.reply_text("❌ You are not assigned to a group.")
        return
    context.bot_data.setdefault("user_chats", {})[user_id] = update.effective_chat.id
    context.bot_data.setdefault("context_by_user", {})[user_id] = label
    await send_attendance_prompt(user_id, context.bot, context, custom_text=f"Who did you miss this {label}?")

async def predawn(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await start_prompt(update, context, "Predawn")

async def wednesday(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await start_prompt(update, context, "Wednesday")

async def sunday(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await start_prompt(update, context, "Sunday")

# keep the rest of your functions unchanged like:
# - send_attendance_prompt
# - check_for_response_timeout
# - handle_button
# - handle_reason
# - restart_attendance

async def main():
    application = ApplicationBuilder().token(BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("restart_attendance", restart_attendance))
    application.add_handler(CommandHandler("predawn", predawn))
    application.add_handler(CommandHandler("wednesday", wednesday))
    application.add_handler(CommandHandler("sunday", sunday))
    application.add_handler(CallbackQueryHandler(handle_button))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_reason))

    scheduler.start()
    print("🤖 Bot is running...")
    await application.run_polling()

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())
