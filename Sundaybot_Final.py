import requests
import datetime
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Bot, Update
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler,
    MessageHandler, ContextTypes, filters
)
from apscheduler.schedulers.background import BackgroundScheduler

# === 🔐 BOT TOKEN
BOT_TOKEN = '7651692145:AAGmvAfhjqJ_bhKOyTM-KN3EDGlGaqLOY6E'

# === 🌐 GOOGLE APPS SCRIPT WEB APP URL
WEBHOOK_URL = 'https://script.google.com/macros/s/AKfycbwR2zO90VW6LIQr8BO3Aray8VXXoKgotu90n_HVZ4yUvmLO2ZZB-6pN85yw-U8WMvIz/exec'

# === 👤 PER-USER GROUP ASSIGNMENTS
USER_GROUPS = {
    503493798: "FAMILY",          # D Fatima
    222222222: "CAREER MALES",    # D Jabs
    333333333: "CAREER FEMALES",  # D Rue
    444444444: "CAMPUS FEMALES",  # Divine
    555555555: "JS FEMALES",      # M Cor
    515714808: "MEMBERS ABROAD",  # M Jervene
    444444444: "ACTIVE NC",       # M Jervene
    444444444: "Visitors",        # M Jervene
    444444444: "OTHER MEMBERS"    # M Jervene
}

# === 👥 GROUP MEMBER LISTS
MEMBER_LISTS = {
    "FAMILY": ["M Jervene", "Dcn Issa", "Dcn Ian", "Shayne", "Jessie", "Vangie", "Almen", "Dcns Frances", "Dcn Probo", "M Ruby"],
    "CAREER MALES": ["Alexander", "Daniel Ezekiel", "Franz", "Jiboy", "Venancio"],
    "CAREER FEMALES": ["Aliza", "Andrea", "Angel", "Anica", "Clarice", "Daryl Mitzi", "Grace", "Dr Kristine", "Joannes", "Lavinia", "Melanie", "Mia", "M Sarah", "Shaja", "Trina", "Zhandra"],
    "CAMPUS FEMALES": ["Marinell"],
    "JS FEMALES": ["Tita Merlita", "Grace", "Emeru"],
    "MEMBERS ABROAD": ["*Riza", "*Saeyeong", "*Grace", "*Vicky", "*Mirasol", "*Donna", "*Wendy", "*Iven"],
    "ACTIVE NC": ["Hannah", "Fernan", "Renata"],
    "Visitors": ["Randrew Dela Cruz", "John Carlo Lucero"],
    "OTHER MEMBERS": ["PP Gene Ann", "Cherry Ann", "Rhea Cho", "Gemma", "Yolly", "Weng", "Taiki Okubo"]
}

user_sessions = {}

# === ✅ /start handler
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id

    group_name = USER_GROUPS.get(user_id)
    if not group_name:
        await update.message.reply_text("❌ You are not assigned to a group.")
        return

    context.bot_data.setdefault("user_chats", {})[user_id] = chat_id
    await send_attendance_prompt(user_id, context.bot, context, custom_text="Who did you miss this Predawn?")

# === ✅ Attendance prompt
async def send_attendance_prompt(user_id, bot: Bot, context=None, custom_text="Who did you miss this Predawn?"):
    group_name = USER_GROUPS.get(user_id)
    members = MEMBER_LISTS.get(group_name, [])

    if not members:
        await bot.send_message(chat_id=context.bot_data["user_chats"].get(user_id),
                               text="No members found for your group.")
        return

    # 🧠 Extract label
    if custom_text.startswith("Who did you miss this "):
        label = custom_text.replace("Who did you miss this ", "").replace("?", "").strip()
    else:
        label = "Predawn"

    if context:
        context.bot_data.setdefault("context_by_user", {})[user_id] = label

    session = {
        "group_tab": group_name,
        "members": members.copy(),
        "selected": [],
        "reasons": {}
    }
    user_sessions[user_id] = session

    keyboard = [[InlineKeyboardButton(name, callback_data=name)] for name in members]
    keyboard.append([InlineKeyboardButton("✅ ALL ACCOUNTED", callback_data="ALL ACCOUNTED")])

    await bot.send_message(
        chat_id=context.bot_data["user_chats"].get(user_id),
        text=custom_text,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# === ✅ Button handler
async def handle_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    session = user_sessions.get(user_id)
    if not session:
        await query.edit_message_text("Session expired. Please send /start again.")
        return

    selected = query.data

    if selected == "ALL ACCOUNTED":
        date_today = datetime.datetime.now().strftime("%Y-%m-%d")
        label = context.bot_data.get("context_by_user", {}).get(user_id, "Predawn")

        data = {
            "group": session["group_tab"],
            "date": date_today,
            "label": label,
            "absentees": [
                {"name": name, "reason": session["reasons"].get(name, "")}
                for name in session["selected"]
            ]
        }

        try:
            response = requests.post(WEBHOOK_URL, json=data)
            await query.edit_message_text(
                f"✅ Attempted submission.\nStatus: {response.status_code}\nResponse: {response.text}"
            )
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

# === ✅ Reason input handler
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

        await update.message.reply_text(
            "Who else did you miss?",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    else:
        await update.message.reply_text("✅ Everyone accounted for. You may now submit.")

# === ✅ Broadcasts
def broadcast_with_label(bot, label, context):
    for user_id, group_name in USER_GROUPS.items():
        chat_id = context.bot_data["user_chats"].get(user_id)
        if chat_id:
            application.create_task(
                send_attendance_prompt(user_id, bot, context, custom_text=f"Who did you miss this {label}?")
            )

def schedule_weekly_broadcast(application):
    scheduler = BackgroundScheduler(timezone="Asia/Manila")

    scheduler.add_job(
        lambda: broadcast_with_label(application.bot, "Predawn", application.bot_data),
        'cron', day_of_week='mon,tue,wed,thu,fri,sat', hour=6, minute=0
    )
    scheduler.add_job(
        lambda: broadcast_with_label(application.bot, "Wednesday", application.bot_data),
        'cron', day_of_week='wed', hour=21, minute=0
    )
    scheduler.add_job(
        lambda: broadcast_with_label(application.bot, "Sunday", application.bot_data),
        'cron', day_of_week='sun', hour=13, minute=0
    )

    scheduler.start()

# === ✅ Launch bot
application = ApplicationBuilder().token(BOT_TOKEN).build()
application.add_handler(CommandHandler("start", start))
application.add_handler(CallbackQueryHandler(handle_button))
application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_reason))

schedule_weekly_broadcast(application)
print("✅ Bot is now running. Waiting for messages...")
application.run_polling()
