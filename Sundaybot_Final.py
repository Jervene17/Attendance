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

BOT_TOKEN = os.getenv("BOT_TOKEN")
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
        "CAREER FEMALES 3": ["Riza", "Saeyong"],
        "Visitors": ["Riza","M Saeyoung","Taiki","Randrew Dela Cruz", "John Carlo Lucero", "Cherry Ann", "Rhea Cho", "Gemma", "Yolly", "Weng"]
    },
    "Wednesday": {
        "CAREER FEMALES 2": ["Donna", "Vicky"],
        "CAREER FEMALES 3": ["Riza"],
        "Visitors": ["Riza","M Saeyoung","Taiki","Randrew Dela Cruz", "John Carlo Lucero", "Cherry Ann", "Rhea Cho", "Gemma", "Yolly", "Weng"]
    }
}
user_sessions = {}  # user_id -> session dict

# === COMMAND HANDLER ===
async def start_attendance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if update.message.chat.type != "private":
        await update.message.reply_text("Please message me in private to start attendance.")
        return

    context.bot_data.setdefault("user_chats", {})[user.id] = update.message.chat_id

    # Example hardcoded label for testing
    await send_attendance_prompt(user.id, context.bot, context, label="Sunday")


# === PROMPT ===
async def send_attendance_prompt(user_id, bot: Bot, context, label):
    group = USER_GROUPS[user_id]
    members = MEMBER_LISTS[group][:]

    if group != "Visitors":
        excluded = EXCLUSIONS.get(label, {}).get(group, [])
        members = [m for m in members if m not in excluded]

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

    if group == "Visitors":
        prompt_text = f"Who attended the {label} service?"
    else:
        prompt_text = f"Who did you miss this {label}?"

    keyboard = [[InlineKeyboardButton(m, callback_data=m)] for m in members]

    if group == "Visitors":
        keyboard += [[InlineKeyboardButton("🆕 Not Listed", callback_data="NOT_LISTED")]]

    if group != "Visitors":
        keyboard += [[InlineKeyboardButton("➕ Add Newcomer", callback_data="ADD_NEWCOMER")]]

    keyboard += [[InlineKeyboardButton("✅ ALL ACCOUNTED", callback_data="ALL_ACCOUNTED")]]

    await bot.send_message(chat_id, text=prompt_text, reply_markup=InlineKeyboardMarkup(keyboard))


# === BUTTON CALLBACK ===
async def handle_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    data = query.data

    session = user_sessions.get(user_id)
    if not session:
        await query.edit_message_text("Session expired or missing. Please restart attendance.")
        return

    if data == "ALL_ACCOUNTED":
        await query.edit_message_text("✅ Thank you! Submission complete.")
        return

    elif data == "ADD_NEWCOMER":
        context.user_data["awaiting_newcomer"] = True
        await query.message.reply_text("Enter the newcomer's name:")

    elif data == "NOT_LISTED":
        context.user_data["awaiting_visitor"] = True
        await query.message.reply_text("Enter the name of the visitor who attended:")

    else:
        if session["group"] == "Visitors":
            if data not in session["selected"]:
                session["selected"].append(data)
                await query.message.reply_text(f"✅ Marked {data} as present")
        else:
            if data not in session["selected"]:
                session["selected"].append(data)
                if session["label"] != "Predawn":
                    context.user_data["awaiting_reason"] = data
                    await query.message.reply_text(f"Why was {data} absent?")
                else:
                    await query.message.reply_text(f"✅ Marked {data} as absent")


# === MESSAGE HANDLER ===
async def handle_reason(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    session = user_sessions.get(user_id)
    if not session:
        await update.message.reply_text("Session missing. Please restart attendance.")
        return

    if context.user_data.get("awaiting_reason"):
        name = context.user_data.pop("awaiting_reason")
        session["reasons"][name] = update.message.text.strip()
        await update.message.reply_text(f"📝 Reason noted for {name}.")

    elif context.user_data.get("awaiting_newcomer"):
        name = update.message.text.strip()
        session["selected"].append(f"Newcomer - {name}")
        del context.user_data["awaiting_newcomer"]
        await update.message.reply_text(f"✅ Added newcomer: {name}")

    elif context.user_data.get("awaiting_visitor"):
        name = update.message.text.strip()
        session["visitors"].append(f"Visitor - {name}")
        del context.user_data["awaiting_visitor"]
        await update.message.reply_text(f"✅ Added visitor: {name}")


# === MAIN ===
def main():
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start_attendance))
    app.add_handler(CallbackQueryHandler(handle_button))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_reason))

    scheduler = AsyncIOScheduler(timezone=timezone("Asia/Manila"))
    scheduler.start()

    print("Bot running...")
    app.run_polling()

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())