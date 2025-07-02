import requests
import datetime
import asyncio
from pytz import timezone
from telegram import (
    InlineKeyboardButton, InlineKeyboardMarkup, Bot, Update
)
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler,
    MessageHandler, ContextTypes, filters
)
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import nest_asyncio

nest_asyncio.apply()

BOT_TOKEN = '7651692145:AAGmvAfhjqJ_bhKOyTM-KN3EDGlGaqLOY6E'
WEBHOOK_URL = 'https://script.google.com/macros/s/AKfycbwR2zO90VW6LIQr8BO3Aray8VXXoKgotu90n_HVZ4yUvmLO2ZZB-6pN85yw-U8WMvIz/exec'

# --- Configurable Data ---

EXCLUSIONS = {
    "Predawn": {
        "CAREER MALES": ["Taiki"],
        "CAREER FEMALES 2": ["Donna", "Vicky"],
        "CAREER FEMALES 3": ["Riza", "Saeyong"],
        "JS FEMALES": ["Randrew Dela Cruz", "John Carlo Lucero", "Cherry Ann", "Rhea Cho", "Gemma", "Yolly", "Weng"]
    },
    "Wednesday": {
        "CAREER MALES": ["Taiki"],
        "CAREER FEMALES 2": ["Donna", "Vicky"],
        "CAREER FEMALES 3": ["Riza"],
        "JS FEMALES": ["Randrew Dela Cruz", "John Carlo Lucero", "Cherry Ann", "Rhea Cho", "Gemma", "Yolly", "Weng"]
    }
}

USER_GROUPS = {
    503493798: "FAMILY FEMALES",
    222222222: "CAREER MALES",
    333333333: "CAREER FEMALES 1",
    777777777: "CAREER FEMALES 2",
    666666666: "CAREER FEMALES 3",
    444444444: "CAMPUS FEMALES",
    555555555: "JS FEMALES",
    515714808: "FAMILY MALES",
}

MEMBER_LISTS = {
    "FAMILY FEMALES": ["Fatima", "Vangie", "Hannah", "M Ru", "Dcn Frances", "Shayne", "Dcn Issa"],
    "FAMILY MALES": ["Dcn Ian", "M Jervene", "Jessie", "Almen", "Dcn Probo", "Mjhay"],
    "CAREER MALES": ["Jabs", "Xander", "Franz", "Daniel", "Jiboy", "Venancio", "Iven", "Taiki"],
    "CAREER FEMALES 1": ["Shaja", "Grace", "Daryl", "Clarice", "Mia", "Aliza", "Anica"],
    "CAREER FEMALES 2": ["Mel", "Andrea", "Angel", "Inia", "M Rose", "Vicky", "Donna"],
    "CAREER FEMALES 3": ["D Rue", "PP Bam", "Zhandra", "Trina", "Dr Kristine", "Riza", "Saeyong", "Mirasol", "Joan"],
    "CAMPUS FEMALES": ["Divine", "Marinell"],
    "JS FEMALES": ["MCor", "Tita Merlita", "Grace", "Emeru", "Randrew Dela Cruz", "John Carlo Lucero", "Cherry Ann", "Rhea Cho", "Gemma", "Yolly", "Weng"],
}

# --- Runtime Data ---

user_sessions = {}
submission_tracker = {}
scheduler = AsyncIOScheduler(timezone="Asia/Manila")

# --- Core Handlers ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("✅ You can start using commands like /predawn, /sunday, or /wednesday.")

async def restart_attendance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id in user_sessions:
        user_sessions.pop(user_id)
        await update.message.reply_text("🔁 Your attendance session has been reset.")
    else:
        await update.message.reply_text("ℹ️ You have no active session.")

async def send_attendance_prompt(user_id, bot: Bot, context, label):
    group = USER_GROUPS.get(user_id)
    members = MEMBER_LISTS.get(group, []).copy()
    excluded = EXCLUSIONS.get(label, {}).get(group, [])
    members = [m for m in members if m not in excluded]

    chat_id = context.bot_data.get("user_chats", {}).get(user_id)
    if not chat_id or not members:
        return

    context.bot_data.setdefault("context_by_user", {})[user_id] = label

    user_sessions[user_id] = {
        "group_tab": group,
        "members": members.copy(),
        "selected": [],
        "reasons": {},
        "visitors": [],
        "newcomers": [],
    }

    keyboard = [[InlineKeyboardButton(name, callback_data=name)] for name in members]
    keyboard.append([
        InlineKeyboardButton("➕ Add Visitor", callback_data="ADD_VISITOR"),
        InlineKeyboardButton("🆕 Add Newcomer", callback_data="ADD_NEWCOMER")
    ])
    keyboard.append([InlineKeyboardButton("✅ ALL ACCOUNTED", callback_data="ALL ACCOUNTED")])

    await bot.send_message(chat_id=chat_id, text=f"Who did you miss this {label}?", reply_markup=InlineKeyboardMarkup(keyboard))

    submission_tracker.setdefault(label, set())
    await update_submission_progress(context, label)

async def update_submission_progress(context, label):
    total = len(USER_GROUPS)
    submitted = len(submission_tracker[label])
    pending = [f"User {uid}" for uid in USER_GROUPS if uid not in submission_tracker[label]]
    message = f"✅ {submitted}/{total} submitted.\nStill waiting for: {', '.join(pending)}"
    group_chat_id = context.bot_data.get("progress_message_chat")
    message_id = context.bot_data.get("progress_message_id")

    if group_chat_id and message_id:
        await context.bot.edit_message_text(chat_id=group_chat_id, message_id=message_id, text=message)

async def handle_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    session = user_sessions.get(user_id)
    if not session:
        await query.edit_message_text("Session expired. Send /restart_attendance.")
        return

    selected = query.data
    if selected == "ALL ACCOUNTED":
        await finalize_attendance_submission(user_id, context, query)
    elif selected == "ADD_VISITOR":
        context.user_data["awaiting_visitor"] = True
        await query.message.reply_text("Type visitor's name:")
    elif selected == "ADD_NEWCOMER":
        context.user_data["awaiting_newcomer"] = True
        await query.message.reply_text("Type newcomer's name:")
    else:
        session["selected"].append(selected)
        session["members"].remove(selected)
        context.user_data["awaiting_reason"] = selected
        await query.message.reply_text(f"Why did you miss {selected}?")

        keyboard = [[InlineKeyboardButton(name, callback_data=name)] for name in session["members"]]
        keyboard.append([
            InlineKeyboardButton("➕ Add Visitor", callback_data="ADD_VISITOR"),
            InlineKeyboardButton("🆕 Add Newcomer", callback_data="ADD_NEWCOMER")
        ])
        keyboard.append([InlineKeyboardButton("✅ ALL ACCOUNTED", callback_data="ALL ACCOUNTED")])
        await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(keyboard))

async def handle_reason(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    session = user_sessions.get(user_id)
    if not session:
        await update.message.reply_text("Please start with /restart_attendance.")
        return

    if context.user_data.get("awaiting_visitor"):
        session["visitors"].append(update.message.text.strip())
        del context.user_data["awaiting_visitor"]
        await update.message.reply_text("✅ Visitor added.")
    elif context.user_data.get("awaiting_newcomer"):
        session["newcomers"].append(update.message.text.strip())
        del context.user_data["awaiting_newcomer"]
        await update.message.reply_text("✅ Newcomer added.")
    elif context.user_data.get("awaiting_reason"):
        name = context.user_data.pop("awaiting_reason")
        session["reasons"][name] = update.message.text.strip()
        await update.message.reply_text(f"Reason recorded for {name} ✅")

    if session["members"]:
        keyboard = [[InlineKeyboardButton(name, callback_data=name)] for name in session["members"]]
        keyboard.append([
            InlineKeyboardButton("➕ Add Visitor", callback_data="ADD_VISITOR"),
            InlineKeyboardButton("🆕 Add Newcomer", callback_data="ADD_NEWCOMER")
        ])
        keyboard.append([InlineKeyboardButton("✅ ALL ACCOUNTED", callback_data="ALL ACCOUNTED")])
        await update.message.reply_text("Who else did you miss?", reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await update.message.reply_text("✅ Everyone accounted. Submit when ready.")

async def finalize_attendance_submission(user_id, context, query):
    session = user_sessions[user_id]
    label = context.bot_data.get("context_by_user", {}).get(user_id, "Predawn")
    data = {
        "group": session["group_tab"],
        "date": datetime.datetime.now().strftime("%Y-%m-%d"),
        "label": label,
        "absentees": [
            {"name": name, "reason": session["reasons"].get(name, "")}
            for name in session["selected"]
        ] + [{"name": f"Visitor - {v}", "reason": "VISITOR"} for v in session["visitors"]] +
            [{"name": f"Newcomer - {n}", "reason": "NEWCOMER"} for n in session["newcomers"]]
        or [{"name": "ALL ACCOUNTED", "reason": ""}]
    }
    try:
        requests.post(WEBHOOK_URL, json=data)
        await query.edit_message_text("✅ Attendance submitted.")
    except Exception as e:
        await query.edit_message_text(f"❌ Error submitting: {e}")

    user_sessions.pop(user_id, None)
    submission_tracker[label].add(user_id)
    await update_submission_progress(context, label)

# --- Command Triggers ---

async def broadcast_attendance(update: Update, context: ContextTypes.DEFAULT_TYPE, label):
    # Start tracking
    submission_tracker[label] = set()

    # Post group progress message
    sent = await update.message.reply_text(f"📢 {label} attendance in progress...")
    context.bot_data["progress_message_chat"] = sent.chat_id
    context.bot_data["progress_message_id"] = sent.message_id

    # Send private prompts
    for user_id in USER_GROUPS:
        context.bot_data.setdefault("user_chats", {})[user_id] = user_id
        await send_attendance_prompt(user_id, context.bot, context, label)

    # Reminders after 30 min
    scheduler.add_job(
        lambda: asyncio.create_task(update_submission_progress(context, label)),
        'date', run_date=datetime.datetime.now() + datetime.timedelta(minutes=30)
    )

async def predawn_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await broadcast_attendance(update, context, "Predawn")

async def sunday_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await broadcast_attendance(update, context, "Sunday")

async def wednesday_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await broadcast_attendance(update, context, "Wednesday")

# --- App Entry Point ---

async def main():
    application = ApplicationBuilder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("restart_attendance", restart_attendance))
    application.add_handler(CommandHandler("predawn", predawn_command))
    application.add_handler(CommandHandler("sunday", sunday_command))
    application.add_handler(CommandHandler("wednesday", wednesday_command))
    application.add_handler(CallbackQueryHandler(handle_button))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_reason))
    scheduler.start()
    print("🤖 Bot is running...")
    await application.run_polling()

if __name__ == "__main__":
    import sys
    if sys.platform.startswith('win'):
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import nest_asyncio
            nest_asyncio.apply()
            loop.create_task(main())
        else:
            loop.run_until_complete(main())
    except RuntimeError:
        asyncio.run(main())

