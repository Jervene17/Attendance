import requests
import datetime
import asyncio
from pytz import timezone
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Bot, Update, Message
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler,
    MessageHandler, ContextTypes, filters
)
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import nest_asyncio

nest_asyncio.apply()

BOT_TOKEN = '7651692145:AAGmvAfhjqJ_bhKOyTM-KN3EDGlGaqLOY6E'
WEBHOOK_URL = 'https://script.google.com/macros/s/AKfycbwR2zO90VW6LIQr8BO3Aray8VXXoKgotu90n_HVZ4yUvmLO2ZZB-6pN85yw-U8WMvIz/exec'

EXCLUSIONS = {
    "Predawn": {
        "CAREER MALES": ["Taiki"],
        "CAREER FEMALES 2": ["Donna", "Vicky"],
        "CAREER FEMALES 3": ["Riza", "Saeyong"],
        "JS": ["Randrew Dela Cruz", "John Carlo Lucero", "Cherry Ann", "Rhea Cho", "Gemma", "Yolly", "Weng"]
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

USERNAMES = {
    503493798: "@fdevosor",
    515714808: "@Jervene17",
}

MEMBER_LISTS = {
    "FAMILY FEMALES": ["Fatima", "Vangie", "Hannah", "M Ru", "Dcn Frances", "Shayne", "Dcn Issa"],
    "FAMILY MALES": ["Dcn Ian", "M Jervene", "Jessie", "Fernan", "Almen", "Dcn Probo", "Mjhay"],
    "CAREER MALES": ["Jabs", "Xander", "Franz", "Daniel", "Jiboy", "Venancio", "Iven", "Taiki"],
    "CAREER FEMALES 1": ["Shaja", "Grace", "Daryl", "Clarice", "Mia", "Aliza", "Anica"],
    "CAREER FEMALES 2": ["Mel", "Andrea", "Angel", "Inia", "M Rose", "Vicky", "Donna"],
    "CAREER FEMALES 3": ["D Rue", "PP Bam", "Zhandra", "Trina", "Dr Kristine", "Riza", "Saeyong", "Mirasol", "Joan"],
    "CAMPUS FEMALES": ["Divine", "Marinell"],
    "JS FEMALES": ["MCor", "Tita Merlita", "Grace", "Emeru", "Randrew Dela Cruz", "John Carlo Lucero", "Cherry Ann", "Rhea Cho", "Gemma", "Yolly", "Weng"],
}

FAILOVER_CHAIN = {
    "FAMILY FEMALES": [503493798, 515714808],
    "FAMILY MALES": [515714808, 503493798],
    "CAREER MALES": [222222222, 515714808],
    "CAMPUS MALES": [666666666, 515714808],
    "CAREER FEMALES 1": [333333333, 515714808],
    "CAREER FEMALES 2": [101010101, 515714808],
    "CAREER FEMALES 3": [999999999, 515714808],
    "CAMPUS FEMALES": [444444444, 515714808],
    "JS FEMALES": [555555555, 515714808],
}

user_sessions = {}
submission_progress = {
    "group_message_id": None,
    "chat_id": None,
    "label": None,
    "total": 0,
    "submitted": set()
}

async def send_attendance_prompt(user_id, bot: Bot, context=None, custom_text="Who did you miss this Predawn?"):
    group = USER_GROUPS.get(user_id)
    members = MEMBER_LISTS.get(group, []).copy()
    chat_id = context.bot_data.get("user_chats", {}).get(user_id)

    label = context.bot_data.setdefault("context_by_user", {}).get(user_id, custom_text.split("this ")[-1].replace("?", ""))
    excluded = EXCLUSIONS.get(label, {}).get(group, [])
    members = [m for m in members if m not in excluded]

    if not members:
        await bot.send_message(chat_id=chat_id, text="✅ No members to report for this service.")
        return

    context.bot_data["context_by_user"][user_id] = label

    user_sessions[user_id] = {
        "group_tab": group,
        "members": members.copy(),
        "selected": [],
        "reasons": {},
        "prompt_time": datetime.datetime.now()
    }

    keyboard = [[InlineKeyboardButton(name, callback_data=name)] for name in members]
    keyboard.append([InlineKeyboardButton("✅ ALL ACCOUNTED", callback_data="ALL ACCOUNTED")])

    await bot.send_message(chat_id=chat_id, text=custom_text, reply_markup=InlineKeyboardMarkup(keyboard))

    async def delayed_fallback():
        await asyncio.sleep(3600)  # 1 hour
        if user_id in user_sessions:
            await check_for_response_timeout(user_id, group, bot, context)

    asyncio.create_task(delayed_fallback())

async def check_for_response_timeout(user_id, group, bot: Bot, context):
    if user_id in user_sessions:
        chain = FAILOVER_CHAIN.get(group, [])
        if user_id in chain:
            idx = chain.index(user_id)
            if idx + 1 < len(chain):
                next_user = chain[idx + 1]
                chat_id = context.bot_data.get("user_chats", {}).get(next_user)
                if chat_id:
                    await send_attendance_prompt(next_user, bot, context, custom_text=f"{group} checker didn't respond. Please handle attendance.")

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

        # Update group progress
        submission_progress["submitted"].add(user_id)
        await update_group_progress(context)
    else:
        session["selected"].append(selected)
        session["members"].remove(selected)
        context.user_data["awaiting_reason"] = selected
        await query.message.reply_text(f"Why did you miss {selected}?")
        keyboard = [[InlineKeyboardButton(name, callback_data=name)] for name in session["members"]]
        keyboard.append([InlineKeyboardButton("✅ ALL ACCOUNTED", callback_data="ALL ACCOUNTED")])
        await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(keyboard))

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

async def update_group_progress(context: ContextTypes.DEFAULT_TYPE):
    if submission_progress["group_message_id"] and submission_progress["chat_id"]:
        submitted = len(submission_progress["submitted"])
        total = submission_progress["total"]
        remaining = [USERNAMES.get(uid, f"User {uid}") for uid in submission_progress["all_users"] if uid not in submission_progress["submitted"]]
        mention_str = ", ".join(remaining)
        text = f"✅ {submitted}/{total} submitted."
        if remaining:
            text += f"\nStill waiting for: {mention_str}"
        else:
            text += "\n🎉 All submitted."
        try:
            await context.bot.edit_message_text(chat_id=submission_progress["chat_id"], message_id=submission_progress["group_message_id"], text=text)
        except:
            pass

async def start_submission(update: Update, context: ContextTypes.DEFAULT_TYPE, label):
    group_chat_id = update.effective_chat.id
    all_users = list(USER_GROUPS.keys())
    submission_progress.update({
        "group_message_id": None,
        "chat_id": group_chat_id,
        "label": label,
        "submitted": set(),
        "total": len(all_users),
        "all_users": all_users
    })
    msg = await context.bot.send_message(chat_id=group_chat_id, text=f"📝 Logging for {label} started. 0/{len(all_users)} submitted.")
    submission_progress["group_message_id"] = msg.message_id
    for user_id in all_users:
        chat_id = context.bot_data.get("user_chats", {}).get(user_id)
        if chat_id:
            await send_attendance_prompt(user_id, context.bot, context, custom_text=f"Who did you miss this {label}?")

async def predawn_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await start_submission(update, context, "Predawn")

async def wednesday_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await start_submission(update, context, "Wednesday")

async def sunday_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await start_submission(update, context, "Sunday")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    group = USER_GROUPS.get(user_id)
    if not group:
        await update.message.reply_text("❌ You are not assigned to a group.")
        return
    context.bot_data.setdefault("user_chats", {})[user_id] = update.effective_chat.id
    await update.message.reply_text("✅ You are now registered with the bot.")

async def main():
    application = ApplicationBuilder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("predawn", predawn_command))
    application.add_handler(CommandHandler("wednesday", wednesday_command))
    application.add_handler(CommandHandler("sunday", sunday_command))
    application.add_handler(CallbackQueryHandler(handle_button))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_reason))
    print("🤖 Bot is running...")
    await application.run_polling()

if __name__ == "__main__":
    asyncio.run(main())
