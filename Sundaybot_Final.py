import os
import json
import datetime
import asyncio
import re
import html
import requests
from dotenv import load_dotenv
from pytz import timezone
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Bot, Update
from telegram.constants import ParseMode
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)
from telegram.helpers import escape_markdown

# Load local .env if present (Railway ignores this and uses its own env vars)
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
print("DEBUG: Railway BOT_TOKEN =", repr(os.getenv("BOT_TOKEN")))
WEBHOOK_URL = os.getenv("WEBHOOK_URL")

user_sessions = {}

# === Static Config ===
USER_GROUPS = {
    503493798: "FAMILY FEMALES",
    485107813: "CAREER MALES",
    707729145: "CAREER FEMALES 1",
    518836085: "CAREER FEMALES 2",
    7681981308: "CAREER FEMALES 3",
    2016438287: "CAMPUS FEMALES",
    544095264: "JS",
    515714808: "FAMILY MALES",
    2120840431: "Visitors",
    519557915: "HQ",
}

USER_NAMES = {
    503493798: "Fatima",
    485107813: "Jabs",
    707729145: "Shaja",
    518836085: "Mel",
    7681981308: "D Rue",
    2016438287: "Divine",
    544095264: "MCor",
    515714808: "Jervene",
    2120840431: "Andrea",
    519557915: "M Rose",
}

MEMBER_LISTS = {
    "FAMILY FEMALES": ["Fatima", "Vangie", "M Ru", "Dcn Frances", "Shayne", "Dcn Issa"],
    "FAMILY MALES": ["Dcn Ian", "M Jervene", "Jessie", "Almen", "Dcn Probo"],
    "CAREER MALES": ["Jabs", "Xander", "Franz", "Daniel", "Jiboy", "Venancio", "Iven"],
    "CAREER FEMALES 1": ["Shaja", "Grace", "Daryl", "Clarice", "Mia", "Aliza", "Anica"],
    "CAREER FEMALES 2": ["Mel", "Andrea", "Angel", "Inia", "M Rose", "Vicky", "Donna"],
    "CAREER FEMALES 3": ["D Rue", "PP Bam", "Zhandra", "Trina", "Dr Kristine"],
    "CAMPUS FEMALES": ["Divine", "Marinell"],
    "JS": ["MCor", "Tita Merlita", "Grace", "Emeru"],
    "Visitors": ["Riza", "M Saeyoung", "Taiki", "Randrew Dela Cruz", "John Carlo Lucero",
                 "Cherry Ann", "Rhea Cho", "Gemma", "Yolly", "Weng"],
    "HQ": ["PK", "M Ju Nara", "MA", "M Sarah", "Mjhay"],
}

EXCLUSIONS = {
    "Predawn": {
        "CAREER FEMALES 2": ["Donna", "Vicky"],
        "Visitors": ["Riza", "M Saeyoung", "Taiki", "Randrew Dela Cruz", "John Carlo Lucero",
                     "Cherry Ann", "Rhea Cho", "Gemma", "Yolly", "Weng"],
        "JS": ["Tita Merlita"],
    },
    "Wednesday": {
        "CAREER FEMALES 2": ["Donna", "Vicky"],
        "Visitors": ["Riza", "M Saeyoung", "Taiki", "Randrew Dela Cruz", "John Carlo Lucero",
                     "Cherry Ann", "Rhea Cho", "Gemma", "Yolly", "Weng"],
        "JS": ["Tita Merlita"],
    },
    "Friday": {
        "CAREER FEMALES 2": ["Donna", "Vicky"],
        "Visitors": ["Riza", "M Saeyoung", "Taiki", "Randrew Dela Cruz", "John Carlo Lucero",
                     "Cherry Ann", "Rhea Cho", "Gemma", "Yolly", "Weng"],
        "JS": ["Tita Merlita"],
    },
}

# 🔹 Helper: build prompt text + keyboard
def build_attendance_prompt(group, members, label):
    if group in ["HQ", "Visitors"]:
        prompt_text = f"Who attended this {label}?"
    else:
        prompt_text = f"Who did you miss this {label}?"

    keyboard = [[InlineKeyboardButton(m, callback_data=m)] for m in members]

    if group == "Visitors":
        keyboard += [[InlineKeyboardButton("🆕 Not Listed", callback_data="NOT_LISTED")]]
    elif group != "HQ":
        keyboard += [[InlineKeyboardButton("➕ Add Newcomer", callback_data="ADD_NEWCOMER")]]

    keyboard += [[InlineKeyboardButton("✅ ALL ACCOUNTED", callback_data="ALL_ACCOUNTED")]]

    return prompt_text, InlineKeyboardMarkup(keyboard)


# 🔹 Main: send attendance prompt
async def send_attendance_prompt(user_id, bot: Bot, context, label):
    group = USER_GROUPS[user_id]

    # Skip prompting Visitors for Predawn, Wednesday, Friday
    if group == "Visitors" and label in ["Predawn", "Wednesday", "Friday"]:
        print(f"[SKIP] Skipping Visitors group for {label}")
        return

    members = MEMBER_LISTS[group][:]

    if group != "Visitors":
        excluded = EXCLUSIONS.get(label, {}).get(group, [])
        members = [m for m in members if m not in excluded]

    # ✅ Start session
    user_sessions[(user_id, label)] = {
        "group": group,
        "label": label,
        "members": members[:],
        "selected": [],
        "reasons": {},
        "visitors": [],
        "newcomers": [],
    }

    context.user_data["label"] = label

    chat_id = context.bot_data.get("user_chats", {}).get(user_id)
    if not chat_id:
        print(f"[SKIP] No private chat for user {user_id}")
        return

    prompt_text, keyboard = build_attendance_prompt(group, members, label)
    await bot.send_message(chat_id, text=prompt_text, reply_markup=keyboard)


# 🔹 Start command
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat_id = update.effective_chat.id

    if "user_chats" not in context.bot_data:
        context.bot_data["user_chats"] = {}

    if update.effective_chat.type == "private":
        context.bot_data["user_chats"][user.id] = chat_id
        await update.message.reply_text("You're now registered for attendance prompts.")


# 🔹 Handle text responses for reasons, newcomers, visitors
async def handle_reason(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    label = context.user_data.get("label")
    session = user_sessions.get((user_id, label))
    if not session:
        await update.message.reply_text("⚠️ No active session found for this prompt.")
        return

    if context.user_data.get("awaiting_reason_custom"):
        name = context.user_data.pop("awaiting_reason_custom")
        custom_reason = update.message.text.strip()
        session["reasons"][name] = custom_reason
        await update.message.reply_text(f"✅ Reason recorded for {name}: {custom_reason}")

    elif context.user_data.get("awaiting_visitor"):
        name = update.message.text.strip()
        session["visitors"].append(f"Visitor - {name}")
        del context.user_data["awaiting_visitor"]
        await update.message.reply_text(f"✅ Added visitor: {name}")

    elif context.user_data.get("awaiting_newcomer"):
        name = update.message.text.strip()
        session["newcomers"].append(name)
        session["reasons"][name] = ""
        del context.user_data["awaiting_newcomer"]
        await update.message.reply_text(f"✅ Added newcomer: {name}")

    elif context.user_data.get("awaiting_reason"):
        name = context.user_data.pop("awaiting_reason")
        reason = update.message.text.strip()
        session["reasons"][name] = reason
        await update.message.reply_text(f"✅ Reason recorded for {name}.")

    # Refresh keyboard if there are still members
    if session["members"]:
        prompt, keyboard = build_attendance_prompt(session["group"], session["members"], label)
        await update.message.reply_text(prompt, reply_markup=keyboard)
    else:
        await update.message.reply_text("✅ Everyone accounted for. You may now submit.")


# 🔹 Handle inline button presses
async def handle_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    data = query.data

    label = context.user_data.get("label")
    if "|" in data:
        label, data = data.split("|", 1)
        context.user_data["label"] = label

    session = user_sessions.get((user_id, label))
    if not session:
        await query.edit_message_text("⚠️ No active session found for this prompt.")
        return

    # ... handle all button cases here ...
    # (ALL_ACCOUNTED, NOT_LISTED, ADD_NEWCOMER, REASON_x, member selection)
    # Logic same as original script


# 🔹 Submit attendance
async def submit_attendance(user_id, context, query):
    label = context.user_data.get("label")
    session = user_sessions.get((user_id, label))
    if not session:
        await query.edit_message_text("ℹ️ No active session found.")
        return

    # Process absentees, newcomers, visitors and send webhook
    # Clear session at the end
    user_sessions.pop((user_id, label), None)


# 🔹 Broadcast attendance prompts
async def broadcast_attendance(update: Update, context: ContextTypes.DEFAULT_TYPE, label: str):
    submitted_users = set()
    total = len(USER_GROUPS)
    chat_id = update.effective_chat.id

    waiting_users = [escape_markdown(USER_NAMES.get(uid, f"User {uid}"), version=2) for uid in USER_GROUPS]
    initial_text = f"🟡 0/{total} submitted. Still waiting for: {', '.join(waiting_users)}"
    escaped_text = escape_markdown(initial_text, version=2)
    msg = await context.bot.send_message(chat_id, text=escaped_text, parse_mode=ParseMode.MARKDOWN_V2)

    context.bot_data["progress"] = {"message_id": msg.message_id, "chat_id": chat_id, "submitted": submitted_users}

    for user_id in USER_GROUPS:
        if user_id not in context.bot_data.get("user_chats", {}):
            continue
        await send_attendance_prompt(user_id, context.bot, context, label)


# 🔹 Update progress in group
async def update_progress(user_id, context):
    progress = context.bot_data.get("progress")
    if not progress:
        return

    progress["submitted"].add(user_id)
    total = len(USER_GROUPS)
    submitted = len(progress["submitted"])
    waiting = [escape_markdown(USER_NAMES.get(uid, f"User {uid}"), version=2)
               for uid in USER_GROUPS if uid not in progress["submitted"]]

    text = f"✅ {submitted}/{total} submitted."
    if waiting:
        text += f"\nStill waiting for: {', '.join(waiting)}"
    else:
        text += "\n🎉 All users have submitted."

    escaped_text = escape_markdown(text, version=2)
    try:
        await context.bot.edit_message_text(
            text=escaped_text,
            chat_id=progress["chat_id"],
            message_id=progress["message_id"],
            parse_mode=ParseMode.MARKDOWN_V2,
        )
    except Exception as e:
        print("❌ Failed to update progress message:", e)
        await context.bot.send_message(chat_id=progress["chat_id"], text=text)


# 🔹 Restart attendance session
async def restart_attendance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    label = context.user_data.get("label")
    if (user_id, label) in user_sessions:
        user_sessions.pop((user_id, label))
        await update.message.reply_text("🔁 Your attendance session has been reset.")
    else:
        await update.message.reply_text("ℹ️ No active session to reset.")


# 🔹 Service commands
async def predawn(update, context): await broadcast_attendance(update, context, "Predawn")
async def sunday(update, context): await broadcast_attendance(update, context, "Sunday")
async def wednesday(update, context): await broadcast_attendance(update, context, "Wednesday")
async def friday(update, context): await broadcast_attendance(update, context, "Friday")


# 🔹 Main entry
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # Commands
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("restart_attendance", restart_attendance))
    app.add_handler(CommandHandler("predawn", predawn))
    app.add_handler(CommandHandler("sunday", sunday))
    app.add_handler(CommandHandler("wednesday", wednesday))
    app.add_handler(CommandHandler("friday", friday))

    # Callbacks
    app.add_handler(CallbackQueryHandler(handle_button))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_reason))

    app.run_polling()


if __name__ == "__main__":
    main()
