import requests
import datetime
import asyncio
import re
import json
import os
from pytz import timezone
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Bot, Update
from telegram.constants import ParseMode
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler,
    MessageHandler, ContextTypes, filters
)
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import nest_asyncio

nest_asyncio.apply()

BOT_TOKEN = '7651692145:AAGmvAfhjqJ_bhKOyTM-KN3EDGlGaqLOY6E'
WEBHOOK_URL = 'https://script.google.com/macros/s/AKfycbwR2zO90VW6LIQr8BO3Aray8VXXoKgotu90n_HVZ4yUvmLO2ZZB-6pN85yw-U8WMvIz/exec'

# === Persistent Storage ===
USER_CHATS_FILE = "user_chats.json"

def load_user_chats():
    if os.path.exists(USER_CHATS_FILE):
        with open(USER_CHATS_FILE, "r") as f:
            return {int(k): v for k, v in json.load(f).items()}
    return {}

def save_user_chats(data):
    with open(USER_CHATS_FILE, "w") as f:
        json.dump(data, f)

# === Static Config ===
USER_GROUPS = {
    503493798: "FAMILY FEMALES",
    222222222: "CAREER MALES",
    707729145: "CAREER FEMALES 1",
    777777777: "CAREER FEMALES 2",
    666666666: "CAREER FEMALES 3",
    444444444: "CAMPUS FEMALES",
    544095264: "JS",
    888888888: "FAMILY MALES",
    515714808: "Visitors",
    000000000: "HQ"
}

USER_NAMES = {
    503493798: "Fatima",
    222222222: "Jabs",
    707729145: "Shaja",
    777777777: "Mel",
    7681981308: "D Rue",
    2016438287: "Divine",
    544095264: "MCor",
    515714808: "Jervene",
}

MEMBER_LISTS = {
    "FAMILY FEMALES": ["Fatima", "Vangie", "M Ru", "Dcn Frances", "Shayne", "Dcn Issa"],
    "FAMILY MALES": ["Dcn Ian", "M Jervene", "Jessie", "Almen", "Dcn Probo", "Mjhay"],
    "CAREER MALES": ["Jabs", "Xander", "Franz", "Daniel", "Jiboy", "Venancio", "Iven"],
    "CAREER FEMALES 1": ["Shaja", "Grace", "Daryl", "Clarice", "Mia", "Aliza", "Anica"],
    "CAREER FEMALES 2": ["Mel", "Andrea", "Angel", "Inia", "M Rose", "Vicky", "Donna"],
    "CAREER FEMALES 3": ["D Rue", "PP Bam", "Zhandra", "Trina", "Dr Kristine"],
    "CAMPUS FEMALES": ["Divine", "Marinell"],
    "JS": ["MCor", "Tita Merlita", "Grace", "Emeru"],
    "Visitors": ["Riza","M Saeyoung","Taiki", "Randrew Dela Cruz", "John Carlo Lucero", "Cherry Ann", "Rhea Cho", "Gemma", "Yolly", "Weng"],
    "HQ": ["PK","M Ju Nara","M Sarah","Mjhay"]
}

EXCLUSIONS = {
    "Predawn": {
            "CAREER FEMALES 2": ["Donna", "Vicky"],
        "Visitors": ["Riza","M Saeyoung","Taiki","Randrew Dela Cruz", "John Carlo Lucero", "Cherry Ann", "Rhea Cho", "Gemma", "Yolly", "Weng"]
    },
    "Wednesday": {
        "CAREER FEMALES 2": ["Donna", "Vicky"],
        "Visitors": ["Riza","M Saeyoung","Taiki","Randrew Dela Cruz", "John Carlo Lucero", "Cherry Ann", "Rhea Cho", "Gemma", "Yolly", "Weng"]
    }
}
user_sessions = {}
scheduler = AsyncIOScheduler(timezone="Asia/Manila")

def escape_markdown(text):
    return re.sub(r'([_\*\[\]()~>#+\-=|{}.!\\])', r'\\\1', text)

async def send_attendance_prompt(user_id, bot: Bot, context, label):
    group = USER_GROUPS[user_id]

    # Skip prompting Visitors for Predawn and Wednesday
    if group == "Visitors" and label in ["Predawn", "Wednesday"]:
        print(f"[SKIP] Skipping Visitors group for {label}")
        return

    members = MEMBER_LISTS[group][:]

    # Apply exclusions (only if not Visitors)
    if group != "Visitors":
        excluded = EXCLUSIONS.get(label, {}).get(group, [])
        members = [m for m in members if m not in excluded]

    # Start session
    user_sessions[user_id] = {
        "group": group,
        "label": label,
        "members": members[:],
        "selected": [],
        "reasons": {},
        "visitors": [],
    }

    chat_id = context.bot_data.get("user_chats", {}).get(user_id)
    if not chat_id:
        print(f"[SKIP] No private chat for user {user_id}")
        return

    # Set prompt text based on group
    if group == "Visitors":
        prompt_text = f"Who attended the {label} service?"
    else:
        prompt_text = f"Who did you miss this {label}?"

    # Construct keyboard
    keyboard = [[InlineKeyboardButton(m, callback_data=m)] for m in members]

    if group == "Visitors":
        keyboard += [[InlineKeyboardButton("🆕 Not Listed", callback_data="NOT_LISTED")]]
    if group != "Visitors":
        keyboard += [[InlineKeyboardButton("➕ Add Newcomer", callback_data="ADD_NEWCOMER")]]

    keyboard += [[InlineKeyboardButton("✅ ALL ACCOUNTED", callback_data="ALL_ACCOUNTED")]]

    # Send message
    await bot.send_message(chat_id, text=prompt_text, reply_markup=InlineKeyboardMarkup(keyboard))


async def handle_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        await update.message.reply_text("❌ Please use /start in a private chat with the bot.")
        return

    user_id = update.effective_user.id
    chat_id = update.effective_chat.id

    context.bot_data.setdefault("user_chats", {})[user_id] = chat_id
    save_user_chats(context.bot_data["user_chats"])

    await update.message.reply_text("✅ You're now registered for attendance prompts.")

async def handle_reason(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    session = user_sessions.get(user_id)

    if not session:
        await update.message.reply_text("Session expired. Send /start again.")
        return

    if context.user_data.get("awaiting_visitor"):
        name = update.message.text.strip()
        session["visitors"].append(f"Visitor - {name}")
        del context.user_data["awaiting_visitor"]
        await update.message.reply_text(f"✅ Added visitor: {name}")
    elif context.user_data.get("awaiting_newcomer"):
        name = update.message.text.strip()
        session["visitors"].append(f"Newcomer - {name}")
        del context.user_data["awaiting_newcomer"]
        await update.message.reply_text(f"✅ Added newcomer: {name}")
    elif context.user_data.get("awaiting_reason"):
        name = context.user_data["awaiting_reason"]
        reason = update.message.text.strip()
        session["reasons"][name] = reason
        del context.user_data["awaiting_reason"]
        await update.message.reply_text(f"✅ Reason recorded for {name}.")

    if session["members"]:
        keyboard = [[InlineKeyboardButton(m, callback_data=m)] for m in session["members"]]
        keyboard += [[InlineKeyboardButton("➕ Add Visitor", callback_data="ADD_VISITOR")],
                     [InlineKeyboardButton("➕ Add Newcomer", callback_data="ADD_NEWCOMER")],
                     [InlineKeyboardButton("✅ ALL ACCOUNTED", callback_data="ALL_ACCOUNTED")]]
        await update.message.reply_text("Who else did you miss?", reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await update.message.reply_text("✅ Everyone accounted for. You may now submit.")

async def handle_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    data = query.data
    session = user_sessions.get(user_id)
    if not session:
        await query.edit_message_text("Session expired. Send /start again.")
        return

    if data == "ALL_ACCOUNTED":
        await submit_attendance(user_id, context, query)
    elif data == "NOT_LISTED":
        context.user_data["awaiting_visitor"] = True
        await query.message.reply_text("Enter the name of the visitor who attended:")
    elif data == "ADD_NEWCOMER":
        context.user_data["awaiting_newcomer"] = True
        await query.message.reply_text("Enter newcomer name:")
    else:
    session["selected"].append(data)
    session["members"].remove(data)

    if session["group"] != "Visitors":
        context.user_data["awaiting_reason"] = data
        await query.message.reply_text(f"Why did you miss {data}?")
    else:
        # No reason needed, refresh keyboard immediately
        keyboard = [[InlineKeyboardButton(m, callback_data=m)] for m in session["members"]]
        keyboard += [[InlineKeyboardButton("🆕 Not Listed", callback_data="NOT_LISTED")],
                      [InlineKeyboardButton("➕ Add Newcomer", callback_data="ADD_NEWCOMER")],
                     [InlineKeyboardButton("✅ ALL ACCOUNTED", callback_data="ALL_ACCOUNTED")]]
        await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(keyboard))
       
async def submit_attendance(user_id, context, query):
    session = user_sessions.pop(user_id, None)
    if not session:
        await query.edit_message_text("Session expired.")
        return

    selected_absentees = [{"name": name, "reason": session["reasons"].get(name, "")} for name in session["selected"]]
    visitor_absentees = [{"name": v, "reason": "VISITOR"} for v in session.get("visitors", [])]
    newcomer_absentees = [{"name": n, "reason": "NEWCOMER"} for n in session.get("newcomers", [])]
    all_absentees = selected_absentees + visitor_absentees + newcomer_absentees

    if not all_absentees:
        all_absentees = [{"name": "ALL ACCOUNTED", "reason": ""}]

    data = {
        "group": session["group"],
        "label": session["label"],
        "date": datetime.datetime.now().strftime("%Y-%m-%d"),
        "absentees": all_absentees
    }

    try:
        requests.post(WEBHOOK_URL, json=data)
        await query.edit_message_text("✅ Attendance submitted.")
    except Exception as e:
        await query.edit_message_text(f"❌ Submission failed: {e}")

    await update_progress(user_id, context)

async def broadcast_attendance(update: Update, context: ContextTypes.DEFAULT_TYPE, label: str):
    submitted_users = set()
    total = len(USER_GROUPS)
    chat_id = update.effective_chat.id

    msg = await context.bot.send_message(chat_id, text=f"🟡 0/{total} submitted. Still waiting for: {', '.join(map(str, USER_GROUPS))}")
    context.bot_data["progress"] = {"message_id": msg.message_id, "chat_id": chat_id, "submitted": submitted_users}

    for user_id in USER_GROUPS:
        if user_id not in context.bot_data.get("user_chats", {}):
            continue
        await send_attendance_prompt(user_id, context.bot, context, label)

async def update_progress(user_id, context):
    progress = context.bot_data.get("progress")
    if not progress:
        return
    progress["submitted"].add(user_id)
    total = len(USER_GROUPS)
    submitted = len(progress["submitted"])

    waiting = [escape_markdown(USER_NAMES.get(uid, f"User {uid}")) for uid in USER_GROUPS if uid not in progress["submitted"]]
    text = f"✅ {submitted}/{total} submitted.\nStill waiting for: {', '.join(waiting)}"

    await context.bot.edit_message_text(
        text=text,
        chat_id=progress["chat_id"],
        message_id=progress["message_id"],
        parse_mode=ParseMode.MARKDOWN_V2
    )

async def restart_attendance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id in user_sessions:
        user_sessions.pop(user_id)
        await update.message.reply_text("🔁 Your attendance session has been reset.")
    else:
        await update.message.reply_text("ℹ️ No active session to reset.")

async def predawn(update, context): await broadcast_attendance(update, context, "Predawn")
async def sunday(update, context): await broadcast_attendance(update, context, "Sunday")
async def wednesday(update, context): await broadcast_attendance(update, context, "Wednesday")

async def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.bot_data["user_chats"] = load_user_chats()
    app.add_handler(CommandHandler("start", handle_start))
    app.add_handler(CommandHandler("restart_attendance", restart_attendance))
    app.add_handler(CommandHandler("predawn", predawn))
    app.add_handler(CommandHandler("sunday", sunday))
    app.add_handler(CommandHandler("wednesday", wednesday))
    app.add_handler(CallbackQueryHandler(handle_button))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_reason))
    scheduler.start()
    print("🤖 Bot is running...")
    await app.run_polling()

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())
