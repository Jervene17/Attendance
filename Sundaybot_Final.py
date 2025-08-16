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

BOT_TOKEN = '7651692145:AAGmvAfhjqJ_bhKOyTM-KN3EDGlGaqLOY6E'
WEBHOOK_URL = 'https://script.google.com/macros/s/AKfycbxbOAoL3sgcNdHdXdCpiOTolC_5exn0PQDHmeV9zHmHGdtscMY9-SKk0MknzxaD_ufV/exec'

# === Static Config ===
USER_GROUPS = {
    503493798: "FAMILY FEMALES",
    222222222: "CAREER MALES",
    707729145: "CAREER FEMALES 1",
    777777777: "CAREER FEMALES 2",
    666666666: "CAREER FEMALES 3",
    444444444: "CAMPUS FEMALES",
    544095264: "JS",
    515714808: "FAMILY MALES",
    888888888: "Visitors",
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
    "FAMILY MALES": ["Dcn Ian", "M Jervene", "Jessie", "Almen", "Dcn Probo"],
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
        "Visitors": ["Riza","M Saeyoung","Taiki","Randrew Dela Cruz", "John Carlo Lucero", "Cherry Ann", "Rhea Cho", "Gemma", "Yolly", "Weng"],
        "JS":["Tita Merlita"]
    },
    "Wednesday": {
        "CAREER FEMALES 2": ["Donna", "Vicky"],
        "Visitors": ["Riza","M Saeyoung","Taiki","Randrew Dela Cruz", "John Carlo Lucero", "Cherry Ann", "Rhea Cho", "Gemma", "Yolly", "Weng"],
        "JS":["Tita Merlita"]
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
    else:
        keyboard += [[InlineKeyboardButton("➕ Add Newcomer", callback_data="ADD_NEWCOMER")]]

    keyboard += [[InlineKeyboardButton("✅ ALL ACCOUNTED", callback_data="ALL_ACCOUNTED")]]

    # Send message
    await bot.send_message(chat_id, text=prompt_text, reply_markup=InlineKeyboardMarkup(keyboard))

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat_id = update.effective_chat.id
    print(f"Received /start from user {user.id} in chat {chat_id}")

    if "user_chats" not in context.bot_data:
        context.bot_data["user_chats"] = {}

    if update.effective_chat.type == "private":
        context.bot_data["user_chats"][user.id] = chat_id
        await update.message.reply_text("You're now registered for attendance prompts.")

async def handle_reason(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    session = user_sessions.get(user_id)

    # ✅ Handle custom reason (for "Others")
    if context.user_data.get("awaiting_reason_custom"):
        name = context.user_data.pop("awaiting_reason_custom")
        custom_reason = update.message.text.strip()
        session["reasons"][name] = custom_reason
        await update.message.reply_text(f"✅ Reason recorded for {name}: {custom_reason}")

        # Refresh keyboard if more members left
        if session["members"]:
            keyboard = [[InlineKeyboardButton(m, callback_data=m)] for m in session["members"]]
            keyboard += [
                [InlineKeyboardButton("➕ Add Newcomer", callback_data="ADD_NEWCOMER")],
                [InlineKeyboardButton("✅ ALL ACCOUNTED", callback_data="ALL_ACCOUNTED")]
            ]
            await update.message.reply_text("Who else did you miss?", reply_markup=InlineKeyboardMarkup(keyboard))
        else:
            await update.message.reply_text("✅ Everyone accounted for. You may now submit.")
        return  # Important to return here to avoid processing below blocks

    # ✅ Handle visitor entry
    if context.user_data.get("awaiting_visitor"):
        name = update.message.text.strip()
        session["visitors"].append(f"Visitor - {name}")
        del context.user_data["awaiting_visitor"]
        await update.message.reply_text(f"✅ Added visitor: {name}")

    # ✅ Handle newcomer entry
    elif context.user_data.get("awaiting_newcomer"):
        name = update.message.text.strip()
        session["members"].append(name)
        session["reasons"][name] = ""  # Leave reason blank
        del context.user_data["awaiting_newcomer"]
        await update.message.reply_text(f"✅ Added newcomer: {name}")

    # ✅ Handle free-form reason
    elif context.user_data.get("awaiting_reason"):
        name = context.user_data.pop("awaiting_reason")
        reason = update.message.text.strip()
        session["reasons"][name] = reason
        await update.message.reply_text(f"✅ Reason recorded for {name}.")

    # ✅ Refresh keyboard for next person
    if session.get("group") == "Visitors":
        keyboard = [[InlineKeyboardButton(m, callback_data=m)] for m in session["members"]]
        keyboard += [
            [InlineKeyboardButton("🆕 Not Listed", callback_data="NOT_LISTED")],
            [InlineKeyboardButton("➕ Add Newcomer", callback_data="ADD_NEWCOMER")],
            [InlineKeyboardButton("✅ ALL ACCOUNTED", callback_data="ALL_ACCOUNTED")]
        ]
        await update.message.reply_text("Who else did you miss?", reply_markup=InlineKeyboardMarkup(keyboard))
    elif session["members"]:
        keyboard = [[InlineKeyboardButton(m, callback_data=m)] for m in session["members"]]
        keyboard += [
            [InlineKeyboardButton("➕ Add Newcomer", callback_data="ADD_NEWCOMER")],
            [InlineKeyboardButton("✅ ALL ACCOUNTED", callback_data="ALL_ACCOUNTED")]
        ]
        await update.message.reply_text("Who else did you miss?", reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await update.message.reply_text("✅ Everyone accounted for. You may now submit.")

async def handle_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    data = query.data
    session = user_sessions.get(user_id)

    if data == "ALL_ACCOUNTED":
        await submit_attendance(user_id, context, query)
        if "progress" in context.bot_data:
            context.bot_data["progress"]["submitted"].add(user_id)
            await update_progress_message(context)
        return

    elif data == "NOT_LISTED":
        context.user_data["awaiting_visitor"] = True
        await query.message.reply_text("Enter the name of the visitor who attended:")

    elif data == "ADD_NEWCOMER":
        context.user_data["awaiting_newcomer"] = True
        await query.message.reply_text("Enter newcomer name:")

    elif data.startswith("REASON_"):
        reason_index = int(data.split("_")[1])
        reason_options = context.user_data.get("reason_choices", [])
        reason = reason_options[reason_index] if reason_index < len(reason_options) else "Unknown"

        name = context.user_data.get("awaiting_reason_name")
        user_sessions[user_id]["reasons"][name] = reason
        context.user_data["awaiting_reason"] = name

        await query.message.reply_text("Please specify. (Put N/A if no additional explanation needed)")

    elif data in session["members"]:
        session["selected"].append(data)
        session["members"].remove(data)

        if session["group"] != "Visitors":
            context.user_data["awaiting_reason_name"] = data

            reason_options = [
                "Family Emergency", "No Fare money", "Sick", "Taking care of a loved one",
                "Work related", "Far from onsite without Electricity/Internet",
                "Did not wake up early", "Need to relay to Headleader", "Others"
            ]
            context.user_data["reason_choices"] = reason_options
            keyboard = [[InlineKeyboardButton(reason, callback_data=f"REASON_{i}")] for i, reason in enumerate(reason_options)]

            await query.message.reply_text(f"Select reason for {data}:", reply_markup=InlineKeyboardMarkup(keyboard))
        else:
            keyboard = [[InlineKeyboardButton(m, callback_data=m)] for m in session["members"]]
            keyboard += [
                [InlineKeyboardButton("🆕 Not Listed", callback_data="NOT_LISTED")],
                [InlineKeyboardButton("➕ Add Newcomer", callback_data="ADD_NEWCOMER")],
                [InlineKeyboardButton("✅ ALL ACCOUNTED", callback_data="ALL_ACCOUNTED")]
            ]
            await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(keyboard))

async def submit_attendance(user_id, context, query):
    session = user_sessions.pop(user_id, None)

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
    "absentees": all_absentees,
    "chat_id": query.message.chat.id,
    "username": query.from_user.username or USER_NAMES.get(user_id, "Unknown")
}

    try:
        requests.post(WEBHOOK_URL, json=data)
        await query.edit_message_text("✅ Attendance submitted.")

        # ✅ Send Sunday absentees to specific users
        from datetime import datetime
        today = datetime.now().strftime("%A")
        absentees = [name for name in session["selected"] if name in session["reasons"]]

        if today == "Sunday" and absentees:
            absentees_text = "\n".join([f"• {name}: {session['reasons'][name]}" for name in absentees])
            message = f"📋 Sunday Absentees:\n{absentees_text}"

            target_user_ids = [439340490, 515714808]  # Replace with actual Telegram IDs

            for uid in target_user_ids:
                try:
                    await context.bot.send_message(chat_id=uid, text=message)
                except Exception as e:
                    print(f"❌ Failed to send absentees to {uid}: {e}")

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

async def update_progress_message(context: ContextTypes.DEFAULT_TYPE):
    progress_data = context.bot_data.get("progress")
    if not progress_data:
        return

    submitted = progress_data["submitted"]
    total = len(USER_GROUPS)
    waiting = [str(uid) for uid in USER_GROUPS if uid not in submitted]

    text = f"✅ {len(submitted)}/{total} submitted.\n"
    if waiting:
        text += f"Still waiting for: {', '.join(waiting)}"
    else:
        text += "🎉 All users have submitted."

    try:
        await context.bot.edit_message_text(
            chat_id=progress_data["chat_id"],
            message_id=progress_data["message_id"],
            text=text
        )
    except Exception as e:
        print("Failed to update progress message:", e)

def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.bot_data["user_chats"] = {}

    # Commands
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("restart_attendance", restart_attendance))
    app.add_handler(CommandHandler("predawn", predawn))
    app.add_handler(CommandHandler("sunday", sunday))
    app.add_handler(CommandHandler("wednesday", wednesday))

    # Buttons
    app.add_handler(CallbackQueryHandler(handle_button))

    # Only handle non-command text in private chats
    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE,
            handle_reason
        )
    )

    scheduler.start()
    print("🤖 Bot is running (webhook)...")

    app.run_webhook(
        listen="0.0.0.0",
        port=int(os.environ.get("PORT", 8443)),
        webhook_url=WEBHOOK_URL
    )


if __name__ == "__main__":
    main()
