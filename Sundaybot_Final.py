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
    ApplicationBuilder, CommandHandler, CallbackQueryHandler,
    MessageHandler, ContextTypes, filters, PicklePersistence
)
from telegram.helpers import escape_markdown

# Load local .env if present (Railway ignores this and uses its own env vars)
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
print("DEBUG: Railway BOT_TOKEN =", repr(os.getenv("BOT_TOKEN")))

WEBHOOK_URL = os.getenv("WEBHOOK_URL")

persistence = PicklePersistence(filepath="bot_persistence.pkl")

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
    519557915: "HQ"
}

USER_NAMES = {
    503493798: "Fatima",
    485107813: "Jabs",
    707729145: "Shaja",
    518836085: "Mel",
    7681981308: "D Rue",
    2016438287: "Divine",
    544095264: "MCor",
    515714808: "M Jervene",
    2120840431: "Andrea",
    519557915: "M Rose"
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
    "HQ": ["PK","M Ju Nara","MA","M Sarah","Mjhay"]
}

EXCLUSIONS = {
    "Predawn": {
        "CAREER FEMALES 2": ["Donna", "Vicky"],
        "Visitors": ["Riza","M Saeyoung","Taiki","Randrew Dela Cruz","John Carlo Lucero",
                     "Cherry Ann","Rhea Cho","Gemma","Yolly","Weng"],
        "JS": ["Tita Merlita"]
    },
    "Wednesday": {
        "CAREER FEMALES 2": ["Donna", "Vicky"],
        "Visitors": ["Riza","M Saeyoung","Taiki","Randrew Dela Cruz","John Carlo Lucero",
                     "Cherry Ann","Rhea Cho","Gemma","Yolly","Weng"],
        "JS": ["Tita Merlita"]
    },
    "Friday": {
        "CAREER FEMALES 2": ["Donna", "Vicky"],
        "Visitors": ["Riza","M Saeyoung","Taiki","Randrew Dela Cruz","John Carlo Lucero",
                     "Cherry Ann","Rhea Cho","Gemma","Yolly","Weng"],
        "JS": ["Tita Merlita"]
    }
}

# 🔹 Helper: build prompt text + keyboard
# 🔹 Helper: build prompt text + keyboard
def build_attendance_prompt(group, members, label):
    # Decide prompt text
    if group in ["HQ", "Visitors"]:
        prompt_text = f"Who attended this {label}?"
    else:
        prompt_text = f"Who did you miss this {label}?"

    # Build keyboard
    keyboard = [[InlineKeyboardButton(m, callback_data=m)] for m in members]

    if group == "Visitors":
        keyboard += [[InlineKeyboardButton("🆕 Not Listed", callback_data="NOT_LISTED")]]
    elif group != "HQ":
        keyboard += [[InlineKeyboardButton("➕ Add Newcomer", callback_data="ADD_NEWCOMER")]]

    keyboard += [[InlineKeyboardButton("✅ ALL ACCOUNTED", callback_data="ALL_ACCOUNTED")]]

    return prompt_text, InlineKeyboardMarkup(keyboard)



# 🔹 Main: send attendance prompt
async def send_attendance_prompt(user_id, context, label, group=None):
    # Resolve group
    group = group or USER_GROUPS.get(user_id)
    if not group:
        print(f"[SKIP] No group found for user {user_id}")
        return

    # Skip prompting Visitors for certain services
    if group == "Visitors" and label in ["Predawn", "Wednesday", "Friday"]:
        print(f"[SKIP] Skipping Visitors group for {label}")
        return

    # Base member list
    members = MEMBER_LISTS.get(group, [])[:]

    # Apply exclusions (only for non-Visitors)
    if group != "Visitors":
        excluded = EXCLUSIONS.get(label, {}).get(group, [])
        members = [m for m in members if m not in excluded]

    # ✅ Start session (store in bot_data so it persists across restarts)
    sessions = context.bot_data.setdefault("user_sessions", {})
    sessions[(user_id, label)] = {
        "group": group,
        "label": label,
        "members": members,
        "selected": [],
        "reasons": {},
        "visitors": [],
        "newcomers": []   # track manually added newcomers only
    }
    context.user_data["label"] = label

    # Find private chat
    chat_id = context.bot_data.get("user_chats", {}).get(user_id)
    if not chat_id:
        print(f"[SKIP] No private chat for user {user_id}")
        return

    # 🔹 Build message and keyboard
    prompt_text, keyboard = build_attendance_prompt(group, members, label)

    # Send message
    await send_attendance_prompt(user_id, context, label)



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
    label = context.user_data.get("label")
    sessions = context.bot_data.get("user_sessions", {})
    session = sessions.get((user_id, label))
    if not session:
        await update.message.reply_text("⚠️ No active session found for this prompt.")
        return

    # ✅ Handle custom reason (for "Others")
    if context.user_data.get("awaiting_reason_custom"):
        name = context.user_data.pop("awaiting_reason_custom")
        custom_reason = update.message.text.strip()
        session["reasons"][name] = custom_reason
        await update.message.reply_text(f"✅ Reason recorded for {name}: {custom_reason}")

    # ✅ Handle visitor entry
    elif context.user_data.get("awaiting_visitor"):
        name = update.message.text.strip()
        session["visitors"].append(f"Visitor - {name}")
        del context.user_data["awaiting_visitor"]
        await update.message.reply_text(f"✅ Added visitor: {name}")

    # ✅ Handle newcomer entry
    elif context.user_data.get("awaiting_newcomer"):
        name = update.message.text.strip()
        session["newcomers"].append(name)
        session["reasons"][name] = ""  # Leave reason blank
        del context.user_data["awaiting_newcomer"]
        await update.message.reply_text(f"✅ Added newcomer: {name}")

    # ✅ Handle free-form reason
    elif context.user_data.get("awaiting_reason"):
        name = context.user_data.pop("awaiting_reason")
        reason = update.message.text.strip()
        session["reasons"][name] = reason
        await update.message.reply_text(f"✅ Reason recorded for {name}.")

    # 🔄 Refresh keyboard or finalize
    if session["members"]:
        prompt, keyboard = build_attendance_prompt(session["group"], session["members"], label)
        await update.message.reply_text(prompt, reply_markup=keyboard)
    else:
        await update.message.reply_text("✅ Everyone accounted for. You may now submit.")


async def handle_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    data = query.data

    # retrieve label from context or from callback data if it has format LABEL|DATA
    if "|" in data:
        label, data = data.split("|", 1)
        context.user_data["label"] = label
    else:
        label = context.user_data.get("label")

    # ✅ pull from persistent sessions
    sessions = context.bot_data.setdefault("user_sessions", {})
    session = sessions.get((user_id, label))

    if not session:
        await query.edit_message_text("⚠️ No active session found for this prompt.")
        return

    if data == "ALL_ACCOUNTED":
        await submit_attendance(user_id, context, query)
        if "progress" in context.bot_data:
            context.bot_data["progress"]["submitted"].add(user_id)
            await update_progress(user_id, context)

        # 🔄 refresh keyboard to disable further clicks
        await query.edit_message_reply_markup(reply_markup=None)
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
        if name:
            session["reasons"][name] = reason
            context.user_data["awaiting_reason"] = name
        await query.message.reply_text("Please specify. (Put N/A if no additional explanation needed)")

    elif data in session["members"]:
        # Prevent duplicates
        if data not in session["selected"]:
            session["selected"].append(data)
            session["members"].remove(data)

        if session["group"] != "Visitors":
            # Always ask for reason
            context.user_data["awaiting_reason_name"] = data
            reason_options = [
                "Family Emergency", "No Fare money", "Sick", "Taking care of a loved one",
                "Work related", "Far from onsite without Electricity/Internet",
                "Did not wake up early", "Need to relay to Headleader", "Others"
            ]
            context.user_data["reason_choices"] = reason_options
            reason_kb = [
                [InlineKeyboardButton(reason, callback_data=f"{label}|REASON_{i}")]
                for i, reason in enumerate(reason_options)
            ]
            await query.message.reply_text(
                f"Select reason for {escape_markdown(data, version=2)}:",
                reply_markup=InlineKeyboardMarkup(reason_kb),
                parse_mode="MarkdownV2"
            )
        else:
            # Visitors: 🔄 refresh main keyboard after selection
            keyboard = [[InlineKeyboardButton(m, callback_data=f"{label}|{m}")] for m in session["members"]]
            keyboard += [
                [InlineKeyboardButton("🆕 Not Listed", callback_data=f"{label}|NOT_LISTED")],
                [InlineKeyboardButton("✅ ALL ACCOUNTED", callback_data=f"{label}|ALL_ACCOUNTED")]
            ]
            await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(keyboard))


async def submit_attendance(user_id, context, query):
    label = context.user_data.get("label")

    # ✅ Pull from persisted sessions
    sessions = context.bot_data.setdefault("user_sessions", {})
    session = sessions.get((user_id, label))   # don't pop yet
    if not session:
        await query.edit_message_text("⚠️ Session mismatch. No active session found for this prompt.")
        return

    # Absentees
    selected_absentees = [
        {
            "name": name,
            "reason": session["reasons"].get(name, ""),
            "department": session["group"]
        }
        for name in session["selected"]
    ]

    # Newcomers
    newcomers = [
        {"name": n, "reason": "NC", "department": "Newcomers"}
        for n in session.get("newcomers", [])
    ]

    # Visitors
    visitors = [
        {"name": v.replace("Visitor - ", ""), "reason": "", "department": "Visitors"}
        for v in session.get("visitors", [])
    ]

    # Combine
    all_entries = selected_absentees + newcomers + visitors
    if not all_entries:
        all_entries = [{"name": "ALL ACCOUNTED", "reason": "", "department": session["group"]}]

    current_date = datetime.datetime.now().strftime("%Y-%m-%d")

    data = {
        "group": session["group"],
        "label": session["label"],
        "date": current_date,
        "absentees": all_entries,
        "chat_id": query.message.chat.id,
        "username": query.from_user.username or USER_NAMES.get(user_id, "Unknown")
    }

    try:
        requests.post(WEBHOOK_URL, json=data)
        await query.edit_message_text("✅ Attendance submitted.")

        # Sunday special message (unchanged)
        today = datetime.datetime.now().strftime("%A")
        entries_for_message = [item for item in all_entries if item["name"] != "ALL ACCOUNTED"]

        if today == "Sunday" and entries_for_message:
            absentees_text_list = []
            for item in entries_for_message:
                name = item["name"]
                reason = item.get("reason", "")
                line = f"{name}: {reason if reason else 'N/A'}"
                escaped_line = escape_markdown(line, version=2)
                absentees_text_list.append("• " + escaped_line)

            message = escape_markdown("📋 Sunday Absentees:\n", version=2) + "\n".join(absentees_text_list)

            target_user_ids = [439340490]  # Replace with actual IDs
            for uid in target_user_ids:
                try:
                    await context.bot.send_message(
                        chat_id=uid,
                        text=message,
                        parse_mode=ParseMode.MARKDOWN_V2
                    )
                except Exception as e:
                    print(f"❌ Failed to send absentees to {uid}: {e}")

    except Exception as e:
        await query.edit_message_text(f"❌ Submission failed: {e}")

    # ✅ always clear this user’s session at the very end
    sessions.pop((user_id, label), None)

    # ✅ Refresh keyboard after submission (if there are still members left)
    if session.get("members"):
        prompt, keyboard = build_attendance_prompt(session["group"], session["members"], label)
        await context.bot.send_message(
            chat_id=query.message.chat.id,
            text=prompt,
            reply_markup=keyboard
        )

    # Update group progress after submission
    await update_progress(user_id, context)


async def broadcast_attendance(update: Update, context: ContextTypes.DEFAULT_TYPE, label: str):
    submitted_users = set()
    total = len(USER_GROUPS)
    chat_id = update.effective_chat.id

    # Escape all usernames safely
    waiting_users = [
        escape_markdown(USER_NAMES.get(uid, f"User {uid}"), version=2)
        for uid in USER_GROUPS
    ]

    # Initial progress message
    initial_text = f"🟡 0/{total} submitted. Still waiting for: {', '.join(waiting_users)}"
    escaped_text = escape_markdown(initial_text, version=2)

    msg = await context.bot.send_message(
        chat_id,
        text=escaped_text,
        parse_mode=ParseMode.MARKDOWN_V2
    )

    # Store progress tied to this label
    context.bot_data["progress"] = {
        "message_id": msg.message_id,
        "chat_id": chat_id,
        "submitted": submitted_users,
        "label": label
    }

    # Prepare user_sessions and send prompts
    sessions = context.bot_data.setdefault("user_sessions", {})
    for user_id in USER_GROUPS:
        # Only send to users who have done /start
        if user_id not in context.bot_data.get("user_chats", {}):
            print(f"[SKIP] User {user_id} has no private chat")
            continue

        # Initialize session
        sessions[(user_id, label)] = {
            "group": USER_GROUPS[user_id],
            "label": label,
            "members": MEMBER_LISTS.get(USER_GROUPS[user_id], [])[:],
            "selected": [],
            "reasons": {},
            "newcomers": [],
            "visitors": []
        }

        # Send attendance prompt
        await send_attendance_prompt(user_id, context, label)


async def update_progress(user_id, context):
    progress = context.bot_data.get("progress")
    if not progress:
        return

    # ✅ Ensure "submitted" exists
    if "submitted" not in progress:
        progress["submitted"] = set()

    progress["submitted"].add(user_id)
    total = len(USER_GROUPS)
    submitted = len(progress["submitted"])

    # ✅ Escape waiting usernames
    waiting = [
        escape_markdown(USER_NAMES.get(uid, f"User {uid}"), version=2)
        for uid in USER_GROUPS if uid not in progress["submitted"]
    ]

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
            parse_mode=ParseMode.MARKDOWN_V2
        )
    except Exception as e:
        # Fallback: just send plain text if MarkdownV2 fails
        print("❌ Failed to update progress message:", e)
        await context.bot.send_message(
            chat_id=progress["chat_id"],
            text=text
        )


async def restart_attendance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    # ✅ Find any active session(s) for this user
    active_sessions = [(uid, lbl) for (uid, lbl) in user_sessions if uid == user_id]

    if active_sessions:
        for key in active_sessions:
            user_sessions.pop(key, None)
        await update.message.reply_text("🔁 Your attendance session has been reset.")
    else:
        await update.message.reply_text("ℹ️ No active session to reset.")

async def predawn(update, context): await broadcast_attendance(update, context, "Predawn")
async def sunday(update, context): await broadcast_attendance(update, context, "Sunday")
async def wednesday(update, context): await broadcast_attendance(update, context, "Wednesday")
async def friday(update, context): await broadcast_attendance(update, context, "Friday")

def main():
    app = ApplicationBuilder().token(BOT_TOKEN).persistence(persistence).build()

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

    # Run polling (starts event loop internally)
    app.run_polling()

if __name__ == "__main__":
    main()


