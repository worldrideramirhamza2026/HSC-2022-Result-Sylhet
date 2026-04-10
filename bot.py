from flask import Flask
from threading import Thread

# ================= KEEP ALIVE =================
app_web = Flask('')

@app_web.route('/')
def home():
    return "Bot is running!"

def run():
    app_web.run(host='0.0.0.0', port=10000)

def keep_alive():
    t = Thread(target=run)
    t.start()

# ================= ORIGINAL CODE =================
import requests
import time
import csv
import os
from bs4 import BeautifulSoup
from telegram import Update, ReplyKeyboardMarkup, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes

TOKEN = "8643223258:AAF2qByjhoWCUhgWqv1_zWkoaHMx6anPwXg"
FILE_NAME = "data.csv"

last_range = {}

def init_file():
    if not os.path.exists(FILE_NAME):
        with open(FILE_NAME, "w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow(["Name","Roll","Board","Mobile","Date","TranID"])

def is_duplicate(tran_id):
    if not os.path.exists(FILE_NAME):
        return False
    with open(FILE_NAME, "r", encoding="utf-8") as f:
        return any(tran_id in row for row in f)

def save_data(name, roll, board, mobile, date, tran_id):
    if is_duplicate(tran_id):
        return
    with open(FILE_NAME, "a", newline="", encoding="utf-8") as f:
        csv.writer(f).writerow([name, roll, board, mobile, date, tran_id])

def get_tran_ids(roll):
    url = f"https://billpay.sonalibank.com.bd/BoardRescrutiny/Home/Search?searchStr={roll}"
    res = requests.get(url)
    soup = BeautifulSoup(res.text, "html.parser")

    ids = []
    try:
        rows = soup.find("table").find_all("tr")[1:]
        for r in rows:
            ids.append(r.find_all("td")[1].text.strip())
    except:
        pass

    return ids

def get_full_data(tran_id):
    url = f"https://billpay.sonalibank.com.bd/BoardRescrutiny/Home/Voucher/{tran_id}"
    res = requests.get(url)
    soup = BeautifulSoup(res.text, "html.parser")

    try:
        lines = [l.strip() for l in soup.get_text("\n").split("\n") if l.strip()]

        def find(label):
            for i in range(len(lines)):
                if label in lines[i]:
                    return lines[i+1]
            return "Not found"

        name = find("Name")
        roll = find("Roll")
        board = find("Board")
        mobile = find("Mobile")
        date = find("Date")

        save_data(name, roll, board, mobile, date, tran_id)

        text = f"""<pre>
Name   : {name}
Roll   : {roll}
Board  : {board}
Mobile : {mobile}
Date   : {date}
ID     : {tran_id}
</pre>"""

        return text, mobile
    except:
        return None, None

def format_number_bd(mobile):
    n = mobile.replace("+","").replace(" ","")
    if n.startswith("01"):
        return "880"+n[1:]
    if n.startswith("880"):
        return n
    return None

def get_contact_buttons(mobile):
    n = format_number_bd(mobile)
    if not n:
        return None

    return InlineKeyboardMarkup([[
        InlineKeyboardButton("📱 WhatsApp", url=f"https://wa.me/{n}"),
        InlineKeyboardButton("✈️ Telegram", url=f"https://t.me/+{n}")
    ]])

def next_button():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➡️ Next 50", callback_data="next50")]
    ])

def get_keyboard():
    return ReplyKeyboardMarkup(
        [["🚀 Start"],["📂 Search Database"],["📥 Download Data"]],
        resize_keyboard=True
    )

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 Welcome!", reply_markup=get_keyboard())

async def run_range(message, context, start, end):
    status = await message.reply_text("⏳ Processing...")
    count = 0

    for roll in range(start, end+1):
        await status.edit_text(f"⏳ Processing...\n🔢 Roll: {roll}\n📊 Found: {count}")

        for tid in get_tran_ids(roll):
            data, mobile = get_full_data(tid)

            if data:
                count += 1
                await message.reply_text(
                    f"📄 Result {count}:\n{data}",
                    parse_mode="HTML",
                    reply_markup=get_contact_buttons(mobile)
                )

        time.sleep(2)

    await status.edit_text(f"✅ Done!\n📊 Total: {count}")
    await message.reply_text("👉 Next 50?", reply_markup=next_button())

async def handle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    user_id = update.message.from_user.id

    if text == "🚀 Start":
        await update.message.reply_text("✅ Ready!", reply_markup=get_keyboard())
        return

    if text == "📂 Search Database":
        await update.message.reply_text("👉 Roll বা Range দাও (max 50)")
        return

    if text == "📥 Download Data":
        if os.path.exists(FILE_NAME):
            await update.message.reply_document(open(FILE_NAME,"rb"))
        else:
            await update.message.reply_text("❌ No data")
        return

    if text.isdigit():
        await update.message.reply_text("⏳ Searching...")
        for i, tid in enumerate(get_tran_ids(int(text)),1):
            data, mobile = get_full_data(tid)
            if data:
                await update.message.reply_text(
                    f"📄 Result {i}:\n{data}",
                    parse_mode="HTML",
                    reply_markup=get_contact_buttons(mobile)
                )
        return

    if "-" in text:
        try:
            start_r, end_r = map(int, text.split("-"))
        except:
            await update.message.reply_text("❌ Wrong format")
            return

        if (end_r-start_r+1) > 50:
            await update.message.reply_text("❌ Max 50")
            return

        last_range[user_id] = (start_r, end_r)
        await run_range(update.message, context, start_r, end_r)
        return

    await update.message.reply_text("❌ Invalid input")

async def handle_next(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id

    if user_id not in last_range:
        await query.message.reply_text("❌ আগে search করো")
        return

    start_r, end_r = last_range[user_id]
    new_start = end_r + 1
    new_end = end_r + 50

    last_range[user_id] = (new_start, new_end)

    await query.message.reply_text(f"🔄 Auto: {new_start}-{new_end}")
    await run_range(query.message, context, new_start, new_end)

# ================= RUN =================
init_file()
keep_alive()  # 🔥 THIS IS THE MAGIC

app = ApplicationBuilder().token(TOKEN).build()

app.add_handler(CommandHandler("start", start))
app.add_handler(MessageHandler(filters.TEXT, handle))
app.add_handler(CallbackQueryHandler(handle_next))

print("🤖 BOT RUNNING 24/7...")
app.run_polling()