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

# === 🔐 BOT TOKEN (⚠️ Replace after testing)
BOT_TOKEN = '7651692145:AAGmvAfhjqJ_bhKOyTM-KN3EDGlGaqLOY6E'

# === 🌐 GOOGLE APPS SCRIPT WEB APP URL
WEBHOOK_URL = 'https://script.google.com/macros/s/AKfycbwR2zO90VW6LIQr8BO3Aray8VXXoKgotu90n_HVZ4yUvmLO2ZZB-6pN85yw-U8WMvIz/exec'

# === 👥 Group Assignments
USER_GROUPS = {
    503493798: "FAMILY",
    222222222: "CAREER MALES",
    333333333: "CAREER FEMALES",
    444444444: "CAMPUS FEMALES",
    555555555: "JS FEMALES",
    515714808: "MEMBERS ABROAD",
}

# === ⛑️ Failover chain
FAILOVER_CHAIN = {
    "FAMILY": [503493798, 515714808],
    "CAREER MALES": [222222222, 515714808],
    "CAREER FEMALES": [333333333, 515714808],
    "CAMPUS FEMALES": [444444444, 515714808],
    "JS FEMALES": [555555555, 515714808],
    "MEMBERS ABROAD": [515714808],
    "ACTIVE NC": [444444444, 515714808],
    "Visitors": [444444444, 515714808],
    "OTHER MEMBERS": [444444444, 515714808]
}

# === 👤 Members
MEMBER_LISTS = {
    "FAMILY": ["M Jervene", "Dcn Issa", "Shayne"],
    "CAREER MALES": ["Alexander", "Jiboy"],
    "CAREER FEMALES": ["Aliza", "Angel"],
    "CAMPUS FEMALES": ["Marinell"],
    "JS FEMALES": ["Tita Merlita", "Grace"],
    "MEMBERS ABROAD": ["*Riza", "*Saeyeong"],
    "ACTIVE NC": ["Hannah", "Fernan"],
    "Visitors": ["Randrew Dela Cruz"],
    "OTHER MEMBERS": ["PP Gene Ann"]
}

user_sessions = {}
scheduler = AsyncIOScheduler(timezone="Asia/Manila")

# === ✅ Start command
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    group = USER_GROUPS.get(user_id)
    if not group:
        await update.message.reply_text("❌ You are not assigned to a group.")
        return

    context.bot_data.setdefault("user_chats", {})[user_id] = update.effective_chat.id
    await send_attendance_prompt(user_id, context.bot, context)

# === ✅ Send attendance prompt
async def send_attendance_prompt(user_id, bot: Bot, context=None, custom_text="Who did you miss today?"):
    group = USER_GROUPS.get(user_id)
    members = MEMBER_LISTS.get(group, [])
    chat_id = context.bot_data.get("user_chats", {}).get(user_id)

    if not members or not chat_id:
        await bot.send_message(chat_id=chat_id, text="No members found.")
        return

    user_sessions[user_id] = {
        "group_tab": group,
        "members": members.copy(),
        "selected": [],
        "reasons": {},
        "prompt_time": datetime.datetime.now()
    }

    context.bot_data.setdefault("context_by_user", {})[user_id] = custom_text.split("this ")[-1].replace("?", "")

    keyboard = [[InlineKeyboardButton(name, callback_data=name)] for name in members]
    keyboard.append([InlineKeyboardButton("✅ ALL ACCOUNTED", callback_data="ALL ACCOUNTED")])

    await bot.send_message(
        chat_id=chat_id,
        text=custom_text,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

    run_at = datetime.datetime.now() + datetime.timedelta(hours=1)
    scheduler.add_job(
        lambda: asyncio.create_task(
            check_for_response_timeout(user_id, group, bot, context)
        ),
        trigger='date',
        run_date=run_at
    )

# === 🔁 Timeout fallback
async def check_for_response_timeout(user_id, group, bot: Bot, context):
    if user_id in user_sessions:
        chain = FAILOVER_CHAIN.get(group, [])
        if user_id in chain:
            idx = chain.index(user_id)
            if idx + 1 < len(chain):
                next_user = chain[idx + 1]
                chat_id = context.bot_data.get("user_chats", {}).get(next_user)
                if chat_id:
                    await send_attendance_prompt(
                        next_user, bot, context,
                        custom_text=f"{group} checker didn't respond. Please handle attendance."
                    )

# === ✅ Handle button
async def handle_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    session = user_sessions.get(user_id)

    if not session:
        await query.edit_message_text("Session expired. Send /start again.")
        return

    selected = query.data
    if selected == "ALL ACCOUNTED":
        date_today = datetime.datetime.now().strftime("%Y-%m-%d")
        label = context.bot_data.get("context_by_user", {}).get(user_id, "Predawn")

        absentees = [
            {"name": name, "reason": session["reasons"].get(name, "")}
            for name in session["selected"]
        ] if session["selected"] else [{"name": "ALL ACCOUNTED", "reason": ""}]

        data = {
            "group": session["group_tab"],
            "date": date_today,
            "label": label,
            "absentees": absentees
        }

        try:
            response = requests.post(WEBHOOK_URL, json=data)
            if response.ok:
                await query.edit_message_text("✅ Attendance submitted.\n" + response.text)
            else:
                await query.edit_message_text(f"❌ Failed to submit: {response.status_code}")
        except Exception as e:
            await query.edit_message_text(f"❌ Error submitting: {e}")

        user_sessions.pop(user_id, None)
    else:
        session["selected"].append(selected)
        session["members"].remove(selected)
        context.user_data["awaiting_reason"] = selected
        await query.message.reply_text(f"Why did you miss {selected}?")

        keyboard = [[InlineKeyboardButton(name, callback_data=name)] for name in session["members"]]
        keyboard.append([InlineKeyboardButton("✅ ALL ACCOUNTED", callback_data="ALL ACCOUNTED")])
        await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(keyboard))

# === ✅ Handle reason input
async def handle_reason(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    session = user_sessions.get(user_id)
    awaiting = context.user_data.get("awaiting_reason")

    if not awaiting or not session:
        await update.message.reply_text("Please start with /start.")
        return

    reason = update.message.text.strip()
    session["reasons"][awaiting] = reason
    del context.user_data["awaiting_reason"]
    await update.message.reply_text(f"Recorded reason for {awaiting} ✅")

    if session["members"]:
        keyboard = [[InlineKeyboardButton(name, callback_data=name)] for name in session["members"]]
        keyboard.append([InlineKeyboardButton("✅ ALL ACCOUNTED", callback_data="ALL ACCOUNTED")])
        await update.message.reply_text("Who else did you miss?", reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await update.message.reply_text("✅ Everyone accounted for. You may now submit.")

# === 🕖 Weekly scheduler
def broadcast_with_label(bot, label, context):
    for user_id in USER_GROUPS:
        chat_id = context.bot_data.get("user_chats", {}).get(user_id)
        if chat_id:
            asyncio.create_task(send_attendance_prompt(user_id, bot, context, custom_text=label))

def schedule_weekly_broadcast(application):
    scheduler.add_job(lambda: broadcast_with_label(application.bot, "Who did you miss this predawn?", application.bot_data),
                      'cron', day_of_week='mon,tue,wed,thu,fri,sat', hour=6, minute=0)
    scheduler.add_job(lambda: broadcast_with_label(application.bot, "Who did you miss this Wednesday?", application.bot_data),
                      'cron', day_of_week='wed', hour=21, minute=0)
    scheduler.add_job(lambda: broadcast_with_label(application.bot, "Who did you miss this Sunday?", application.bot_data),
                      'cron', day_of_week='sun', hour=13, minute=0)

# === 🚀 Launch bot
async def main():
    application = ApplicationBuilder().token(BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(handle_button))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_reason))

    scheduler.start()
    schedule_weekly_broadcast(application)

    print("🤖 Bot is running...")
    await application.run_polling()

if __name__ == "__main__":
    import asyncio
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())
